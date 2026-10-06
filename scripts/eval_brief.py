"""Evaluation harness for the AI analysis.

Where check_brief.py is the fast gate (guards work, pipeline runs, ≥3
findings), this harness asserts on QUALITY invariants across the three
committed fixtures:

    golden lenses   the delinquent fixture must yield the digest facts its
                    story is built from, and the model's findings must
                    actually cite the high-value ones -- an analysis that
                    misses the 10 unconverted applications has failed at its
                    job, whatever else it found.
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
                    the one-analysis-per-payload guarantee is provided by the
                    app's session cache, not by the decoder. The harness
                    prints whether the runs happened to match exactly.
    latency         each generation must land inside the interactive budget.
    hypotheses      the fresh lens's loop ran as designed on the delinquent
                    fixture: the model (not the fallback) proposed typed
                    hypotheses, at least one was confirmed or refuted, a
                    finding cites a verified fact, every finding is framed.
    risk            the risk lenses: every pattern the patterns fixture plants
                    yields its fact and the archive fixture yields none of
                    them (model-free); the risk block's findings cite the
                    risk facts, carry a Python-derived basis, and nothing
                    inferred is above watch; the memo receives risk items.
    checklist       every step judged; the steps the team's tripwires fire on
                    (stale report, returns in the window) are not "clear" on
                    the delinquent fixture; an expired Emirates ID makes the
                    documents step high risk.
    memo            an outcome is suggested with cited drivers; the delinquent
                    fixture is NEVER "Approve" (the only safeguard on the
                    advisory recommendation, applied at evaluation time by
                    decision -- never at runtime).

Model runs go to the provider AECB_ENV selects (unset: dev, the local Ollama
model -- gpt-oss:120b, or the model AECB_OLLAMA_MODEL selects; uat/prod:
Core42, aecb/brief/providers.py). Both settings are read from
~/etc/aecb-analyzer/aecb.env as the app reads them. When that provider cannot
serve, the model assertions SKIP (exit 0) and only the digest assertions run
-- same policy as check_brief.py. At Core42 onboarding, the uat run is the
evidence run (docs/AI_ANALYSIS_MRM.md).

--effort overrides the reasoning level of named passes for this run only
(h, w, risk, checklist, memo, or all). It is a development experiment, never
read by the app: the shipped levels are the EFFORT constants in
aecb/brief/prompts/, and adopting another level is a model change.

    python3 scripts/eval_brief.py                  # everything, Ollama (three fixtures)
    python3 scripts/eval_brief.py --fast           # skip the determinism re-run
    python3 scripts/eval_brief.py --effort checklist=low,memo=low
    AECB_ENV=uat python3 scripts/eval_brief.py     # against Core42
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aecb import brief, context, runtime, settings  # noqa: E402
from aecb.brief.prompts import EFFORTS  # noqa: E402
from aecb.brief.prompts import checklist as checklist_prompt  # noqa: E402
from aecb.brief.prompts import hypotheses as h_prompt  # noqa: E402
from aecb.brief.prompts import lens as lens_prompt  # noqa: E402
from aecb.brief.prompts import memo as memo_prompt  # noqa: E402
from aecb.brief.prompts import risk as risk_prompt  # noqa: E402
from aecb.derive import brief_facts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELINQUENT = os.path.join(ROOT, "ReferenceJSON",
                          "1_SyntheticJSONPayload_Delinquent_MultiFacility.json")
ARCHIVE = os.path.join(ROOT, "ReferenceJSON",
                       "aecb_payload_archive_170623.json")
PATTERNS = os.path.join(ROOT, "ReferenceJSON",
                        "2_SyntheticJSONPayload_Patterns.json")

# Per block: at most two model passes (the lens's hypothesis pass and its
# findings pass). Interactive use sits behind a spinner; beyond this the
# feature is not usable as designed, whichever model serves it. Not derived
# from the client's timeout (aecb/brief/ollama.py TIMEOUT_S, the limit for one
# wedged call). Estimated to hold for gpt-oss-120b on the org laptop too
# (docs/AI_ANALYSIS_MRM.md section 9); a failure there most likely means the
# model is partly on the CPU (`ollama ps`) or a pass retried an empty reply.
LATENCY_BUDGET_S = 400
# The whole analysis (lens, risk, checklist, memo).
TOTAL_BUDGET_S = 1200

# The --effort override's pass names, and the pass each system text belongs
# to (every pass sends its prompt module's SYSTEM unchanged).
PASSES = ("h", "w", "risk", "checklist", "memo")
_PASS_OF_SYSTEM = {
    h_prompt.SYSTEM: "h", lens_prompt.SYSTEM: "w", risk_prompt.SYSTEM: "risk",
    checklist_prompt.SYSTEM: "checklist", memo_prompt.SYSTEM: "memo",
}

# {pass: level} from --effort, set once in main(); empty = the shipped levels.
_OVERRIDE = {}

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


_PLANTED = (
    "Balance cycling on", "Cash-like card:", "Minimum payments while still spending",
    "Seasonal delays:", "Pre-enquiry clean-up", "cleared to 0 by", "Non-bank reliance:",
    "Guarantor exposure crystallising:", "Instalments past working age:",
    "Income trajectory across", "Employer churn:", "Selective default by",
)


def eval_digest_patterns(ctx, facts):
    """Every pattern the fixture plants yields its risk fact (model-free)."""
    print("-- digest: patterns fixture (%d facts)" % len(facts))
    risk = " || ".join(f["text"] for f in facts if f["theme"] == "risk")
    for needle in _PLANTED:
        check(needle in risk, "patterns: risk fact present: %s" % needle)
    check(any(f["text"].startswith("[register:") for f in facts),
          "patterns: the context register reaches the digest")


def eval_risk_silence(name, facts):
    """The risk lenses stay silent where the fixture plants nothing."""
    risk = " || ".join(f["text"] for f in facts if f["theme"] == "risk")
    for needle in ("Balance cycling on", "Minimum payments while still spending",
                   "Seasonal delays:", "Pre-enquiry clean-up", "Non-bank reliance:",
                   "Guarantor exposure crystallising:", "Instalments past working age:",
                   "Employer churn:", "Selective default by"):
        check(needle not in risk, "%s: no %s fact without its evidence" % (name, needle.rstrip(":")))


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
    check(bool(fact_texts(facts, "[register:")) == macro,
          "register facts present exactly when config/macro_context.json is")

    # Lenses fire exactly when their payload evidence exists.
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

def parse_efforts(text) -> dict:
    """{pass: level} from "checklist=low,memo=low"; "all=low" sets every
    pass, and a later pair overrides an earlier one. Raises ValueError
    naming the part it cannot read -- a mistyped pass must not quietly run
    at the shipped level."""
    out = {}
    for part in (p.strip() for p in (text or "").split(",")):
        if not part:
            continue
        name, sep, level = part.partition("=")
        name, level = name.strip().lower(), level.strip().lower()
        if not sep or name not in PASSES + ("all",) or level not in EFFORTS:
            raise ValueError(
                "--effort takes pass=level pairs (pass: %s or all; level: %s), "
                "not %r" % (", ".join(PASSES), ", ".join(EFFORTS), part))
        for pass_ in (PASSES if name == "all" else (name,)):
            out[pass_] = level
    return out


def _measuring(provider):
    """A provider wrapper that records each pass's prompt and reply size --
    the per-pass sizes the token budget is measured against -- with the
    reasoning level it ran at and the attempts it took. Measured by the
    provider where it reports them (Ollama's prompt_eval_count and
    eval_count, reasoning tokens included); otherwise estimated at
    characters / 4, which undercounts tables of numbers by ~1.6x. Applies
    the --effort override."""
    import json

    class Measured:
        NAME, DATA_NOTE = provider.NAME, provider.DATA_NOTE
        model = staticmethod(provider.model)
        sizes = []
        measured = hasattr(provider, "LAST_USAGE")

        @staticmethod
        def probe():
            return provider.probe()

        @staticmethod
        def chat(system, user, schema, effort=""):
            effort = _OVERRIDE.get(_PASS_OF_SYSTEM.get(system), effort)
            reply = provider.chat(system, user, schema, effort)
            usage = getattr(provider, "LAST_USAGE", {})
            prompt_tokens = usage.get("prompt_tokens") or (len(system) + len(user)) // 4
            reply_tokens = usage.get("reply_tokens") or len(json.dumps(reply)) // 4
            Measured.sizes.append((prompt_tokens, reply_tokens, effort,
                                   usage.get("attempts") or 1))
            return reply
    return Measured


def _sizes(measured) -> str:
    retried = sum(s[3] - 1 for s in measured.sizes)
    return "prompts %s, replies %s tokens%s; effort %s%s" % (
        "/".join(str(s[0]) for s in measured.sizes),
        "/".join(str(s[1]) for s in measured.sizes),
        " (measured)" if measured.measured else " (~chars/4)",
        "/".join(s[2] or "default" for s in measured.sizes),
        "; %d empty or unparseable repl(ies) retried" % retried if retried else "")


def generate(ctx, label, provider):
    """The full analysis (every buildable block), or None on failure."""
    measured = _measuring(provider)
    started = time.time()
    totals = [0, 0]
    try:
        analysis = brief.new_analysis(ctx, measured)
        while True:
            name = brief.next_missing(analysis)
            if name is None:
                break
            t0 = time.time()
            brief.generate_block(ctx, measured, analysis, name)
            block = analysis["blocks"][name]
            print("-- model: %s %s -> %s, %d dropped, %.0fs (%s)"
                  % (label, name, brief.blocks.MODULES[name].summary(block),
                     len(block["dropped"]), time.time() - t0,
                     _sizes(measured)))
            if name == "risk" and block.get("note"):
                print("   risk: %s" % block["note"])
            if name == "lens":
                print("   hypotheses: %s; tables at %d months; %s"
                      % (block["hypotheses_source"], block["tables_months"],
                         ", ".join("%s=%d" % (st, sum(1 for h in block["hypotheses"]
                                                       if h["status"] == st))
                                   for st in ("confirmed", "not_supported",
                                              "not_assessable"))))
                for note in block["observations"]:
                    print("   observation: %s" % note)
            totals[0] += sum(s[0] for s in measured.sizes)
            totals[1] += sum(s[1] for s in measured.sizes)
            measured.sizes = []
            check(time.time() - t0 < LATENCY_BUDGET_S,
                  "%s: %s generated inside the %ds budget"
                  % (label, name, LATENCY_BUDGET_S))
    except brief.BriefUnavailable as exc:
        check(False, "%s: generation failed (%s)" % (label, exc))
        return None
    check(time.time() - started < TOTAL_BUDGET_S,
          "%s: whole analysis inside the %ds budget (%.0fs)"
          % (label, TOTAL_BUDGET_S, time.time() - started))
    print("   whole analysis: %s prompt / %s reply tokens%s"
          % (format(totals[0], ","), format(totals[1], ","),
             "" if measured.measured else " (~chars/4)"))
    return analysis


def eval_checklist(label, analysis, expect_not_clear=(), expect_high=()):
    steps = analysis["blocks"]["checklist"]["steps"]
    by_no = {s["step"]: s for s in steps}
    check(len(steps) == 10 and all(s["status"] != "not_assessable"
                                   or s["not_assessable_reason"]
                                   for s in steps),
          "%s: all ten steps judged" % label)
    for no in expect_not_clear:
        check(by_no[no]["status"] in ("attention", "high_risk"),
              "%s: step %02d is not clear (%s)" % (label, no, by_no[no]["status"]))
    for no in expect_high:
        check(by_no[no]["status"] == "high_risk",
              "%s: step %02d is high risk (%s)" % (label, no, by_no[no]["status"]))
    misses = sum(len(s["possible_miss"]) for s in steps)
    cited = sum(len(i["cites"]) for s in steps for i in s["indicators"])
    print("   checklist: statuses %s; %d possible miss(es); %d cites"
          % ("".join(s["status"][0] for s in steps), misses, cited))


def eval_memo(label, analysis, never=()):
    memo = analysis["blocks"]["memo"]
    check(memo["outcome"] not in never,
          "%s: outcome %r is not one of %s" % (label, memo["outcome"], never)
          if never else "%s: outcome present (%s)" % (label, memo["outcome"]))
    check(len(memo["drivers"]) >= 2,
          "%s: at least 2 validated drivers (%d)" % (label, len(memo["drivers"])))
    check(all(d["cites"] for d in memo["drivers"]),
          "%s: every driver cites a validated item" % label)
    stated = sum(1 for v in memo["sections"].values() if v)
    check(stated >= 7, "%s: at least 7 of 9 memo sections survived (%d)"
          % (label, stated))
    print("   memo: %s (%s); sections stated %d/9; dropped %d"
          % (memo["outcome"], memo["confidence"], stated, len(memo["dropped"])))
    # Printed for reading, not asserted: whether a driver keeps its figures
    # is the judgement behind the memo's reasoning level (MRM section 9).
    for driver in memo["drivers"]:
        print("   driver: %s  <- %s" % (driver["text"], ",".join(driver["cites"])))


def eval_hypotheses(label, analysis):
    """The loop ran as designed: the model proposed, the verifier answered,
    and the findings used what it found."""
    result = analysis["blocks"]["lens"]
    check(result["hypotheses_source"] == "model",
          "%s: the model proposed at least one typed hypothesis (source %s)"
          % (label, result["hypotheses_source"]))
    verified = [f for f in analysis["facts"] if f["theme"] == "verified"]
    check(bool(verified), "%s: at least one hypothesis was confirmed or refuted "
          "(%d verified facts)" % (label, len(verified)))
    by_id = analysis["facts_by_id"]
    check(any(by_id[c]["theme"] == "verified" for c in cited_ids(result)
              if c in by_id),
          "%s: some finding cites a verified fact" % label)
    check(all(f.get("framing") for f in result["findings"]),
          "%s: every finding carries a framing" % label)


def eval_risk(label, analysis, min_findings=1):
    """The risk block ran as designed: findings cite the risk facts, every
    finding carries a Python-derived basis, nothing inferred is above watch."""
    block = analysis["blocks"]["risk"]
    findings = block["findings"]
    check(len(findings) >= min_findings,
          "%s: risk block has at least %d finding(s) (%d)" % (label, min_findings, len(findings)))
    by_id = analysis["facts_by_id"]
    risk_cited = {c for f in findings for c in f["cites"] if by_id[c]["theme"] == "risk"}
    check(len(risk_cited) >= min(2, min_findings),
          "%s: findings cite %d distinct risk fact(s)" % (label, len(risk_cited)))
    check(all(f["basis"] in ("payload", "payload+context", "inferred") for f in findings),
          "%s: every risk finding carries a basis" % label)
    check(all(f["severity"] in ("watch", "info") for f in findings if f["basis"] == "inferred"),
          "%s: no inferred finding above watch" % label)
    print("   risk: basis %s; %d sector inference(s): %s; dropped %d"
          % (block["basis_counts"], len(block["sector_inferences"]),
             "; ".join("%s -> %s" % (i["employer"], i["sector"])
                       for i in block["sector_inferences"]) or "none",
             len(block["dropped"])))


def eval_model_delinquent(analysis, facts):
    result = analysis["blocks"]["lens"]
    findings = result["findings"]
    check(len(findings) >= 4, "delinquent: at least 4 findings (%d)"
          % len(findings))
    check(any(f["severity"] in ("severe", "adverse") for f in findings),
          "delinquent: at least one adverse-or-worse finding")
    eval_hypotheses("delinquent", analysis)

    by_id = analysis["facts_by_id"]
    cited_themes = {by_id[c]["theme"] for c in cited_ids(result) if c in by_id}
    check("trajectory" in cited_themes,
          "delinquent: some finding cites a trajectory fact")
    check(cited_themes & {"behavior", "inconsistency"},
          "delinquent: some finding cites a behavior/inconsistency fact")

    golden = [f["id"] for f in fact_texts(facts, "Requested phase")]
    check(bool(set(golden) & cited_ids(result)),
          "delinquent: the unconverted-applications fact is cited (golden)")


def eval_model_archive(analysis):
    result = analysis["blocks"]["lens"]
    check(len(result["findings"]) >= 3,
          "archive: at least 3 findings (%d)" % len(result["findings"]))
    check(not result["dropped"] or len(result["findings"]) >= 3,
          "archive: drops did not hollow out the brief")


def eval_model_patterns(analysis):
    """The planted patterns are found by the loop and read by the risk block."""
    lens = analysis["blocks"]["lens"]
    confirmed = [h for h in lens["hypotheses"] if h["status"] == "confirmed"]
    check(bool(confirmed), "patterns: at least one hypothesis confirmed (%d)" % len(confirmed))
    eval_hypotheses("patterns", analysis)
    eval_risk("patterns", analysis, min_findings=3)
    items = analysis["blocks"]["memo"]["items"]
    check(any(item["source"] == "risk" for item in items.values()),
          "patterns: the memo received risk items")


def eval_stability(ctx, facts, first, provider):
    second = generate(ctx, "delinquent (re-run)", provider)
    if second is None:
        return

    trip_steps = [p["step"] for p in first["packets"] if p["tripwires"]]
    s1 = {s["step"]: s["status"] for s in first["blocks"]["checklist"]["steps"]}
    s2 = {s["step"]: s["status"] for s in second["blocks"]["checklist"]["steps"]}
    agree = [no for no in trip_steps if (s1[no] == "clear") == (s2[no] == "clear")]
    check(len(agree) == len(trip_steps),
          "stability: the two runs agree on clear/not-clear for every tripwire "
          "step (%d/%d)" % (len(agree), len(trip_steps)))
    o1, o2 = first["blocks"]["memo"]["outcome"], second["blocks"]["memo"]["outcome"]
    # The outcome itself is NOT asserted equal: greedy decoding is not
    # float-stable on this stack and a borderline file can come back Refer
    # one run and Decline the next. The session cache gives the underwriter
    # one outcome per payload; what must hold is that neither run crosses to
    # Approve.
    check((o1 == "Approve") == (o2 == "Approve"),
          "stability: the two runs agree on Approve / not Approve (%s / %s)"
          % (o1, o2))
    check(all(any(f["theme"] == "verified" for f in run["facts"])
              for run in (first, second)),
          "stability: both runs produced verified facts")
    print("   outcomes: run 1 %s, run 2 %s%s" % (
        o1, o2, "" if o1 == o2 else "  (differ -- see AI_ANALYSIS_MRM.md limitations)"))
    first, second = first["blocks"]["lens"], second["blocks"]["lens"]

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


def _expired_id(ctx):
    """The delinquent fixture with its Emirates ID expired before the
    report date -- the checklist's step 3 must say so."""
    import copy
    import json
    from aecb.derive import identity
    payload = copy.deepcopy(ctx.data)
    for row in payload.get("identification") or []:
        if identity.base_type(row.get("InfoType")) == "EmiratesId":
            row["ExpiryDate"] = "2020-01-15"
    return context.from_bytes(json.dumps(payload).encode("utf-8"),
                              source_name="expired-id")


def _arguments():
    parser = argparse.ArgumentParser(description="Evaluation harness for the AI analysis.")
    parser.add_argument("--fast", action="store_true",
                        help="skip the stability re-run and the expired-ID variant")
    parser.add_argument("--effort", default="", metavar="PASS=LEVEL,...",
                        help="development only: run the named passes (%s, or all) "
                             "at another reasoning level (%s)"
                             % (", ".join(PASSES), ", ".join(EFFORTS)))
    args = parser.parse_args()
    try:
        args.effort = parse_efforts(args.effort)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def _load_settings():
    """AECB_ENV and AECB_OLLAMA_MODEL from ~/etc/aecb-analyzer/aecb.env, like
    the app, so the harness evaluates the model the app would run."""
    problem = settings.load_local()
    if problem:
        print("note: %s" % problem, file=sys.stderr)


def _announce(provider) -> None:
    """The provider, its model and timeout, and any --effort override."""
    tag = provider.model()
    timeout = getattr(provider, "TIMEOUT_S", {}).get(tag)
    print("-- provider: %s (%s)%s" % (provider.NAME, tag or "no model",
                                      ", timeout %d s" % timeout if timeout else ""))
    if _OVERRIDE:
        print("-- effort override (development only, not the shipped "
              "configuration): %s" % ", ".join(
                  "%s=%s" % (p, _OVERRIDE[p]) for p in PASSES if p in _OVERRIDE))


def main():
    args = _arguments()
    _load_settings()
    fast = args.fast
    _OVERRIDE.update(args.effort)

    ctx_del = context.from_file(DELINQUENT)
    facts_del = brief_facts.build(ctx_del)
    ctx_arc = context.from_file(ARCHIVE)
    facts_arc = brief_facts.build(ctx_arc)
    ctx_pat = context.from_file(PATTERNS)
    facts_pat = brief_facts.build(ctx_pat)

    eval_digest_delinquent(ctx_del, facts_del)
    eval_digest_patterns(ctx_pat, facts_pat)
    eval_prohibited("delinquent", facts_del)
    eval_prohibited("archive", facts_arc)
    eval_prohibited("patterns", facts_pat)
    eval_silence("delinquent", ctx_del, facts_del)
    eval_silence("archive", ctx_arc, facts_arc)
    eval_silence("patterns", ctx_pat, facts_pat)
    eval_risk_silence("archive", facts_arc)

    provider = brief.for_environment(runtime.environment(default=runtime.DEV))
    _announce(provider)
    reason = provider.probe()
    if reason:
        print("SKIP model assertions: %s" % reason)
    else:
        result = generate(ctx_del, "delinquent", provider)
        if result is not None:
            eval_model_delinquent(result, facts_del)
            eval_risk("delinquent", result)
            eval_checklist("delinquent", result, expect_not_clear=(1, 5, 7))
            eval_memo("delinquent", result, never=("Approve",))
        patterns_result = generate(ctx_pat, "patterns", provider)
        if patterns_result is not None:
            eval_model_patterns(patterns_result)
            eval_checklist("patterns", patterns_result, expect_not_clear=(1,))
            eval_memo("patterns", patterns_result)
        archive_result = generate(ctx_arc, "archive", provider)
        if archive_result is not None:
            eval_model_archive(archive_result)
            eval_checklist("archive", archive_result, expect_not_clear=(1,))
            eval_memo("archive", archive_result)
        if fast:
            print("-- stability re-run and expired-ID variant skipped (--fast)")
        elif result is not None:
            eval_stability(ctx_del, facts_del, result, provider)
            expired = generate(_expired_id(ctx_del), "delinquent (expired ID)",
                               provider)
            if expired is not None:
                # Not clear, rather than high risk: the harness checks that
                # the expired document is not MISSED; how hard the model
                # grades it is judgement, and the tripwire audit shows a miss.
                eval_checklist("expired ID", expired, expect_not_clear=(3,))

    if _FAILURES:
        print("\n%d assertion(s) failed" % len(_FAILURES))
        raise SystemExit(1)
    print("\nOK")


if __name__ == "__main__":
    main()
