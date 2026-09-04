"""Phase-1 gate for the AI underwriting brief.

Runs the full pipeline -- fact digest, one local-model pass, validation,
render -- against the committed delinquent fixture and asserts the exit
criterion from the brief plan: at least three findings survive validation.

Needs Ollama with the brief's model on localhost. When the service is absent
(CI, the air-gapped server) the check SKIPS with exit 0 rather than failing:
model absence is a deployment state the app already degrades through, not a
code defect. Everything the gate can verify without a model -- that the digest
builds, that the brief renders into the page -- still runs first.

    python3 scripts/check_brief.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aecb import brief, context  # noqa: E402
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
    # synthesis: vouched by findings passes; anything else degrades to ''
    findings = [{"claim": "Exposure is AED 115,300 at DU TELECOM.",
                 "suggested_action": ""}]
    if validate.validate_synthesis(
            "Overall, exposure of AED 115,300 sits with DU TELECOM.",
            findings) == "":
        fail("vouched synthesis was rejected")
    if validate.validate_synthesis(
            "Exposure of AED 999 at Falcon Trading.", findings) != "":
        fail("unvouched synthesis survived")
    print("validator: guard suite OK")


def main():
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

    reason = brief.probe()
    if reason:
        print("SKIP model pass: %s" % reason)
        return

    # --- the model pass ---------------------------------------------------
    result = brief.generate_brief(ctx)
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
    if result["synthesis"]:
        print("  [synthesis] %s" % result["synthesis"])
    for note in result["background"]:
        print("  [background] %s  <- %s" % (note["note"],
                                            ",".join(note["cites"])))
    for unknown in result["unknowns"]:
        print("  [unknown] %s" % unknown)

    if len(findings) < MIN_FINDINGS:
        fail("only %d validated finding(s); the phase-1 exit test wants >= %d"
             % (len(findings), MIN_FINDINGS))

    # --- the brief must reach the page ------------------------------------
    ctx.brief = result
    html = render_page(ctx)
    # Probe for MARKUP, not the substring: the inlined stylesheet mentions
    # .bf-card whether or not any finding rendered.
    if 'class="bf-card"' not in html:
        fail("findings did not render into the rail")
    if 'class="rail-empty"' in html:
        fail("rail rendered its empty state despite attached findings")
    for finding in findings:
        probe_text = finding["claim"][:40].replace("&", "&amp;") \
            .replace("<", "&lt;").replace(">", "&gt;")
        if probe_text not in html:
            fail("claim missing from the page: %r" % finding["claim"][:60])
    print("render: brief present in the standalone HTML")

    print("OK")


if __name__ == "__main__":
    main()
