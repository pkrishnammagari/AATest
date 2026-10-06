"""Fast gate for the AI analysis.

Runs the full fresh-lens pipeline -- fact digest, step packets, the
hypothesis pass, verification, the findings pass, validation, render --
against the committed delinquent fixture and asserts that at least three
findings survive validation.

The model pass goes to the provider AECB_ENV selects (unset: dev, Ollama with
the AI Analysis model on localhost -- gpt-oss:120b, or the model
AECB_OLLAMA_MODEL selects; uat/prod: Core42, aecb/brief/providers.py). Both
settings are read from ~/etc/aecb-analyzer/aecb.env as the app reads them.
When that provider cannot serve (CI, the air-gapped server, Core42 not yet
onboarded) the check SKIPS with exit 0 rather than failing: model absence is
a deployment state the app already degrades through, not a code defect.
Everything the gate can verify without a model -- that the digest builds,
that the AI Analysis renders into the page -- still runs first.

    python3 scripts/check_brief.py
    AECB_ENV=uat python3 scripts/check_brief.py     # against Core42
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aecb import brief, context, runtime, settings  # noqa: E402
from aecb.brief import validate  # noqa: E402
from aecb.derive import brief_facts  # noqa: E402
from aecb.render.page import render_page  # noqa: E402

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ReferenceJSON", "1_SyntheticJSONPayload_Delinquent_MultiFacility.json")

MIN_FINDINGS = 3


def fail(message):
    print("FAIL: %s" % message)
    raise SystemExit(1)


def check_validator():
    """The guard suite, model-free: what must drop, drops; what must pass,
    passes. Every case here is a hallucination class seen or anticipated."""
    facts = [
        {"id": "F001", "theme": "structure",
         "text": "Total exposure AED 115,300; utilization 34% as of 2025-03. "
                 "Employer on file: DU TELECOM.",
         "fields": ["contractsTotalSummary.TotalExposure"],
         "section": "facilities"},
    ]

    def run(finding_kwargs, unknowns=None, background=None):
        base = {"claim": "x", "severity": "info", "confidence": "low",
                "cites": ["F001"]}
        base.update(finding_kwargs)
        return validate.validate({"findings": [base],
                                  "unknowns": unknowns or [],
                                  "background": background or []}, facts)

    # verbatim normalizer: %, decimals, thousands separators, date fragments
    for claim in ("Exposure is AED 115300.", "Utilization was 34.0%.",
                  "As of March 2025, utilization stood at 34%."):
        found, _, _, dropped = run({"claim": claim})
        if len(found) != 1:
            fail("normalizer rejected a verbatim claim %r: %s"
                 % (claim, dropped))
    # invented figure drops
    found, _, _, dropped = run({"claim": "Exposure is AED 999,000."})
    if found or "figures" not in dropped[0]:
        fail("invented figure survived: %s" % dropped)
    # unknown cite drops
    found, _, _, dropped = run({"cites": ["F999"], "claim": "Anything."})
    if found:
        fail("unknown cite survived")
    # proper-noun guard: vouched name passes, invented name drops,
    # sentence-initial capital is exempt
    found, _, _, dropped = run(
        {"claim": "The employer DU TELECOM reported 34%."})
    if len(found) != 1:
        fail("vouched employer name was dropped: %s" % dropped)
    found, _, _, dropped = run(
        {"claim": "The employer Falcon Trading reported 34%."})
    if found or "names" not in dropped[0]:
        fail("invented employer name survived: %s" % dropped)
    found, _, _, dropped = run({"claim": "Utilization reached 34% in 2025."})
    if len(found) != 1:
        fail("sentence-initial word tripped the name guard: %s" % dropped)
    # inline fact references are stripped, not treated as invented figures
    found, _, _, dropped = run(
        {"claim": "Utilization stood at 34% (F001), per the fact table F001."})
    if len(found) != 1 or "F001" in found[0]["claim"]:
        fail("inline fact refs mishandled: %r / %s"
             % (found and found[0]["claim"], dropped))
    # unknowns: digest-vouched passes; invented figure and name drop; deduped
    _, _, unknowns, dropped = run({}, unknowns=[
        "Income for DU TELECOM is not corroborated.",
        "Income for DU TELECOM is not corroborated.",
        "A balance of AED 500,000 is unexplained.",
        "The record at Falcon Trading is unverified.",
    ])
    if unknowns != ["Income for DU TELECOM is not corroborated."]:
        fail("unknowns validation wrong: %r / %s" % (unknowns, dropped))
    # background: cite guards apply, no severity; invented name drops
    _, background, _, dropped = run({}, background=[
        {"note": "The employer DU TELECOM sits in the telecom sector.",
         "cites": ["F001"]},
        {"note": "Falcon Trading operates in a volatile sector.",
         "cites": ["F001"]},
        {"note": "Uncited texture.", "cites": []},
    ])
    if len(background) != 1 or "TELECOM" not in background[0]["note"]:
        fail("background validation wrong: %r / %s" % (background, dropped))
    # observations: vouched by the tables they came from; invented figures
    # and names drop; deduped; capped at 3
    tables = "K1 | Credit Card C41880273 (B01) | card | 45000 | 52340\nDU TELECOM | 2025-09"
    kept, dropped = validate.validate_observations(
        ["The card at 52340 looks maxed.", "The card at 52340 looks maxed.",
         "Balance of AED 999,000 unexplained.", "Falcon Trading employs them.",
         "A second note.", "A third note.", "A fourth note."], tables)
    if kept != ["The card at 52340 looks maxed.", "A second note.",
                "A third note."] or len(dropped) != 4:
        fail("observations validation wrong: %r / %s" % (kept, dropped))
    # refuted-only cap: a finding citing only refuted hypotheses is at most watch
    refuted = facts + [{"id": "F002", "theme": "verified", "status": "not_supported",
                        "text": "Verified hypothesis (not supported): no swing.",
                        "fields": [], "section": "detail"}]
    found, _, _, dropped = validate.validate(
        {"findings": [{"claim": "A severe pattern.", "severity": "severe",
                       "confidence": "high", "cites": ["F002"],
                       "framing": "story"}],
         "unknowns": [], "background": []}, refuted)
    if not found or found[0]["severity"] != "watch" or "capped" not in dropped[0]:
        fail("refuted-only cap failed: %r / %s" % (found, dropped))
    found, _, _, _ = validate.validate(
        {"findings": [{"claim": "A severe pattern.", "severity": "severe",
                       "confidence": "high", "cites": ["F001", "F002"],
                       "framing": "story"}],
         "unknowns": [], "background": []}, refuted)
    if not found or found[0]["severity"] != "severe" or found[0]["framing"] != "story":
        fail("a finding with a non-refuted cite was capped or lost its framing")
    # risk block: basis derived from cites, inferred capped at watch, the
    # register's sector words allow-listed, employer inferences vouched
    from aecb.brief.blocks import risk as risk_block
    risk_facts = {
        "F001": facts[0],
        "F002": {"id": "F002", "theme": "background", "section": None, "fields": [],
                 "text": "[register: sectors under stress] Construction is cyclical."},
    }
    vocab = {"telecom": "Telecommunications", "construction": "Construction"}
    found, inferences, dropped = risk_block.validate_risk({"findings": [
        {"claim": "Exposure AED 115,300 at DU TELECOM, a Telecom employer.",
         "so_what": "x", "severity": "severe", "confidence": "high",
         "cites": ["F001"], "inferred_sector": "telecom"},
        {"claim": "Exposure AED 115,300 beside the Construction note.",
         "so_what": "x", "severity": "adverse", "confidence": "high",
         "cites": ["F001", "F002"]},
        {"claim": "Falcon Trading is exposed.", "so_what": "x", "severity": "info",
         "confidence": "low", "cites": ["F001"]},
    ], "sector_inferences": [{"employer": "DU TELECOM", "sector": "telecom"},
                             {"employer": "Falcon Trading", "sector": "telecom"}]},
        risk_facts, vocab, {"du telecom": "DU TELECOM"})
    if [(f["basis"], f["severity"]) for f in found] != [
            ("payload+context", "adverse"), ("inferred", "watch")]:
        fail("risk basis/cap wrong: %r / %s" % ([(f["basis"], f["severity"]) for f in found], dropped))
    if len(inferences) != 1 or not any("Falcon" in d for d in dropped):
        fail("sector inference vouching wrong: %r / %s" % (inferences, dropped))
    print("validator: guard suite OK")


def load_settings():
    """AECB_ENV and AECB_OLLAMA_MODEL from ~/etc/aecb-analyzer/aecb.env,
    like the app, so the gate runs the model the app would. Called from
    main(), never at import: the test suite imports this module."""
    problem = settings.load_local()
    if problem:
        print("note: %s" % problem, file=sys.stderr)


def main():
    load_settings()
    check_validator()

    ctx = context.from_file(FIXTURE)

    # --- model-free checks first ------------------------------------------
    facts = brief_facts.build(ctx)
    if len(facts) < 5:
        fail("digest built only %d facts from the delinquent fixture"
             % len(facts))
    ids = [f["id"] for f in facts]
    if len(ids) != len(set(ids)):
        fail("digest fact ids are not unique")
    # Prohibited-fields policy (see brief_facts docstring): nationality,
    # gender and residency must never reach the model, in any form.
    for fact in facts:
        haystack = fact["text"] + " " + " ".join(fact["fields"])
        for banned in brief_facts.PROHIBITED_FIELDS:
            if banned.lower() in haystack.lower():
                fail("prohibited field %r appears in fact %s"
                     % (banned, fact["id"]))
    print("digest: %d facts (%s), prohibited-fields clean"
          % (len(facts), ", ".join(sorted({f["theme"] for f in facts}))))

    # The checklist's step packets: ten, every one with facts, the
    # arithmetic facts prohibited-field clean, step 2 age only.
    from aecb.derive.brief_facts import steps
    packets, rows = steps.build_packets(ctx, facts)
    if [p["step"] for p in packets] != list(range(1, 11)) or \
            not all(p["fact_ids"] for p in packets):
        fail("step packets are not ten non-empty packets")
    text = steps.packets_text(packets, brief_facts.by_id(rows))
    for banned in brief_facts.PROHIBITED_FIELDS:
        if banned.lower() in text.lower():
            fail("prohibited field %r appears in the step packets" % banned)
    print("packets: 10 steps, %d facts (%d added), %d tripwire(s)"
          % (len(rows), len(rows) - len(facts),
             sum(len(p["tripwires"]) for p in packets)))

    provider = brief.for_environment(runtime.environment(default=runtime.DEV))
    print("provider: %s (%s)" % (provider.NAME, provider.model() or "no model"))
    reason = provider.probe()
    if reason:
        print("SKIP model pass: %s" % reason)
        return

    # --- the model passes (the fresh-lens block: H, verify, W) --------------
    analysis = brief.new_analysis(ctx, provider)
    result = brief.generate_block(ctx, provider, analysis, "lens")
    findings, dropped = result["findings"], result["dropped"]
    print("model: %d finding(s) validated, %d dropped"
          % (len(findings), len(dropped)))
    for note in dropped:
        print("  dropped: %s" % note)
    for finding in findings:
        print("  [%s/%s] %s  <- %s" % (finding["severity"],
                                       finding["confidence"],
                                       finding["claim"],
                                       ",".join(finding["cites"])))
    print("  hypotheses: %s (tables at %d months)"
          % (result["hypotheses_source"], result["tables_months"]))
    for h in result["hypotheses"]:
        print("  [%s] %s" % (h["status"], h["text"][:140]))
    for note in result["observations"]:
        print("  [observation] %s" % note)
    for note in result["background"]:
        print("  [background] %s  <- %s" % (note["note"],
                                            ",".join(note["cites"])))
    for unknown in result["unknowns"]:
        print("  [unknown] %s" % unknown)

    if len(findings) < MIN_FINDINGS:
        fail("only %d validated finding(s); the gate wants >= %d"
             % (len(findings), MIN_FINDINGS))

    # --- the risk block ---------------------------------------------------
    risk = brief.generate_block(ctx, provider, analysis, "risk")
    print("risk: %d finding(s), basis %s, %d inference(s), %d dropped"
          % (len(risk["findings"]), risk["basis_counts"],
             len(risk["sector_inferences"]), len(risk["dropped"])))
    for finding in risk["findings"]:
        print("  [%s/%s] %s  <- %s" % (finding["severity"], finding["basis"],
                                       finding["claim"][:150], ",".join(finding["cites"])))
    for inference in risk["sector_inferences"]:
        print("  [sector] %s -> %s" % (inference["employer"], inference["sector"]))
    for note in risk["dropped"]:
        print("  dropped: %s" % note)

    # --- the analysis must reach the page ---------------------------------
    ctx.analysis = analysis
    html = render_page(ctx, analysis_open=True)
    # Probe for MARKUP, not the substring: the inlined stylesheet mentions
    # .bf-card whether or not any finding rendered.
    if 'class="bf-card"' not in html:
        fail("findings did not render into the analysis view")
    if "No validated findings" in html:
        fail("the lens block rendered its empty state despite findings")
    for finding in findings:
        probe_text = finding["claim"][:40].replace("&", "&amp;") \
            .replace("<", "&lt;").replace(">", "&gt;")
        if probe_text not in html:
            fail("claim missing from the page: %r" % finding["claim"][:60])
    print("render: analysis present in the standalone HTML")

    print("OK")


if __name__ == "__main__":
    main()
