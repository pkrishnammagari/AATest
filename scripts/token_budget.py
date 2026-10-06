"""Per-pass prompt-token budget of the AI analysis, measured by the model server.

Every analysis pass (lens H, lens W, risk, checklist, memo) is built by the
blocks themselves, through a recording provider that keeps each system and
user turn and answers with a canned, validator-proof reply, so the next block
has the input it would have in a real run. Each recorded turn is then posted
to Ollama with `num_predict: 1`: the server tokenises the whole prompt and
returns `prompt_eval_count` within a second or two, without generating. The
numbers are the model's own tokens, not a characters / 4 estimate (which
undercounts the tables of raw numbers by about 1.6x).

The canned replies make the turns deterministic, so a before/after table
compares like with like:

    lens H      no typed hypothesis -> the Python candidate list is verified
                (pass W then reads the same verified facts every run; a real
                run's pass W reads the facts the model's hypotheses produced)
    lens W      one finding per payload fact of the trajectory, behaviour and
                inconsistency themes (claim = the fact's text), up to 6
    risk        one finding per risk fact, up to 6
    checklist   each step "attention", one indicator per step (its first fact)
    memo        reads those items: the real memo framing over item texts of
                realistic length

Reply sizes are not measured here (they need a real generation; the
evaluation harness prints them per pass).

Needs the local Ollama with the AI Analysis model -- gpt-oss:120b, or the
model AECB_OLLAMA_MODEL selects (read from ~/etc/aecb-analyzer/aecb.env as the
app reads it); skips (exit 0) without it. The two models share a tokenizer and
chat template, so their counts should agree within a few tokens
(docs/AI_ANALYSIS_MRM.md section 9). Development tool: scripts/ is excluded
from the release archive.

    python3 scripts/token_budget.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aecb import brief, context, settings  # noqa: E402
from aecb.brief import ollama  # noqa: E402
from aecb.brief.prompts import checklist as checklist_prompt  # noqa: E402
from aecb.brief.prompts import hypotheses as h_prompt  # noqa: E402
from aecb.brief.prompts import lens as lens_prompt  # noqa: E402
from aecb.brief.prompts import memo as memo_prompt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = (
    ("delinquent", "1_SyntheticJSONPayload_Delinquent_MultiFacility.json"),
    ("patterns", "2_SyntheticJSONPayload_Patterns.json"),
    ("archive", "aecb_payload_archive_170623.json"),
)
PASSES = ("lens H", "lens W", "risk", "checklist", "memo")

_CANNED_FINDINGS = 6


class Recorder:
    """A provider that records every turn and replies with canned output."""

    NAME, DATA_NOTE = ollama.NAME, ollama.DATA_NOTE
    model = staticmethod(ollama.model)

    def __init__(self):
        self.analysis = None
        self.turns = []

    @staticmethod
    def probe():
        return ""

    def chat(self, system, user, schema, effort=""):
        self.turns.append((system, user, schema, effort))
        if schema is h_prompt.HYPOTHESES_SCHEMA:
            return {"hypotheses": []}
        if schema is lens_prompt.FINDINGS_SCHEMA:
            return {"findings": self._findings(("trajectory", "behavior",
                                                "inconsistency")),
                    "unknowns": [], "background": []}
        if schema is checklist_prompt.CHECKLIST_SCHEMA:
            return self._checklist()
        if schema is memo_prompt.MEMO_SCHEMA:
            return {"outcome": "Refer", "confidence": "low", "drivers": [],
                    "conditions": [], "counter_considerations": [],
                    "what_would_change_this": "", "sections": {}}
        return {"findings": self._findings(("risk",)), "sector_inferences": []}

    def _findings(self, themes):
        facts = [f for f in self.analysis["facts"] if f["theme"] in themes]
        return [{"claim": f["text"], "so_what": "", "severity": "watch",
                 "confidence": "low", "cites": [f["id"]], "framing": "story"}
                for f in facts[:_CANNED_FINDINGS]]

    def _checklist(self):
        facts_by_id = self.analysis["facts_by_id"]
        out = {}
        for packet in self.analysis["packets"]:
            ids = [fid for fid in packet["fact_ids"] if fid in facts_by_id]
            out["step_%02d" % packet["step"]] = {
                "status": "attention",
                "indicators": [{"bullet": facts_by_id[ids[0]]["text"],
                                "severity": "attention", "cites": ids[:1]}]
                if ids else []}
        return out


def turns_for(path):
    """{pass name: (system, user, schema, effort)} as the blocks build them."""
    ctx = context.from_file(path)
    recorder = Recorder()
    analysis = brief.new_analysis(ctx, recorder)
    recorder.analysis = analysis
    for name in ("lens", "risk", "checklist", "memo"):
        brief.generate_block(ctx, recorder, analysis, name)
    names = list(PASSES)
    if len(recorder.turns) < len(names):
        names.remove("risk")  # no risk fact on this file: no model pass
    return dict(zip(names, recorder.turns))


def prompt_tokens(system, user, schema, effort) -> int:
    tag = ollama.model()
    payload = {
        "model": tag,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "format": schema,
        "options": dict(ollama._OPTIONS, num_predict=1),
    }
    if effort:
        payload["think"] = effort  # as the client sends it (no effect on the count)
    return ollama._post("/api/chat", payload, ollama.TIMEOUT_S[tag])["prompt_eval_count"]


def main():
    problem = settings.load_local()
    if problem:
        print("note: %s" % problem, file=sys.stderr)
    reason = ollama.probe()
    if reason:
        print("SKIP: %s" % reason)
        return
    table = {}
    for label, name in FIXTURES:
        for pass_, (system, user, schema, effort) in turns_for(
                os.path.join(ROOT, "ReferenceJSON", name)).items():
            table[(pass_, label)] = (prompt_tokens(system, user, schema, effort),
                                     (len(system) + len(user)) // 4)
    print("Prompt tokens per pass, measured by Ollama with %s (chars/4 "
          "estimate in brackets); prompt version %s"
          % (ollama.model(), brief.PROMPT_VERSION))
    labels = [label for label, _ in FIXTURES]
    print("%-10s %s" % ("pass", "".join("%20s" % label for label in labels)))
    totals = dict.fromkeys(labels, 0)
    for pass_ in PASSES:
        cells = []
        for label in labels:
            measured, estimate = table.get((pass_, label), (0, 0))
            totals[label] += measured
            cells.append("%20s" % ("%s (%s)" % (format(measured, ","),
                                                format(estimate, ","))))
        print("%-10s %s" % (pass_, "".join(cells)))
    print("%-10s %s" % ("total", "".join("%20s" % format(totals[label], ",")
                                         for label in labels)))


if __name__ == "__main__":
    main()
