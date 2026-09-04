"""Evaluation harness for the AI underwriting brief (phase 3).

Where check_brief.py is the fast gate (guards work, pipeline runs, ≥3
findings), this harness asserts on QUALITY invariants across both committed
fixtures:

    golden lenses   the delinquent fixture must yield the digest facts its
                    story is built from, and the model's findings must
                    actually cite the high-value ones -- a brief that misses
                    the 10 unconverted applications has failed at its job,
                    whatever else it found.
    silence         a lens must not fire where its source data is clean:
                    facts are asserted absent when the payload carries
                    nothing for them. Hallucinated INSIGHT usually begins as
                    an ungrounded fact, so silence is checked at the digest,
                    where it is deterministic.
    stability       two runs over the same payload must be substantively
                    interchangeable: both cite the golden facts, both carry
                    an adverse-or-worse lead, both clear the finding floor.
                    Bit-identical output is NOT asserted -- greedy decoding
                    on this serving stack is not float-stable across calls
                    (measured here: same insights, different phrasing), and
                    the one-brief-per-payload guarantee is provided by the
                    app's session cache, not by the decoder. The harness
                    prints whether the runs happened to match exactly.
    latency         each generation must land inside the interactive budget.

Model runs need Ollama + the brief's model on localhost; without them the
model assertions SKIP (exit 0) and only the digest assertions run -- same
policy as check_brief.py.

    python3 scripts/eval_brief.py           # everything
    python3 scripts/eval_brief.py --fast    # skip the determinism re-run
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aecb import brief, context  # noqa: E402
from aecb.derive import brief_facts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELINQUENT = os.path.join(ROOT, "ReferenceJSON",
                          "1_SyntheticJSONPayload_Delinquent_MultiFacility.json")
ARCHIVE = os.path.join(ROOT, "ReferenceJSON",
                       "aecb_payload_archive_170623.json")

# One generation = a findings pass plus a synthesis pass, so the budget is
# two client timeouts with load headroom. Interactive use sits behind a
# spinner; beyond this the feature is not usable as designed.
LATENCY_BUDGET_S = 400

_FAILURES = []


def check(ok, message):
    tag = "ok  " if ok else "FAIL"
    print("%s %s" % (tag, message))
    if not ok:
        _FAILURES.append(message)


def fact_texts(facts, needle):
    return [f for f in facts if needle.lower() in f["text"].lower()]


def cited_ids(result):
    out = set()
    for finding in result["findings"]:
        out.update(finding["cites"])
    return out


# --- digest assertions (deterministic, no model) -----------------------------

def eval_digest_delinquent(ctx, facts):
    print("-- digest: delinquent fixture (%d facts)" % len(facts))
    themes = {f["theme"] for f in facts}
    check(themes >= {"trajectory", "structure", "inconsistency", "behavior"},
          "all payload lenses represented (got %s)" % ", ".join(sorted(themes)))
    check(bool(fact_texts(facts, "Overdue onset by contract")),
          "overdue-onset synchrony fact present")
    check(bool(fact_texts(facts, "Requested phase")),
          "unconverted-applications fact present")
    check(bool(fact_texts(facts, "open in parallel")),
          "parallel-employments fact present")
    check(bool(fact_texts(facts, "returned instrument")),
          "returned-instruments fact present")


def _positive(value):
    try:
        return float(str(value).replace(",", "")) > 0
    except (TypeError, ValueError):
        return False


def eval_prohibited(name, facts):
    """The compliance guardrail: prohibited fields never reach a fact."""
    from aecb.derive.brief_facts import PROHIBITED_FIELDS
    dirty = [f["id"] for f in facts
             if any(banned.lower() in
                    (f["text"] + " " + " ".join(f["fields"])).lower()
                    for banned in PROHIBITED_FIELDS)]
    check(not dirty, "%s: no prohibited field reaches the digest%s"
          % (name, "" if not dirty else " (dirty: %s)" % ", ".join(dirty)))


def eval_silence(name, ctx, facts):
    """A lens may not fire without payload evidence behind it."""
    print("-- digest silence: %s" % name)
    totals = ctx.totals
    has_guarantee = (_positive(totals.get("TotalBalanceGuaranteed"))
                     or _positive(totals.get("TotalOverdueGuaranteed")))
    check(bool(fact_texts(facts, "guarantor")) == has_guarantee,
          "guarantee fact present only with guaranteed balances")
    check(bool(fact_texts(facts, "returned instrument"))
          == bool(ctx.rows("paymentOrder")),
          "returned-instruments fact present only with paymentOrder rows")
    check(bool(fact_texts(facts, "minimum payment flagged")) is False
          or any(r.get("MinimumPaymentFlag") is not None
                 for r in ctx.rows("contractsHistory")),
          "minimum-payment streak fact only when the flag was delivered")
    macro = os.path.exists(os.path.join(ROOT, "config", "macro_context.json"))
    check(bool(fact_texts(facts, "curated context")) == macro,
          "macro facts present exactly when config/macro_context.json is")

    # p4.0 lenses: fire exactly when their payload evidence exists.
    def active(contract):
        return str(contract.get("ActiveFlag", "")).strip().lower() == "active"

    kinds = {ctx.provider(c.get("ProviderNo"))["kind"]
             for c in ctx.rows("contracts") if active(c)}
    check(bool(fact_texts(facts, "provider kind")) == (len(kinds) >= 2),
          "waterfall facts present only with 2+ provider kinds")
    has_method = any(str(c.get("MethodOfPayment") or "").strip().lower()
                     in ("salary transfer", "direct debit")
                     for c in ctx.rows("contracts") if active(c))
    check(bool(fact_texts(facts, "Repayment method")) == has_method,
          "repayment-method fact present only when MethodOfPayment delivered")
    has_delay = any(_positive(r.get("DaysPaymentDelay"))
                    for r in ctx.rows("contractsHistory"))
    check(bool(fact_texts(facts, "Episodes:")) == has_delay,
          "cure-velocity episodes present only with delinquent months")
    check(bool(fact_texts(facts, "Obligation components")),
          "obligation-components fact present (both fixtures deliver them)")


# --- model assertions --------------------------------------------------------

def generate(ctx, label):
    started = time.time()
    try:
        result = brief.generate_brief(ctx)
    except brief.BriefUnavailable as exc:
        check(False, "%s: generation failed (%s)" % (label, exc))
        return None
    elapsed = time.time() - started
    print("-- model: %s -> %d finding(s), %d background, %d unknown(s), "
          "%d dropped, synthesis %s, %.0fs"
          % (label, len(result["findings"]), len(result["background"]),
             len(result["unknowns"]), len(result["dropped"]),
             "yes" if result["synthesis"] else "no", elapsed))
    check(elapsed < LATENCY_BUDGET_S,
          "%s generated inside the %ds budget (%.0fs)"
          % (label, LATENCY_BUDGET_S, elapsed))
    return result


def eval_model_delinquent(result, facts):
    findings = result["findings"]
    check(len(findings) >= 4, "delinquent: at least 4 findings (%d)"
          % len(findings))
    check(any(f["severity"] in ("severe", "adverse") for f in findings),
          "delinquent: at least one adverse-or-worse finding")

    by_id = {f["id"]: f for f in facts}
    cited_themes = {by_id[c]["theme"] for c in cited_ids(result) if c in by_id}
    check("trajectory" in cited_themes,
          "delinquent: some finding cites a trajectory fact")
    check(cited_themes & {"behavior", "inconsistency"},
          "delinquent: some finding cites a behavior/inconsistency fact")

    golden = [f["id"] for f in fact_texts(facts, "Requested phase")]
    check(bool(set(golden) & cited_ids(result)),
          "delinquent: the unconverted-applications fact is cited (golden)")


def eval_model_archive(result):
    check(len(result["findings"]) >= 3,
          "archive: at least 3 findings (%d)" % len(result["findings"]))
    check(not result["dropped"] or len(result["findings"]) >= 3,
          "archive: drops did not hollow out the brief")


def eval_stability(ctx, facts, first):
    second = generate(ctx, "delinquent (re-run)")
    if second is None:
        return

    golden = {f["id"] for f in fact_texts(facts, "Requested phase")}
    for label, result in (("run 1", first), ("run 2", second)):
        check(len(result["findings"]) >= 4,
              "stability: %s clears the finding floor (%d)"
              % (label, len(result["findings"])))
        check(any(f["severity"] in ("severe", "adverse")
                  for f in result["findings"]),
              "stability: %s carries an adverse-or-worse finding" % label)
        check(bool(golden & cited_ids(result)),
              "stability: %s cites the golden unconverted-applications fact"
              % label)

    shared = cited_ids(first) & cited_ids(second)
    union = cited_ids(first) | cited_ids(second)
    exact = [f["claim"] for f in first["findings"]] == \
        [f["claim"] for f in second["findings"]]
    print("   cited-fact overlap %d/%d; exact claim match: %s"
          % (len(shared), len(union), "yes" if exact else "no (expected -- "
             "greedy decoding is not float-stable on this stack)"))


def main():
    fast = "--fast" in sys.argv[1:]

    ctx_del = context.from_file(DELINQUENT)
    facts_del = brief_facts.build(ctx_del)
    ctx_arc = context.from_file(ARCHIVE)
    facts_arc = brief_facts.build(ctx_arc)

    eval_digest_delinquent(ctx_del, facts_del)
    eval_prohibited("delinquent", facts_del)
    eval_prohibited("archive", facts_arc)
    eval_silence("delinquent", ctx_del, facts_del)
    eval_silence("archive", ctx_arc, facts_arc)

    reason = brief.probe()
    if reason:
        print("SKIP model assertions: %s" % reason)
    else:
        result = generate(ctx_del, "delinquent")
        if result is not None:
            eval_model_delinquent(result, facts_del)
        archive_result = generate(ctx_arc, "archive")
        if archive_result is not None:
            eval_model_archive(archive_result)
        if fast:
            print("-- stability re-run skipped (--fast)")
        elif result is not None:
            eval_stability(ctx_del, facts_del, result)

    if _FAILURES:
        print("\n%d assertion(s) failed" % len(_FAILURES))
        raise SystemExit(1)
    print("\nOK")


if __name__ == "__main__":
    main()
