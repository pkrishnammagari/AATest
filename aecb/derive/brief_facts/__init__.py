"""Fact digest for the AI underwriting brief.

The brief's model is a finding selector, never a calculator: every join,
trajectory and aggregate is computed HERE, deterministically, and handed to the
model as a numbered fact table. The model connects facts and cites their IDs;
it is never shown raw payload JSON, so a figure it did not receive is a figure
it cannot legitimately emit -- and aecb.brief.validate drops any claim whose
numbers do not appear verbatim in the facts it cites.

One module per lens:

    structure      -- portfolio shape, guarantees, maturity runway, file age,
                      recent limit grants, buried summary counters, obligation
                      components.
    trajectory     -- per-contract time series from contractsHistory.
    inconsistency  -- cross-array joins: income story, applications against
                      contracts, summary against detail, document expiry,
                      flags across five arrays.
    behavior       -- payment waterfall, early-tenor delinquency, returned
                      instruments, post-loan balances, dormant cards.
    absence        -- what the file does NOT establish.
    cycling, seasonality, cleanup, concentration
                   -- the non-obvious-risk lenses (theme "risk"): card usage
                      patterns, delays that return with the calendar,
                      pre-enquiry clean-up, where the exposure sits and who
                      gets paid. Shared arithmetic in patterns.py.
    background     -- curated, as-of-dated macro context and register
                      (optional config).

Each fact carries the exact payload fields behind it and the NAME of the report
section where the human can verify it (names, not numbers: displayed numbers
are assigned positionally in render/sections/__init__.py).

Facts are prose with plain figures, not JSON: the model reads them better, and
the validator only needs the numeric tokens, which survive either way.

PROHIBITED FIELDS -- policy, not preference: customerInfo.Nationality,
customerInfo.Gender and customerInfo.ResidentFlag must never enter a fact's
text or field list. Nationality and gender are impermissible underwriting
factors; ResidentFlag is nationality-adjacent and is excluded by decision --
it may only return as an explicit, documented compliance exception, never as
a code default. aecb.brief enforces this on every digest at runtime, and the
test suite asserts it. DOB-derived age stays.
"""

from __future__ import annotations

from . import (absence, background, behavior, cleanup, concentration, cycling,
               inconsistency, seasonality, structure, trajectory)
from ._common import (ABSENCE, BEHAVIOR, CAT_CARD, INCONSISTENCY, STRUCTURE,
                      Facts, category, contract_label, history_by_contract,
                      is_active)

PROHIBITED_FIELDS = ("Nationality", "Gender", "ResidentFlag")


def _per_contract(ctx, facts, by_contract):
    """Trajectory and card-behavior facts, contract by contract.

    Returns (label, history) pairs for every contract with history, and for
    the active ones -- the inputs of the cross-contract facts that follow.
    """
    labelled, labelled_active = [], []
    for contract in ctx.rows("contracts"):
        history = by_contract.get(contract.get("CBContractId"))
        if not history:
            continue
        label = contract_label(ctx, contract)
        labelled.append((label, history))
        if is_active(contract):
            labelled_active.append((label, history))
        if category(contract) == CAT_CARD:
            trajectory.utilization_series(facts, label, history)
            trajectory.limit_series(facts, label, history)
            trajectory.card_payment_pattern(facts, label, history)
            behavior.dormant_reactivation(facts, label, history)
        trajectory.delay_series(facts, label, history)
        trajectory.balance_trend(facts, label, history)
        trajectory.minimum_payment_streaks(facts, label, history)
    return labelled, labelled_active


def build(ctx):
    """The full fact list for one payload, in stable order."""
    facts = Facts()

    structure.portfolio(ctx, facts)
    structure.opening_dates(ctx, facts)
    structure.guarantees(ctx, facts)
    structure.worst_anchor(ctx, facts)
    structure.buried_counters(ctx, facts)
    structure.file_age(ctx, facts)
    structure.recent_originations(ctx, facts)
    structure.maturity_runway(ctx, facts)
    structure.applications_90d(ctx, facts)

    by_contract = history_by_contract(ctx)
    labelled, labelled_active = _per_contract(ctx, facts, by_contract)
    trajectory.overdue_onsets(facts, labelled)

    behavior.waterfall(ctx, facts, by_contract)
    behavior.method_of_payment(ctx, facts, by_contract)
    structure.obligation_components(ctx, facts)
    behavior.early_tenor_delinquency(ctx, facts, by_contract)

    inconsistency.income_story(ctx, facts)
    inconsistency.application_reconciliation(ctx, facts)
    inconsistency.summary_vs_detail(ctx, facts)
    inconsistency.document_staleness(ctx, facts)
    inconsistency.flag_sweep(ctx, facts)
    behavior.returned_instruments(ctx, facts)
    behavior.post_loan_balances(ctx, facts, by_contract)
    behavior.balance_transfer_trace(ctx, facts, by_contract)
    absence.reporting_gaps(ctx, facts, labelled_active)
    absence.income_corroboration(ctx, facts)

    cycling.card_usage(ctx, facts, by_contract)
    seasonality.seasonal_delays(ctx, facts, labelled)
    seasonality.coverage(ctx, facts, labelled_active)
    cleanup.pre_enquiry_cleanup(ctx, facts, labelled)
    concentration.lender_concentration(ctx, facts)
    concentration.nbfi_reliance(ctx, facts)
    concentration.guarantor_beside_own(ctx, facts)
    concentration.maturity_vs_age(ctx, facts)
    concentration.income_trajectory(ctx, facts)
    concentration.employer_churn(ctx, facts)
    concentration.selective_default(ctx, facts, by_contract)

    background.macro_facts(facts)

    return facts.rows


def digest(facts) -> str:
    """The fact table as the model sees it: one line per fact, id first."""
    return "\n".join("%s [%s] %s" % (f["id"], f["theme"], f["text"])
                     for f in facts)


def by_id(facts) -> dict:
    return {f["id"]: f for f in facts}


# The themes a headline index carries: payload lenses other than the
# per-contract series (the tables carry those) and curated background (not
# payload). Step facts are the checklist's arithmetic and stay out too. The
# risk block's index of "the rest of the file" uses INDEX_THEMES; the
# hypothesis pass reads only what a hypothesis can be about -- the file's
# structure and behaviour -- and never the risk lenses, which are block 2's.
# Lines are cut at INDEX_CHARS: a headline orients, the
# full fact is what a cite is checked against.
INDEX_THEMES = (STRUCTURE, INCONSISTENCY, BEHAVIOR, ABSENCE)
H_INDEX_THEMES = (STRUCTURE, BEHAVIOR)
INDEX_CHARS = 80


def index(facts, themes=INDEX_THEMES) -> str:
    """The digest as headlines: one truncated line per fact of `themes`."""
    lines = []
    for f in facts:
        if f["theme"] not in themes:
            continue
        text = f["text"]
        if len(text) > INDEX_CHARS:
            text = text[:INDEX_CHARS].rstrip() + "..."
        lines.append("%s [%s] %s" % (f["id"], f["theme"], text))
    return "\n".join(lines)
