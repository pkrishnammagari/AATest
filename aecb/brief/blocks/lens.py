"""Block 1 -- the fresh lens, as a hypothesis -> verification loop.

Pass H: the model reads the payload as raw tables (derive/brief_facts/tables)
with a headline index of the digest and proposes typed hypotheses in a closed
grammar (brief/hypotheses/grammar). Python verifies each one
(brief/hypotheses/verify); confirmed and refuted results become facts with
theme "verified", numbered after the digest. If the model proposed no typed
hypothesis, a Python candidate list runs through the same verifiers
(brief/hypotheses/candidates) and the block says so.

Pass W: the findings pass over the digest plus the verified facts, validated
by the citation, verbatim-figure and named-entity guards, with a framing per
finding and the refuted-only severity cap.

The model's custom (free-text) hypotheses are never verified: they are vouched
against the tables they were proposed from and shown apart as unverified
observations -- never findings, never memo input.
"""

from __future__ import annotations

from ...derive import brief_facts
from ...derive.brief_facts import tables as tables_mod
from ...derive.brief_facts._common import RISK, contract_label
from ...derive.brief_facts.steps import STEP
from .. import validate
from ..hypotheses import candidates, grammar, verify
from ..prompts import hypotheses as h_prompt
from ..prompts import lens as prompt

SOURCE_MODEL = "model"
SOURCE_FALLBACK = "fallback"
SOURCE_NONE = "none"


def _hypotheses(ctx, analysis, provider, tables):
    """(verified results, custom texts, source, the H user turn, drops)."""
    index = brief_facts.index(analysis["facts"], brief_facts.H_INDEX_THEMES)
    message = h_prompt.user_message(ctx, tables["text"], index)
    analysis["check_prohibited"](message)
    raw = provider.chat(h_prompt.SYSTEM, message, h_prompt.HYPOTHESES_SCHEMA,
                        h_prompt.EFFORT)
    typed, custom, dropped = grammar.parse(raw, tables["aliases"])
    source = SOURCE_MODEL
    if not typed:
        typed = candidates.generate(ctx, tables["aliases"])
        source = SOURCE_FALLBACK if typed else SOURCE_NONE
    return verify.run(ctx, typed, tables["aliases"]), custom, source, message, dropped


def _w_reads(analysis, facts) -> list:
    """Pass W's input: the payload lenses and the verified facts, and of the
    checklist's step facts only the tripwires on this file and the validity
    fact (findings cite it); the rest of the step facts restate digest
    facts. The risk lenses are block 2's input and would only repeat here."""
    keep = {fid for p in analysis["packets"] for fid in p["tripwires"]}
    for packet in analysis["packets"]:
        if packet["key"] == "validity":
            keep.update(packet["fact_ids"])
    return [f for f in facts if f["theme"] != RISK
            and (f["theme"] != STEP or f["id"] in keep)]


def generate(ctx, analysis, provider) -> dict:
    tables = tables_mod.build(ctx)
    results, custom, source, h_message, dropped = _hypotheses(
        ctx, analysis, provider, tables)
    new_facts = verify.as_facts(results, len(analysis["facts"]) + 1)
    facts = analysis["facts"] + new_facts
    confirmed = [f["id"] for f in new_facts if f["status"] == verify.CONFIRMED]
    read = _w_reads(analysis, facts)
    message = prompt.user_message(ctx, brief_facts.digest(read), confirmed)
    analysis["check_prohibited"](message)
    raw = provider.chat(prompt.SYSTEM, message, prompt.FINDINGS_SCHEMA,
                        prompt.EFFORT)
    # Held to exactly what W read: a cite of a fact it never saw is unknown.
    findings, background, unknowns, dropped_w = validate.validate(raw, read)
    labels = {alias: (contract_label(ctx, c), str(c.get("CBContractId") or ""))
              for alias, c in tables["aliases"].items()}
    # An alias resolves to the label Python minted for it, so the labels
    # vouch alongside the text the observation was proposed from.
    proposed_from = "\n".join([h_message] + [label for label, _ in labels.values()])
    observations, dropped_o = validate.validate_observations(custom, proposed_from,
                                                             labels)
    return {
        "findings": findings,
        "background": background,
        "unknowns": unknowns,
        "observations": observations,
        "hypotheses": [{"type": r["type"], "params_text": r["params_text"],
                        "status": r["status"], "text": r["text"]}
                       for r in results],
        "hypotheses_source": source,
        "tables_months": tables["months"],
        "new_facts": new_facts,
        "dropped": dropped + dropped_w + dropped_o,
    }


def summary(block) -> str:
    """One phrase for the sidebar: '6 findings, 3 confirmed, 1 dropped'."""
    confirmed = sum(1 for h in block.get("hypotheses") or []
                    if h["status"] == verify.CONFIRMED)
    return "%d finding(s), %d confirmed hypothesis(es), %d dropped" % (
        len(block["findings"]), confirmed, len(block["dropped"]))
