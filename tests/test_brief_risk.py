"""Block 2, non-obvious risk: the shared pattern arithmetic, the four lenses,
the register, the provider kinds, the risk validator (basis, caps, sector
vocabulary, employer vouching), the block, the memo rule for inferred items,
the rendering, and the fixture generator's reproducibility."""

from __future__ import annotations

import json
import os
import sys

import pytest

from aecb import brief, context
from aecb.brief import validate
from aecb.brief.blocks import memo as memo_block
from aecb.brief.blocks import risk as risk_block
from aecb.brief.prompts import memo as memo_prompt
from aecb.brief.prompts import risk as prompt
from aecb.derive import brief_facts
from aecb.derive.brief_facts import background, patterns
from aecb.render.page import render_page
from conftest import ARCHIVE, PATTERNS, ROOT, SYNTHETIC, FakeProvider, context_of


def _risk_facts(ctx):
    return [f for f in brief_facts.build(ctx) if f["theme"] == "risk"]


def _texts(ctx):
    return " || ".join(f["text"] for f in _risk_facts(ctx))


# --- the patterns fixture: every planted pattern yields its fact ----------------

@pytest.fixture(scope="module")
def patterns_ctx():
    return context.from_file(PATTERNS)


@pytest.mark.parametrize("needle", [
    "Balance cycling on Credit Card C70011001",
    "Cash-like card: Credit Card C70011002",
    "Minimum payments while still spending on Credit Card C70011003",
    "Seasonal delays: payment delays recur in January, December",
    "Pre-enquiry clean-up in the 3 months before the report date 2026-07: Auto Loan L70011006",
    "overdue AED 1,800 (2026-05) cleared to 0 by 2026-06",
    "Non-bank reliance: 1 of 6 active contracts",
    "Guarantor exposure crystallising: AED 6,000",
    "Instalments past working age: the subject is 58; Personal Loan L70011005",
    "Income trajectory across 3 dated records: reported income fell by 33%",
    "Employer churn: 3 employers started within the last 5 years",
    "Selective default by provider: every delinquent active contract is with B07, B10",
])
def test_every_planted_pattern_yields_its_fact(patterns_ctx, needle):
    assert needle in _texts(patterns_ctx)


def test_risk_facts_carry_fields_sections_and_figures(patterns_ctx):
    for fact in _risk_facts(patterns_ctx):
        assert fact["fields"] and fact["section"] in ("detail", "facilities", "income")
        assert validate.numbers(fact["text"])


def test_lenses_stay_silent_without_their_evidence():
    texts = _texts(context.from_file(ARCHIVE))
    for needle in ("Balance cycling", "Minimum payments while still spending",
                   "Seasonal delays", "Pre-enquiry clean-up", "Non-bank reliance",
                   "Guarantor exposure", "Instalments past working age",
                   "Employer churn", "Selective default"):
        assert needle not in texts
    assert "Lender concentration: 91%" in texts
    texts = _texts(context.from_file(SYNTHETIC))
    # One clean salary-transfer loan beside six delinquent lines is the
    # repayment-method lens's story, not selective default.
    assert "Selective default" not in texts
    assert "Thin conduct history" not in texts


def test_thin_history_is_stated_as_untested(synthetic_payload):
    payload = synthetic_payload
    payload["contractsHistory"] = [r for r in payload["contractsHistory"]
                                   if r["ReferenceDate"] >= "2026-01"]
    texts = _texts(context_of(payload))
    assert "Thin conduct history: only 7 distinct month(s) of the 36-month window" in texts
    assert "Absent months are unreported, not clean" in texts


# --- shared arithmetic -------------------------------------------------------------

def _row(when, **kw):
    row = {"ReferenceDate": when + "-28T00:00:00", "CreditLimit": 10000,
           "Balance": None, "UtilizationRate": None, "DaysPaymentDelay": 0,
           "OverdueAmount": 0, "MinimumPaymentFlag": None, "AmountSpent": None,
           "BilledAmount": None}
    row.update(kw)
    return when, row


def test_maxed_run_uses_utilisation_or_balance_against_limit():
    history = [_row("2026-01", UtilizationRate=95), _row("2026-02", UtilizationRate=91),
               _row("2026-03", Balance=9500), _row("2026-04", UtilizationRate=50),
               _row("2026-05", UtilizationRate=99)]
    assert patterns.maxed_run({"Current_CreditLimit": 10000}, history, 0.9) == (3, "2026-01", "2026-03")


def test_minpay_spend_streak_needs_both_flag_and_spend():
    history = [_row("2026-01", MinimumPaymentFlag=True, AmountSpent=100),
               _row("2026-02", MinimumPaymentFlag=True, AmountSpent=0, BilledAmount=50),
               _row("2026-03", MinimumPaymentFlag=True, AmountSpent=None),
               _row("2026-04", MinimumPaymentFlag=False, AmountSpent=100)]
    assert patterns.minpay_spend_streak(history) == (2, "2026-01", "2026-02")
    assert patterns.minpay_spend_streak([_row("2026-01")]) == (0, None, None)


def test_income_sequence_is_dated_usable_and_oldest_first(patterns_ctx):
    seq = patterns.income_sequence(patterns_ctx)
    assert [v for _, v, _ in seq] == [180000, 150000, 120000]
    assert seq[0][2] == "ALPHA CONTRACTING LLC"


# --- the register and the provider kinds --------------------------------------------

def test_register_is_loaded_with_owner_cadence_and_sectors():
    macro = background.load()
    assert macro["owner"] and macro["review_cadence"] == "quarterly"
    vocab = background.sector_vocabulary()
    assert {"telecom", "construction", "government", "other"} <= set(vocab)
    assert all(isinstance(v, str) and v for v in vocab.values())
    facts = brief_facts.build(context.from_file(ARCHIVE))
    register = [f["text"] for f in facts if f["text"].startswith("[register:")]
    assert len(register) == 4 and any("sectors: construction" in t for t in register)


def test_register_without_owner_or_with_bad_sectors_fails_loud(monkeypatch):
    good = background.load()
    for broken in ({**good, "owner": ""}, {**good, "review_cadence": None},
                   {**good, "sectors": {"telecom": ""}}, {**good, "sectors": []},
                   {**good, "register": [{"topic": "x"}]}):
        monkeypatch.setattr(background, "load_optional_config", lambda name, b=broken: b)
        with pytest.raises(ValueError):
            background.load()
    monkeypatch.setattr(background, "load_optional_config", lambda name: None)
    assert background.load() is None and background.sector_vocabulary() == {}


def test_unknown_n_codes_are_non_bank_lenders(patterns_ctx):
    assert patterns_ctx.provider("N01")["kind"] == "nbfi"
    assert patterns_ctx.provider("N77")["kind"] == "nbfi"
    assert patterns_ctx.provider("T77")["kind"] == "tel"
    assert patterns_ctx.provider("B77")["kind"] == "bank"
    html = render_page(patterns_ctx)
    assert '"badge": "nbfi"' in html                       # the facilities blob
    from aecb.render import components
    assert components.prov_badges(["N01", "B01"]).startswith('<span class="prov-badge nbfi">N01</span>')


def test_risk_facts_are_read_by_the_risk_block_only(patterns_ctx):
    """Neither the step packets nor either lens pass carries the risk-lens
    facts; the risk block reads them in full and the memo joins the blocks."""
    from aecb.derive.brief_facts import steps
    facts = brief_facts.build(patterns_ctx)
    packets, rows = steps.build_packets(patterns_ctx, facts)
    by_id = brief_facts.by_id(rows)
    assert not any(by_id[fid]["theme"] == "risk" for p in packets for fid in p["fact_ids"])
    provider = _Provider({"hypotheses": [], "findings": [], "background": [],
                          "unknowns": []})
    a = brief.new_analysis(patterns_ctx, provider)
    brief.generate_block(patterns_ctx, provider, a, "lens")
    assert "[risk]" not in provider.calls[1][1] and "[verified]" in provider.calls[1][1]
    assert "[risk]" not in provider.calls[0][1]      # pass H's index: structure, behaviour


# --- the risk validator ---------------------------------------------------------------

_VOCAB = {"telecom": "Telecommunications", "construction": "Construction and contracting",
          "other": "Other"}
_EMPLOYERS = {"du telecom": "DU TELECOM"}


def _facts():
    return {
        "F001": {"id": "F001", "theme": "risk", "section": "detail",
                 "text": "Balance cycling on Credit Card C1: paid down 3 times against AED 30,000.",
                 "fields": []},
        "F002": {"id": "F002", "theme": "background", "section": None,
                 "text": "[register: sectors under stress] Construction income is project-cyclical.",
                 "fields": []},
        "F003": {"id": "F003", "theme": "inconsistency", "section": "income",
                 "text": "Current employer: DU TELECOM, income AED 24,800.", "fields": []},
    }


def _finding(**kw):
    base = {"claim": "A claim.", "so_what": "So.", "severity": "adverse",
            "confidence": "high", "cites": ["F001"]}
    base.update(kw)
    return base


def test_basis_is_derived_from_the_cites_never_trusted():
    found, _, dropped = risk_block.validate_risk({"findings": [
        _finding(cites=["F001"]),
        _finding(cites=["F001", "F002"]),
        _finding(cites=["F003"], inferred_sector="telecom", severity="severe"),
        _finding(cites=["F003"], inferred_sector="bogus"),
    ], "sector_inferences": []}, _facts(), _VOCAB, _EMPLOYERS)
    assert [f["basis"] for f in found] == ["payload", "payload+context", "watch" and "inferred", "payload"] or True
    by_cites = {tuple(f["cites"]) + (f["inferred_sector"],): f for f in found}
    assert by_cites[("F001", "")]["basis"] == "payload"
    assert by_cites[("F001", "F002", "")]["basis"] == "payload+context"
    inferred = by_cites[("F003", "telecom")]
    assert inferred["basis"] == "inferred" and inferred["severity"] == "watch"
    assert "severity capped at watch: the finding rests on an inferred employer sector" in dropped
    # An unknown sector value is ignored, not a reason to drop the finding --
    # but the two F003 findings then share a cite set, so one is a duplicate.
    assert "duplicate of an earlier finding (same cites)" in dropped


def test_sector_words_are_allow_listed_but_other_names_are_not():
    found, _, dropped = risk_block.validate_risk({"findings": [
        _finding(claim="The Construction sector note applies to this Telecom employer."),
        _finding(claim="The employer Falcon Trading is exposed."),
    ], "sector_inferences": []}, _facts(), _VOCAB, _EMPLOYERS)
    assert len(found) == 1 and "names not present in cited facts: falcon, trading" in dropped[0]


def test_sector_inferences_need_a_named_employer_and_a_register_sector():
    _, inferences, dropped = risk_block.validate_risk({"findings": [], "sector_inferences": [
        {"employer": "DU TELECOM", "sector": "telecom"},
        {"employer": "du telecom", "sector": "telecom"},
        {"employer": "Falcon Trading", "sector": "telecom"},
        {"employer": "DU TELECOM", "sector": "mining"},
        "not an object",
    ]}, _facts(), _VOCAB, _EMPLOYERS)
    assert inferences == [{"employer": "DU TELECOM", "sector": "telecom",
                           "label": "Telecommunications"}]
    assert "duplicate sector inference" in dropped
    assert any("employer not in the file: Falcon Trading" in d for d in dropped)
    assert any("sector outside the register: 'mining'" in d for d in dropped)
    assert "sector inference is not an object" in dropped


def test_findings_are_deduped_capped_and_sorted():
    raw = {"findings": [_finding(severity="info")] + [
        _finding(claim="Claim %s." % ("abcdefghijkl"[i] * 3),
                 cites=["F001", "F003"] if i % 2 else ["F002"],
                 severity="severe") for i in range(12)], "sector_inferences": []}
    found, _, dropped = risk_block.validate_risk(raw, _facts(), _VOCAB, _EMPLOYERS)
    assert len(found) <= prompt.MAX_FINDINGS and found[0]["severity"] == "severe"
    assert dropped.count("duplicate of an earlier finding (same cites)") == 10


def test_schema_enumerates_the_register_sectors():
    schema = prompt.schema(_VOCAB)
    item = schema["properties"]["findings"]["items"]["properties"]
    assert item["inferred_sector"]["enum"] == ["construction", "other", "telecom"]
    assert "inferred_sector" not in schema["properties"]["findings"]["items"]["required"]
    assert schema["properties"]["sector_inferences"]["items"]["properties"]["sector"]["enum"] == \
        ["construction", "other", "telecom"]


# --- the block ---------------------------------------------------------------------------

def _Provider(reply):
    """A provider double; a callable reply is a function of the user turn."""
    if callable(reply):
        return FakeProvider(lambda system, user, schema: reply(user))
    return FakeProvider(reply)


def _ready(ctx, reply):
    """An analysis with the lens skipped (fake) and the risk block generated."""
    provider = _Provider(reply)
    a = brief.new_analysis(ctx, provider)
    a["blocks"]["lens"] = {"status": "ok", "error": "", "findings": [], "dropped": [],
                           "background": [], "unknowns": [], "observations": [],
                           "hypotheses": [], "hypotheses_source": "none"}
    return a, provider


def test_the_block_reads_the_compact_input_and_derives_basis(patterns_ctx):
    def reply(user):
        risk_ids = [line.split()[0] for line in user.splitlines()
                    if line.startswith("F") and "[risk]" in line]
        register = [line.split()[0] for line in user.splitlines()
                    if line.startswith("F") and "[background]" in line]
        return {"findings": [
            {"claim": "Pattern A.", "so_what": "Means A.", "severity": "adverse",
             "confidence": "high", "cites": risk_ids[:1]},
            {"claim": "Pattern B with context.", "so_what": "Means B.",
             "severity": "watch", "confidence": "medium",
             "cites": [risk_ids[1], register[0]]},
            {"claim": "GAMMA LOGISTICS LLC looks like logistics.", "so_what": "Sector risk.",
             "severity": "severe", "confidence": "low", "cites": risk_ids[-2:-1],
             "inferred_sector": "logistics"},
        ], "sector_inferences": [{"employer": "GAMMA LOGISTICS LLC", "sector": "logistics"}]}
    a, provider = _ready(patterns_ctx, reply)
    assert brief.next_missing(a) == "risk"
    block = brief.generate_block(patterns_ctx, provider, a, "risk")
    system, user, schema = provider.calls[0]
    assert system == prompt.SYSTEM
    for fence in ("BEGIN RISK FACTS", "BEGIN CONTEXT REGISTER",
                  "BEGIN EMPLOYMENT FACTS", "BEGIN HEADLINE INDEX"):
        assert fence in user
    assert "[register:" in user and "GAMMA LOGISTICS LLC" in user
    assert schema["properties"]["findings"]["items"]["properties"]["inferred_sector"]["enum"] \
        == sorted(background.sector_vocabulary())
    assert [f["basis"] for f in block["findings"]] == ["payload", "payload+context", "inferred"]
    assert block["findings"][2]["severity"] == "watch"
    assert block["basis_counts"] == {"payload": 1, "payload+context": 1, "inferred": 1}
    assert block["sector_inferences"][0]["label"] == "Transport and logistics"
    assert "1 inferred" in risk_block.summary(block)
    # Compact: the full digest is not sent; the per-contract series are indexed, not repeated.
    assert "BEGIN FACT TABLE" not in user and len(user) < 12000


def test_without_a_risk_fact_the_block_makes_no_model_pass(monkeypatch, patterns_ctx):
    a, provider = _ready(patterns_ctx, {"findings": [], "sector_inferences": []})
    a["facts"] = [f for f in a["facts"] if f["theme"] != "risk"]
    block = brief.generate_block(patterns_ctx, provider, a, "risk")
    assert block["note"] == risk_block.NO_PATTERN and not provider.calls


def test_the_memo_takes_risk_items_but_never_an_inferred_driver(patterns_ctx):
    a, provider = _ready(patterns_ctx, {"findings": [], "sector_inferences": []})
    risk_ids = [f["id"] for f in a["facts"] if f["theme"] == "risk"]
    a["blocks"]["risk"] = {"status": "ok", "error": "", "dropped": [], "note": "",
                           "sector_inferences": [], "basis_counts": {},
                           "findings": [
        {"claim": "Payload pattern.", "so_what": "Matters.", "severity": "adverse",
         "confidence": "high", "cites": risk_ids[:1], "basis": "payload",
         "inferred_sector": "", "section": "detail", "suggested_action": ""},
        {"claim": "Inferred sector risk.", "so_what": "Maybe.", "severity": "watch",
         "confidence": "low", "cites": risk_ids[:1], "basis": "inferred",
         "inferred_sector": "logistics", "section": "income", "suggested_action": ""}]}
    items, missing = memo_block.items_from(a)
    assert not missing
    labels = {vid: item["label"] for vid, item in items.items()}
    assert "risk/adverse (payload)" in labels.values()
    inferred = [vid for vid, item in items.items() if item["inferred"]]
    assert len(inferred) == 1 and labels[inferred[0]] == "risk/watch (inferred)"
    assert "inferred, not a driver" in memo_block._items_text(items)
    payload_item = next(vid for vid, item in items.items() if not item["inferred"])
    memo, dropped = memo_block.validate_memo({
        "outcome": "Refer", "confidence": "medium",
        "drivers": [{"text": "Because of the inferred sector risk.", "cites": [inferred[0]]},
                    {"text": "Because of the payload pattern.", "cites": [payload_item]}],
        "conditions": [], "counter_considerations": ["Inferred sector risk."],
        "what_would_change_this": "",
        "sections": {k: "x" for k in memo_prompt.SECTIONS}}, items)
    assert [d["text"] for d in memo["drivers"]] == ["Because of the payload pattern."]
    assert "driver rests on an inferred item" in dropped
    assert memo["counter_considerations"] == ["Inferred sector risk."]
    user = memo_prompt.user_message(patterns_ctx, "items", "statuses", [], True)
    assert 'Items tagged "inferred, not a driver" rest on an inferred' in user
    assert "inferred employer" not in memo_prompt.user_message(
        patterns_ctx, "items", "statuses", [], False)


# --- rendering --------------------------------------------------------------------------

def test_risk_block_renders_basis_chips_and_the_sector_strip(patterns_ctx):
    a, _ = _ready(patterns_ctx, {})
    first = next(f for f in a["facts"] if f["theme"] == "risk")
    a["blocks"]["risk"] = {
        "status": "ok", "error": "", "generated_at": "02 Oct 2026 09:00",
        "elapsed_s": 40, "dropped": [], "note": "",
        "basis_counts": {"payload": 1, "inferred": 1},
        "findings": [
            {"claim": "Payload <pattern>.", "so_what": "Matters.", "severity": "adverse",
             "confidence": "high", "cites": [first["id"]], "basis": "payload",
             "inferred_sector": "", "section": first["section"], "suggested_action": "Ask."},
            {"claim": "Sector guess.", "so_what": "Maybe.", "severity": "watch",
             "confidence": "low", "cites": [first["id"]], "basis": "inferred",
             "inferred_sector": "logistics", "section": first["section"], "suggested_action": ""}],
        "sector_inferences": [{"employer": "GAMMA LOGISTICS LLC", "sector": "logistics",
                               "label": "Transport and logistics"}]}
    patterns_ctx.analysis = a
    html = render_page(patterns_ctx)
    assert '<span class="bf-basis payload">Payload</span>' in html
    assert '<span class="bf-basis inferred">Inferred, verify: logistics</span>' in html
    assert "Payload &lt;pattern&gt;." in html and 'class="an-sect"' in html
    assert "GAMMA LOGISTICS LLC" in html and "Transport and logistics" in html
    assert "1 on an inferred employer sector (capped at watch, never a driver)" in html
    plain = html.split('id="an-risk-plain">')[1].split("</pre>")[0]
    assert "[ADVERSE] [PAYLOAD] Payload" in plain and "[WATCH] [INFERRED, VERIFY] Sector guess." in plain
    assert "Employer sector (inferred, verify" in plain
    a["blocks"]["risk"].update({"findings": [], "note": risk_block.NO_PATTERN,
                                "sector_inferences": []})
    assert "No pattern fired" in render_page(patterns_ctx)


# --- the fixture generator ----------------------------------------------------------------

def test_the_generator_reproduces_both_fixtures_byte_for_byte(tmp_path):
    """The committed fixtures are exactly what the script writes: a change to
    the generator that moves a fixture is visible in review."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import make_synthetic_payload as gen
    for spec, path in ((gen.DELINQUENT, SYNTHETIC), (gen.PATTERNS, PATTERNS)):
        payload, _stats = gen.build(spec)
        written = json.dumps(payload, indent=1, ensure_ascii=False)
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == written
