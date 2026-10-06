"""The Python fallback for pass H.

When the model proposes no typed hypothesis (it answered only in custom
text, or with nothing usable), the fresh lens still gets a verified-facts
layer: a fixed candidate list drawn from the payload's shape, run through
the same verifiers. The block records that the hypotheses came from the
fallback rather than the model, and the evaluation harness asserts that on
the golden fixture the model, not the fallback, proposed them.
"""

from __future__ import annotations

from ...coerce import number
from ...derive.brief_facts._common import CAT_CARD, category, history_by_contract
from . import grammar

MAX_CANDIDATES = grammar.MAX_TYPED


def _delayed_aliases(ctx, aliases):
    by_contract = history_by_contract(ctx)
    out = []
    for alias, contract in aliases.items():
        history = by_contract.get(contract.get("CBContractId")) or []
        if any((number(r.get("DaysPaymentDelay")) or 0) > 0 for _, r in history):
            out.append(alias)
    return out


def _busiest_calendar_months(ctx):
    """The two calendar months with delays in the most distinct years."""
    years_by_month = {}
    for row in ctx.rows("contractsHistory"):
        when = str(row.get("ReferenceDate") or "")[:7]
        if len(when) == 7 and (number(row.get("DaysPaymentDelay")) or 0) > 0:
            years_by_month.setdefault(int(when[5:7]), set()).add(when[:4])
    ranked = sorted(years_by_month, key=lambda m: (-len(years_by_month[m]), m))
    return ranked[:2]


def generate(ctx, aliases) -> list:
    """Typed hypotheses in the grammar's shape, at most MAX_CANDIDATES.

    File-level candidates first, then one set per card, so a large book
    loses card candidates to the cap, never the cross-contract ones.
    """
    out = [{"type": "closure_before_enquiry", "params": {"window": 3}},
           {"type": "application_burst_then_delay", "params": {"window": 6}},
           {"type": "income_decline_across_updates", "params": {}}]
    delayed = _delayed_aliases(ctx, aliases)[:4]
    if len(delayed) >= 2:
        out.append({"type": "correlated_delays", "params": {"contracts": delayed}})
    months = _busiest_calendar_months(ctx)
    if months:
        out.append({"type": "delay_cluster",
                    "params": {"months_of_year": sorted(months)}})
    for alias, contract in aliases.items():
        if category(contract) != CAT_CARD:
            continue
        out.append({"type": "balance_oscillation",
                    "params": {"contract": alias, "window": 24}})
        out.append({"type": "limit_increase_then_utilisation",
                    "params": {"contract": alias}})
        out.append({"type": "utilisation_rise_after",
                    "params": {"contract": alias, "event": "loan_opened",
                               "months": 6}})
    return out[:MAX_CANDIDATES]
