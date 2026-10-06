"""The fresh lens's hypothesis -> verification loop: the raw tables, the
grammar, every verifier, the fallback, the observation guard and the block's
orchestration -- all deterministic, no model."""

from __future__ import annotations

import pytest

from aecb import brief, context
from aecb.brief import validate
from aecb.brief.hypotheses import candidates, grammar, verify
from aecb.brief.prompts import hypotheses as h_prompt
from aecb.derive import brief_facts
from aecb.derive.brief_facts import tables
from conftest import SYNTHETIC, FakeProvider, context_of, fixture_payload

# --- payload builders --------------------------------------------------------

_CARD = "C41880273"      # the synthetic fixture's first card (limit 45,000)
_LOAN = "L52913744"      # its first instalment loan


def _month(months_ago, anchor=(2026, 7)):
    year, month = anchor[0], anchor[1] - months_ago
    while month <= 0:
        month += 12
        year -= 1
    return "%04d-%02d" % (year, month)


def _row(contract, months_ago, balance=None, limit=None, util=None, dpd=0,
         overdue=0, category="C"):
    return {"CBContractId": contract, "ContractCategory": category,
            "ReferenceDate": _month(months_ago) + "-28T00:00:00",
            "CreditLimit": limit, "Balance": balance, "UtilizationRate": util,
            "DaysPaymentDelay": dpd, "OverdueAmount": overdue,
            "MinimumPaymentFlag": None, "CardUsedFlag": None,
            "AmountSpent": None, "BilledAmount": None, "PaymentBehaviour": None,
            "ContractStatus": "Active Payments"}


def _payload(history, contracts=None, applications=None, employment=None):
    """The synthetic fixture with its contracts narrowed and the monthly
    history (and optionally applications / employment) replaced."""
    payload = fixture_payload(SYNTHETIC)
    keep = contracts or (_CARD, _LOAN)
    payload["contracts"] = [c for c in payload["contracts"]
                            if c["CBContractId"] in keep]
    payload["contractsHistory"] = history
    if applications is not None:
        payload["applications"] = applications
    if employment is not None:
        payload["employment"] = employment
    return payload


def _ctx(history, **kwargs):
    return context_of(_payload(history, **kwargs))


def _aliases(ctx):
    return tables.build(ctx)["aliases"]


def _one(ctx, type_, **params):
    results = verify.run(ctx, [{"type": type_, "params": params}], _aliases(ctx))
    assert len(results) == 1
    return results[0]


# --- tables --------------------------------------------------------------------

def test_tables_alias_contracts_in_payload_order_with_raw_integers():
    ctx = context.from_file(SYNTHETIC)
    built = tables.build(ctx)
    ids = [c["CBContractId"] for c in ctx.rows("contracts")]
    assert list(built["aliases"]) == ["K%d" % (i + 1) for i in range(len(ids))]
    assert [c["CBContractId"] for c in built["aliases"].values()] == ids
    assert built["months"] == 36
    text = built["text"]
    assert text.startswith("CONTRACTS\n")
    assert "K1 | Credit Card C41880273 | B01 | card | 2018-03 | active" in text
    assert "45000 | 52340 | 12480 | 214 | Default" in text  # no separators
    assert "45,000" not in text and "util" not in text
    for title in ("HISTORY (last 36 months", "APPLICATIONS", "EMPLOYMENT",
                  "RETURNS"):
        assert title in text


def test_tables_trim_the_history_to_the_budget():
    ctx = context.from_file(SYNTHETIC)
    full = tables.build(ctx)
    trimmed = tables.build(ctx, budget_chars=len(full["text"]) - 1)
    assert trimmed["months"] == 24 and len(trimmed["text"]) < len(full["text"])
    assert tables.build(ctx, budget_chars=10)["months"] == 12


def test_tables_carry_no_identity_and_no_prohibited_field():
    ctx = context.from_file(SYNTHETIC)
    text = tables.build(ctx)["text"].lower()
    customer = ctx.customer
    for banned in brief_facts.PROHIBITED_FIELDS:
        assert banned.lower() not in text
        value = str(customer.get(banned) or "").lower()
        assert not value or len(value) < 2 or value not in text
    assert ctx.subject_id.lower() not in text
    assert str(customer.get("FirstName", "")).lower() not in text
    assert "dob" not in text and "1987" not in text


def _lines(text, alias):
    """The history lines of one alias."""
    block = text.split("\n%s\n" % alias, 1)[1]
    return block.split("\n\n")[0].split("\nK")[0].splitlines()


def test_history_lines_carry_only_what_changes_or_is_not_clean():
    history = [_row(_CARD, 6, 1000, 5000), _row(_CARD, 5, 1000, 5000),
               _row(_CARD, 4, 1000, 5000), _row(_CARD, 3, 1000, 5000),
               _row(_CARD, 2, 1200, 6000, dpd=15, overdue=300),
               _row(_CARD, 1, 1200, 6000, dpd=None, overdue=0),
               _row(_LOAN, 2, 5000, category="I"),
               _row(_LOAN, 1, 4800, dpd=30, overdue=200, category="I")]
    text = tables.build(_ctx(history))["text"]
    # The limit shows where it first appears or changes; three identical
    # consecutive months collapse; a delay shows, and an undelivered delay
    # is '-', never a clean month.
    assert _lines(text, "K1") == ["2026-01 1000 lim 5000",
                                  "2026-02..2026-04 1000 x3",
                                  "2026-05 1200 lim 6000 dpd 15 od 300",
                                  "2026-06 1200 dpd - od 0"]
    # A loan has no limit cell.
    assert _lines(text, "K2") == ["2026-05 5000", "2026-06 4800 dpd 30 od 200"]
    assert "dpd = days delayed and od = overdue amount" in text


def test_a_reporting_gap_breaks_a_run():
    history = [_row(_CARD, m, 0, 5000) for m in (6, 5, 3, 2, 1)]
    assert _lines(tables.build(_ctx(history))["text"], "K1") == [
        "2026-01 0 lim 5000", "2026-02 0", "2026-04..2026-06 0 x3"]


def test_tables_show_the_minimum_payment_flag_only_when_delivered():
    history = [_row(_CARD, 3, 1000, 5000), _row(_CARD, 2, 1000, 5000),
               _row(_CARD, 1, 1000, 5000)]
    text = tables.build(_ctx(history))["text"]
    assert " mp " not in text and "minimum-payment" not in text
    history[0]["MinimumPaymentFlag"] = True
    history[1]["MinimumPaymentFlag"] = True
    text = tables.build(_ctx(history))["text"]
    assert "minimum-payment flag" in text
    assert _lines(text, "K1") == ["2026-04 1000 lim 5000 mp 1", "2026-05 1000",
                                  "2026-06 1000 mp -"]


def test_the_headline_index_skips_series_background_and_step_facts():
    ctx = context.from_file(SYNTHETIC)
    facts = brief_facts.build(ctx)
    index = brief_facts.index(facts)
    themes = {line.split("[")[1].split("]")[0] for line in index.splitlines()}
    assert themes <= set(brief_facts.INDEX_THEMES)
    assert "[trajectory]" not in index and "[background]" not in index
    assert "[risk]" not in index
    assert all(len(line) <= brief_facts.INDEX_CHARS + 30 for line in index.splitlines())


def test_the_hypothesis_pass_indexes_structure_and_behaviour_only():
    ctx = context.from_file(SYNTHETIC)
    provider = _Provider({"hypotheses": []})
    analysis = brief.new_analysis(ctx, provider)
    brief.generate_block(ctx, provider, analysis, "lens")
    index = provider.calls[0][1].split("BEGIN HEADLINE INDEX\n")[1]
    themes = {line.split("[")[1].split("]")[0]
              for line in index.split("\nEND HEADLINE INDEX")[0].splitlines()}
    assert themes == {"structure", "behavior"}


# --- grammar -------------------------------------------------------------------

def test_parse_normalises_defaults_drops_bad_entries_and_dedupes():
    aliases = {"K1": {}, "K2": {}}
    typed, custom, dropped = grammar.parse({"hypotheses": [
        {"type": "balance_oscillation", "contract": "K1"},
        {"type": "balance_oscillation", "contract": "K1", "window": 12},
        {"type": "utilisation_rise_after", "contract": "K2", "event": "application",
         "months": 3},
        {"type": "utilisation_rise_after", "contract": "K9", "event": "application"},
        {"type": "correlated_delays", "contracts": ["K1"]},
        {"type": "correlated_delays", "contracts": ["K2", "K1", "K2"]},
        {"type": "delay_cluster", "months_of_year": [12, 1, 1, 13]},
        {"type": "closure_before_enquiry", "window": 99},
        {"type": "custom", "text": " A note. "},
        {"type": "custom"},
        {"type": "unknown_thing"},
        "not an object",
    ]}, aliases)
    assert typed == [
        {"type": "balance_oscillation", "params": {"contract": "K1", "window": 12}},
        {"type": "utilisation_rise_after",
         "params": {"contract": "K2", "event": "application", "months": 3}},
        {"type": "correlated_delays", "params": {"contracts": ["K2", "K1"]}},
        {"type": "delay_cluster", "params": {"months_of_year": [1, 12]}},
        {"type": "closure_before_enquiry", "params": {"window": 12}},
    ]
    assert custom == ["A note."]
    assert "duplicate hypothesis (balance_oscillation)" in dropped
    assert "utilisation_rise_after: missing or invalid contract" in dropped
    assert "correlated_delays: missing or invalid contracts" in dropped
    assert "custom hypothesis without text" in dropped
    assert "unknown hypothesis type 'unknown_thing'" in dropped
    assert "hypothesis is not an object" in dropped


def test_parse_caps_typed_and_custom_entries():
    aliases = {"K1": {}}
    raw = {"hypotheses": [{"type": "balance_oscillation", "contract": "K1",
                           "window": w} for w in range(1, 20)]
           + [{"type": "custom", "text": "note %d" % i} for i in range(5)]}
    typed, custom, dropped = grammar.parse(raw, aliases)
    assert len(typed) == grammar.MAX_TYPED and len(custom) == grammar.MAX_CUSTOM
    assert dropped.count("over the 12-hypothesis cap") == 7
    assert dropped.count("over the 3-observation cap") == 2


def test_parse_rejects_a_reply_that_is_not_a_hypotheses_object():
    assert grammar.parse({"findings": []}, {}) == (
        [], [], ["model output is not a hypotheses object"])


def test_schema_is_flat_and_lists_every_type():
    props = grammar.SCHEMA["properties"]["hypotheses"]["items"]["properties"]
    assert set(props["type"]["enum"]) == set(grammar.TYPES) | {grammar.CUSTOM}
    assert "oneOf" not in str(grammar.SCHEMA)
    assert h_prompt.HYPOTHESES_SCHEMA is grammar.SCHEMA
    for type_ in grammar.TYPES:
        assert type_ in h_prompt.SYSTEM


# --- verifiers -----------------------------------------------------------------

def test_utilisation_rise_after_a_loan_opening():
    # The loan opened 12 months before the report; the card sits at 40%
    # before it and 70% six months later.
    history = [_row(_CARD, m, 18000, 45000, 40) for m in range(20, 12, -1)]
    history += [_row(_CARD, m, 31500, 45000, 70) for m in range(6, -1, -1)]
    payload = _payload(history)
    loan = next(c for c in payload["contracts"] if c["CBContractId"] == _LOAN)
    loan["OpenDate"] = "15 July 2025"
    result = _one(context_of(payload), "utilisation_rise_after", contract="K1",
                  event="loan_opened", months=6)
    assert result["status"] == verify.CONFIRMED
    assert "rose from 40% (2025-06) to 70% (2026-01)" in result["text"]
    assert "Personal Loan L52913744" in result["text"]
    assert "contracts[].OpenDate" in result["fields"]


def test_utilisation_rise_after_is_refuted_or_not_assessable():
    flat = [_row(_CARD, m, 18000, 45000, 40) for m in range(20, -1, -1)]
    payload = _payload(flat)
    loan = next(c for c in payload["contracts"] if c["CBContractId"] == _LOAN)
    loan["OpenDate"] = "15 July 2025"
    result = _one(context_of(payload), "utilisation_rise_after", contract="K1",
                  event="loan_opened", months=6)
    assert result["status"] == verify.NOT_SUPPORTED
    assert "no rise of 15 points or more" in result["text"]
    # Not a card: not assessable; no event of that kind: not assessable.
    assert _one(context_of(payload), "utilisation_rise_after", contract="K2",
                event="loan_opened", months=6)["status"] == verify.NOT_ASSESSABLE
    assert _one(context_of(payload), "utilisation_rise_after", contract="K1",
                event="limit_change", months=6)["text"].startswith(
        "no limit change event")


def test_delay_cluster_confirms_only_a_recurring_and_distinctive_cluster():
    # Delays in December and January of two consecutive winters, clean otherwise.
    history = []
    for m in range(30, -1, -1):
        when = _month(m)
        dpd = 30 if when[5:] in ("12", "01") else 0
        history.append(_row(_LOAN, m, 50000, None, None, dpd, category="I"))
    ctx = _ctx(history)
    result = _one(ctx, "delay_cluster", months_of_year=[12, 1])
    assert result["status"] == verify.CONFIRMED
    assert "December: 2024, 2025" in result["text"] and "January: 2024, 2025, 2026" in result["text"]
    assert _one(ctx, "delay_cluster", months_of_year=[6])["status"] == verify.NOT_SUPPORTED
    # Late every month of every year: recurring everywhere, clustering nowhere.
    always = [_row(_LOAN, m, 50000, None, None, 30, category="I")
              for m in range(30, -1, -1)]
    result = _one(_ctx(always), "delay_cluster", months_of_year=[12, 1])
    assert result["status"] == verify.NOT_SUPPORTED and "most other months" in result["text"]
    # A whole year is not a season.
    result = _one(ctx, "delay_cluster", months_of_year=list(range(1, 13)))
    assert result["status"] == verify.NOT_SUPPORTED and "at most 4" in result["text"]
    # Under two years of history: not assessable.
    short = [_row(_LOAN, m, 50000, None, None, 30, category="I") for m in range(5)]
    assert _one(_ctx(short), "delay_cluster", months_of_year=[12])["status"] == verify.NOT_ASSESSABLE


def test_balance_oscillation_counts_pay_down_then_re_use_swings():
    limit = 45000
    pattern = [40000, 10000, 42000, 9000, 41000, 40000]      # two full swings
    history = [_row(_CARD, len(pattern) - 1 - i, bal, limit, bal * 100 // limit)
               for i, bal in enumerate(pattern)]
    result = _one(_ctx(history), "balance_oscillation", contract="K1", window=12)
    assert result["status"] == verify.CONFIRMED
    assert "2 swing(s)" in result["text"] and "AED 10,000" in result["text"]
    one_swing = [40000, 10000, 42000, 41000, 40000, 39000]
    history = [_row(_CARD, len(one_swing) - 1 - i, bal, limit, bal * 100 // limit)
               for i, bal in enumerate(one_swing)]
    result = _one(_ctx(history), "balance_oscillation", contract="K1", window=12)
    assert result["status"] == verify.NOT_SUPPORTED and "1 pay-down-and-re-use swing" in result["text"]
    assert _one(_ctx(history[:3]), "balance_oscillation", contract="K1",
                window=12)["status"] == verify.NOT_ASSESSABLE
    assert _one(_ctx(history), "balance_oscillation", contract="K2",
                window=12)["text"].endswith("is not a card")


def test_limit_increase_then_utilisation_catch_up():
    history = [_row(_CARD, 8, 27000, 30000, 90), _row(_CARD, 7, 27000, 30000, 90),
               _row(_CARD, 6, 27000, 45000, 60), _row(_CARD, 5, 31500, 45000, 70),
               _row(_CARD, 4, 40500, 45000, 90), _row(_CARD, 3, 42000, 45000, 93)]
    result = _one(_ctx(history), "limit_increase_then_utilisation", contract="K1")
    assert result["status"] == verify.CONFIRMED
    assert "rose from AED 30,000 to AED 45,000 in 2026-01" in result["text"]
    assert "back at 90% by 2026-03" in result["text"]
    history[-2]["UtilizationRate"] = 75
    history[-1]["UtilizationRate"] = 80
    result = _one(_ctx(history), "limit_increase_then_utilisation", contract="K1")
    assert result["status"] == verify.NOT_SUPPORTED and "at most 80%" in result["text"]
    flat = [_row(_CARD, m, 27000, 30000, 90) for m in range(5)]
    assert _one(_ctx(flat), "limit_increase_then_utilisation",
                contract="K1")["status"] == verify.NOT_ASSESSABLE


def test_closure_before_enquiry_finds_closures_and_cleared_overdues():
    history = [_row(_CARD, 4, 5000, 45000, 11, 30, 1500),
               _row(_CARD, 3, 5000, 45000, 11, 0, 0),
               _row(_CARD, 2, 5000, 45000, 11, 0, 0)]
    payload = _payload(history)
    loan = next(c for c in payload["contracts"] if c["CBContractId"] == _LOAN)
    loan["ActiveFlag"], loan["ClosedDate"] = "Closed", "10 June 2026"
    result = _one(context_of(payload), "closure_before_enquiry", window=3)
    assert result["status"] == verify.CONFIRMED
    assert "Personal Loan L52913744 (B04) closed 2026-06" in result["text"]
    assert "overdue AED 1,500 (2026-03) cleared to 0 by 2026-04" in result["text"]
    # Narrow the window past both events: refuted.
    quiet = _payload([_row(_CARD, 2, 5000, 45000, 11)])
    assert _one(context_of(quiet), "closure_before_enquiry",
                window=1)["status"] == verify.NOT_SUPPORTED


def test_application_burst_then_delay():
    apps = [{"ContractType": "Personal Loan", "ProviderNo": "B01",
             "Phase": "Requested ", "LastUpdateDate": "%s-10T00:00:00" % _month(m),
             "TotalAmount": 10000} for m in (12, 11, 10)]
    history = [_row(_LOAN, m, 50000, None, None, 0, category="I") for m in (14, 13, 12, 11, 10, 9)]
    history.append(_row(_LOAN, 7, 50000, None, None, 35, 2000, category="I"))
    result = _one(_ctx(history, applications=apps), "application_burst_then_delay",
                  window=6)
    assert result["status"] == verify.CONFIRMED
    assert "3 applications between 2025-07 and 2025-09" in result["text"]
    assert "began on Personal Loan L52913744" in result["text"] and "2025-12" in result["text"]
    clean = [_row(_LOAN, m, 50000, None, None, 0, category="I") for m in range(14, 0, -1)]
    result = _one(_ctx(clean, applications=apps), "application_burst_then_delay",
                  window=6)
    assert result["status"] == verify.NOT_SUPPORTED and "no new payment delay" in result["text"]
    result = _one(_ctx(clean, applications=apps[:2]), "application_burst_then_delay",
                  window=6)
    assert result["status"] == verify.NOT_SUPPORTED and "no burst of 3 or more" in result["text"]
    assert _one(_ctx(clean, applications=[]), "application_burst_then_delay",
                window=6)["status"] == verify.NOT_ASSESSABLE


def test_income_decline_across_updates():
    employment = [
        {"EmploymentName": "ALPHA LLC", "GrossAnnualIncome": 120000,
         "DateOfEmployment": "2021-01-01T00:00:00", "DateOfTermination": "2023-01-01T00:00:00",
         "DateOfLastUpdate": "2023-01-15T00:00:00", "ProviderNo": "B01"},
        {"EmploymentName": "BETA LLC", "GrossAnnualIncome": 90000,
         "DateOfEmployment": "2023-02-01T00:00:00", "DateOfTermination": None,
         "DateOfLastUpdate": "2026-05-01T00:00:00", "ProviderNo": "B02"},
    ]
    result = _one(_ctx([], employment=employment), "income_decline_across_updates")
    assert result["status"] == verify.CONFIRMED
    assert "fell from AED 120,000 to AED 90,000" in result["text"]
    assert "BETA LLC" in result["text"] and "ALPHA LLC" in result["text"]
    employment[1]["GrossAnnualIncome"] = 130000
    result = _one(_ctx([], employment=employment), "income_decline_across_updates")
    assert result["status"] == verify.NOT_SUPPORTED
    assert _one(_ctx([], employment=employment[:1]),
                "income_decline_across_updates")["status"] == verify.NOT_ASSESSABLE


def test_correlated_delays():
    history = [_row(_CARD, m, 20000, 45000, 44, 30 if m <= 5 else 0) for m in range(10, -1, -1)]
    history += [_row(_LOAN, m, 50000, None, None, 30 if m <= 4 else 0, category="I")
                for m in range(10, -1, -1)]
    result = _one(_ctx(history), "correlated_delays", contracts=["K1", "K2"])
    assert result["status"] == verify.CONFIRMED
    assert "1 month(s) apart" in result["text"] and "5 delinquent month(s) in common" in result["text"]
    history = [_row(_CARD, m, 20000, 45000, 44, 30 if m >= 9 else 0) for m in range(10, -1, -1)]
    history += [_row(_LOAN, m, 50000, None, None, 30 if m <= 1 else 0, category="I")
                for m in range(10, -1, -1)]
    result = _one(_ctx(history), "correlated_delays", contracts=["K1", "K2"])
    assert result["status"] == verify.NOT_SUPPORTED
    clean = [_row(_CARD, m, 20000, 45000, 44, 0) for m in range(3)]
    clean += [_row(_LOAN, m, 50000, None, None, 30, category="I") for m in range(3)]
    assert _one(_ctx(clean), "correlated_delays",
                contracts=["K1", "K2"])["status"] == verify.NOT_SUPPORTED
    assert _one(_ctx(clean[3:]), "correlated_delays",
                contracts=["K1", "K2"])["status"] == verify.NOT_ASSESSABLE


def test_results_become_facts_with_sequential_ids_and_their_status():
    history = [_row(_CARD, m, 20000, 45000, 44, 0) for m in range(3)]
    ctx = _ctx(history)
    results = verify.run(ctx, [
        {"type": "closure_before_enquiry", "params": {"window": 3}},
        {"type": "limit_increase_then_utilisation", "params": {"contract": "K1"}},
    ], _aliases(ctx))
    facts = verify.as_facts(results, 61)
    assert [f["id"] for f in facts] == ["F061"]          # not-assessable yields no fact
    assert facts[0]["theme"] == "verified" and facts[0]["status"] == "not_supported"
    assert facts[0]["text"].startswith("Verified hypothesis (not supported): ")
    assert facts[0]["section"] == "facilities" and facts[0]["fields"]
    assert "closure before enquiry" in facts[0]["hypothesis"]


def test_every_verifier_runs_on_both_fixtures_without_error(fixture_path):
    ctx = context.from_file(fixture_path)
    aliases = _aliases(ctx)
    results = verify.run(ctx, candidates.generate(ctx, aliases), aliases)
    assert results and all(r["status"] in (verify.CONFIRMED, verify.NOT_SUPPORTED,
                                           verify.NOT_ASSESSABLE) for r in results)
    assert all(r["text"] for r in results)


# --- fallback ------------------------------------------------------------------

def test_candidates_put_file_level_hypotheses_first_and_respect_the_cap():
    ctx = context.from_file(SYNTHETIC)
    out = candidates.generate(ctx, _aliases(ctx))
    assert len(out) <= candidates.MAX_CANDIDATES
    types = [h["type"] for h in out]
    assert types[:3] == ["closure_before_enquiry", "application_burst_then_delay",
                         "income_decline_across_updates"]
    assert "correlated_delays" in types and "delay_cluster" in types
    assert all(h["type"] in grammar.TYPES for h in out)
    # Re-parse through the grammar: the shape is the model's shape.
    raw = {"hypotheses": [dict(h["params"], type=h["type"]) for h in out]}
    typed, _, dropped = grammar.parse(raw, _aliases(ctx))
    assert typed == out and not dropped


# --- validation ------------------------------------------------------------------

def _facts():
    return [{"id": "F001", "theme": "structure", "text": "Total exposure AED 115,300.",
             "fields": [], "section": "facilities"},
            {"id": "F002", "theme": "verified", "status": "not_supported",
             "text": "Verified hypothesis (not supported): no swing on the card.",
             "fields": [], "section": "detail"},
            {"id": "F003", "theme": "verified", "status": "confirmed",
             "text": "Verified hypothesis (confirmed): balance swung AED 9,000 to AED 41,000.",
             "fields": [], "section": "detail"}]


def _finding(**kw):
    base = {"claim": "A claim.", "so_what": "So.", "severity": "severe",
            "confidence": "high", "cites": ["F001"], "framing": "story"}
    base.update(kw)
    return base


def test_framing_is_kept_when_known_and_blank_otherwise():
    found, _, _, dropped = validate.validate(
        {"findings": [_finding(framing="intent"), _finding(framing="nope", cites=["F003"]),
                      _finding(cites=["F002", "F003"])],
         "unknowns": [], "background": []}, _facts())
    assert [f["framing"] for f in found] == ["intent", "", "story"]
    assert not dropped


def test_a_finding_resting_only_on_refuted_hypotheses_is_capped_at_watch():
    found, _, _, dropped = validate.validate(
        {"findings": [_finding(cites=["F002"], severity="severe")],
         "unknowns": [], "background": []}, _facts())
    assert found[0]["severity"] == "watch"
    assert dropped == ["severity capped at watch: the finding rests only on "
                       "refuted hypotheses"]
    for cites, severity in ((["F002"], "info"), (["F002", "F003"], "severe"),
                            (["F002", "F001"], "adverse"), (["F003"], "severe")):
        found, _, _, dropped = validate.validate(
            {"findings": [_finding(cites=cites, severity=severity)],
             "unknowns": [], "background": []}, _facts())
        assert found[0]["severity"] == severity and not dropped


def test_observations_are_vouched_against_their_source_text_only():
    source = "K1 | Credit Card C41880273 (B01) | 45000 | 52340\nDU TELECOM | 24800"
    kept, dropped = validate.validate_observations(
        ["The card at 52340 is over its 45000 limit.", "DU TELECOM pays 24800.",
         "Exposure of AED 115,300.", "Falcon Trading employs them.",
         "The card at 52340 is over its 45000 limit.", "", "F001 F002"], source)
    assert kept == ["The card at 52340 is over its 45000 limit.",
                    "DU TELECOM pays 24800."]
    assert dropped == ["observation carries figures not in the tables: 115300",
                       "observation carries names not in the tables: trading",
                       "duplicate observation", "empty observation",
                       "observation was only fact references"]
    kept, dropped = validate.validate_observations(["a", "b", "c", "d"], "a b c d")
    assert kept == ["a", "b", "c"] and dropped == ["over the 3-observation cap"]


def test_observations_resolve_contract_aliases_to_labels():
    source = "K1 | Credit Card C41880273 (B01) | 45000\nK2 | Auto Loan A1 (B09) | -"
    labels = {"K1": ("Credit Card C41880273 (B01)", "C41880273"),
              "K2": ("Auto Loan A1 (B09)", "A1")}
    kept, dropped = validate.validate_observations(
        ["K1's balance is 45000 while K2 is clean.",
         "K1 Credit Card C41880273 (B01) is at 45000."], source, labels)
    assert kept == ["Credit Card C41880273 (B01)'s balance is 45000 while "
                    "Auto Loan A1 (B09) is clean.",
                    "Credit Card C41880273 (B01) is at 45000."] and not dropped
    # Unknown aliases are left alone (and then face the figure guard like
    # any other token); alias-shaped substrings of other words are untouched.
    assert validate._resolve_aliases("K7, K12, KK1 and K1X stay; K1 goes.",
                                     labels) == "K7, K12, KK1 and K1X stay; Credit Card C41880273 (B01) goes."


# --- the block -------------------------------------------------------------------

class _Provider(FakeProvider):
    """Answers pass H with `hypotheses` and pass W with `findings`."""

    def __init__(self, hypotheses, findings=None):
        super().__init__(self._answer)
        self.hypotheses, self.findings = hypotheses, findings

    def _answer(self, system, user, schema):
        if schema is h_prompt.HYPOTHESES_SCHEMA:
            return self.hypotheses
        return self.findings(user) if callable(self.findings) else {
            "findings": [], "unknowns": [], "background": []}


def test_the_block_verifies_the_models_hypotheses_and_absorbs_the_facts():
    ctx = context.from_file(SYNTHETIC)
    provider = _Provider({"hypotheses": [
        {"type": "closure_before_enquiry", "window": 3},
        {"type": "income_decline_across_updates"},
        {"type": "correlated_delays", "contracts": ["K1", "K2"]},
        {"type": "custom", "text": "The card K1 at 52340 is beyond its 45000 limit."},
        {"type": "custom", "text": "Falcon Trading is the employer."},
    ]})

    def findings(user):
        verified = [line.split()[0] for line in user.splitlines()
                    if "[verified]" in line]
        return {"findings": [
            {"claim": "A tested pattern.", "so_what": "It matters.",
             "severity": "adverse", "confidence": "high", "cites": verified[:1],
             "framing": "story"}], "unknowns": [], "background": []}
    provider.findings = findings

    analysis = brief.new_analysis(ctx, provider)
    before = len(analysis["facts"])
    block = brief.generate_block(ctx, provider, analysis, "lens")
    assert block["hypotheses_source"] == "model"
    assert [h["status"] for h in block["hypotheses"]] == [
        "not_supported", "not_supported", "confirmed"]
    # Verified facts continue the digest's numbering and are part of the analysis.
    added = [f for f in analysis["facts"] if f["theme"] == "verified"]
    assert len(analysis["facts"]) == before + 3 == len(analysis["facts_by_id"])
    assert [f["id"] for f in added] == ["F%03d" % (before + i) for i in (1, 2, 3)]
    assert "new_facts" not in block
    assert block["findings"][0]["cites"] == [added[0]["id"]]
    assert block["findings"][0]["framing"] == "story"
    # The custom texts: one vouched by the tables (its alias resolved to the
    # contract's label), one with an invented name.
    assert block["observations"] == ["The card Credit Card C41880273 (B01) at 52340 "
                                     "is beyond its 45000 limit."]
    assert "observation carries names not in the tables: trading" in block["dropped"]
    assert block["tables_months"] == 36
    assert "confirmed hypothesis" in brief.blocks.MODULES["lens"].summary(block)
    # The W turn carried the verified facts and a pointer to the confirmed
    # one; the H turn carried the tables.
    assert "[verified]" in provider.calls[1][1] and "BEGIN TABLES" in provider.calls[0][1]
    assert "Confirmed verified facts (each must be cited by the finding that " \
        "describes its pattern): %s." % added[2]["id"] in provider.calls[1][1]


def test_the_block_falls_back_to_python_candidates_when_nothing_typed_came_back():
    ctx = context.from_file(SYNTHETIC)
    provider = _Provider({"hypotheses": [{"type": "custom", "text": "Only prose."}]})
    analysis = brief.new_analysis(ctx, provider)
    block = brief.generate_block(ctx, provider, analysis, "lens")
    assert block["hypotheses_source"] == "fallback"
    assert len(block["hypotheses"]) == len(candidates.generate(ctx, _aliases(ctx)))
    assert block["observations"] == ["Only prose."]
    assert any(f["theme"] == "verified" for f in analysis["facts"])


def test_pass_w_reads_the_tripwire_step_facts_and_the_validity_fact_only():
    ctx = context.from_file(SYNTHETIC)
    hidden = []

    def findings(_user):
        return {"findings": [{"claim": "Age noted.", "so_what": "", "severity": "info",
                              "confidence": "low", "cites": hidden, "framing": "story"}],
                "unknowns": [], "background": []}
    provider = _Provider({"hypotheses": []}, findings)
    analysis = brief.new_analysis(ctx, provider)
    for packet in analysis["packets"]:
        packet["tripwires"] = [fid for fid in packet["tripwires"]
                               if packet["key"] == "conduct"]
    validity = next(p for p in analysis["packets"] if p["key"] == "validity")
    conduct = next(p for p in analysis["packets"] if p["key"] == "conduct")
    profile = next(p for p in analysis["packets"] if p["key"] == "profile")
    hidden.append(profile["fact_ids"][-1])        # a step fact W never sees
    block = brief.generate_block(ctx, provider, analysis, "lens")
    w_turn = provider.calls[1][1]
    shown = {f["id"] for f in analysis["facts"] if f["theme"] == "step"
             and "\n%s [step]" % f["id"] in w_turn}
    assert shown == set(validity["fact_ids"]) | set(conduct["tripwires"])
    # W is held to what it read: a cite of an unseen step fact is unknown.
    assert block["findings"] == []
    assert any("cites unknown fact(s) %s" % hidden[0] in d for d in block["dropped"])


def test_a_failed_findings_pass_absorbs_no_facts_so_the_retry_is_clean():
    ctx = context.from_file(SYNTHETIC)
    provider = _Provider({"hypotheses": [{"type": "closure_before_enquiry", "window": 3}]})

    def boom(_user):
        raise brief.BriefUnavailable("model died")
    provider.findings = boom
    analysis = brief.new_analysis(ctx, provider)
    before = len(analysis["facts"])
    with pytest.raises(brief.BriefUnavailable, match="model died"):
        brief.generate_block(ctx, provider, analysis, "lens")
    assert len(analysis["facts"]) == before and brief.next_missing(analysis) == "lens"


def test_both_turns_pass_the_prohibited_field_check():
    ctx = context.from_file(SYNTHETIC)
    provider = _Provider({"hypotheses": []})
    analysis = brief.new_analysis(ctx, provider)
    seen = []
    original = analysis["check_prohibited"]

    def record(message):
        seen.append(message)
        original(message)
    analysis["check_prohibited"] = record
    brief.generate_block(ctx, provider, analysis, "lens")
    assert len(seen) == 2 and "BEGIN TABLES" in seen[0] and "BEGIN FACT TABLE" in seen[1]


def test_a_prohibited_word_in_the_tables_refuses_the_block(monkeypatch):
    """The digest check runs at new_analysis; the H turn is checked again on
    its own text, so a leak only the tables carry still stops the block."""
    ctx = context.from_file(SYNTHETIC)
    provider = _Provider({"hypotheses": []})
    analysis = brief.new_analysis(ctx, provider)
    real = tables.build

    def leaky(ctx_, budget_chars=tables.BUDGET_CHARS):
        built = real(ctx_, budget_chars)
        built["text"] += "\nGender | Male"
        return built
    monkeypatch.setattr(tables, "build", leaky)
    with pytest.raises(brief.BriefUnavailable, match="prohibited-field"):
        brief.generate_block(ctx, provider, analysis, "lens")
    assert not provider.calls and brief.next_missing(analysis) == "lens"
