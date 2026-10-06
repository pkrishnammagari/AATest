"""Cycling lens: how a card is USED month by month -- paid down and re-maxed,
held at the limit, serviced at the minimum while still spending. The
heatmap shows delay; these patterns live in the balance columns beside it."""

from __future__ import annotations

from ...coerce import number
from . import patterns
from ._common import (CAT_CARD, F_HIST_BALANCE, F_HIST_DATE, RISK, SEC_DETAIL,
                      category, contract_label, fmt)

# Same definitions as the balance_oscillation verifier (one pattern, one
# threshold set): a swing is a pay-down to <= TROUGH_SHARE of the limit
# followed by re-use to >= PEAK_SHARE; two swings in the window is cycling.
TROUGH_SHARE = 0.5
PEAK_SHARE = 0.8
MIN_SWINGS = 2
WINDOW_MONTHS = 24

# Cash-like card: at or above MAXED_SHARE of the limit for MAXED_MONTHS
# consecutive reported months -- a revolving line used as a cash advance.
MAXED_SHARE = 0.9
MAXED_MONTHS = 6

# Minimum-payment streak with spend: the flag set while spending continues.
MINPAY_SPEND_MONTHS = 3


def _cycling(facts, label, contract, history):
    cutoff = patterns.month_add(history[-1][0], -(WINDOW_MONTHS - 1))
    pairs = patterns.balances_with_limit(contract, history, cutoff)
    found = patterns.swings(pairs, TROUGH_SHARE, PEAK_SHARE)
    if len(found) < MIN_SWINGS:
        return
    limit = pairs[-1][2]
    facts.add(RISK,
              "Balance cycling on %s: paid down and re-used %d time(s) in the "
              "last %d reported months against a limit of AED %s -- %s. A card "
              "repeatedly cleared and refilled is used as a cash line, not for "
              "purchases paid off."
              % (label, len(found), WINDOW_MONTHS, fmt(limit),
                 "; ".join("AED %s (%s) to AED %s (%s)"
                           % (fmt(t[1]), t[0], fmt(p[1]), p[0])
                           for t, p in found)),
              [F_HIST_BALANCE, "contractsHistory[].CreditLimit", F_HIST_DATE],
              SEC_DETAIL)


def _cash_like(facts, label, contract, history):
    months, first, last = patterns.maxed_run(contract, history, MAXED_SHARE)
    if months < MAXED_MONTHS:
        return
    facts.add(RISK,
              "Cash-like card: %s stayed at or above %d%% of its limit for %d "
              "consecutive reported months (%s to %s). A line held at its "
              "ceiling leaves no absorption room and reads as borrowed cash."
              % (label, int(MAXED_SHARE * 100), months, first, last),
              ["contractsHistory[].UtilizationRate", F_HIST_BALANCE,
               F_HIST_DATE],
              SEC_DETAIL)


def _minpay_spend(facts, label, history):
    months, first, last = patterns.minpay_spend_streak(history)
    if months < MINPAY_SPEND_MONTHS:
        return
    facts.add(RISK,
              "Minimum payments while still spending on %s: the minimum-payment "
              "flag was set for %d consecutive reported months (%s to %s) with "
              "spending or billing above zero in each -- the balance is being "
              "serviced, not reduced, while new spend is added."
              % (label, months, first, last),
              ["contractsHistory[].MinimumPaymentFlag",
               "contractsHistory[].AmountSpent", "contractsHistory[].BilledAmount"],
              SEC_DETAIL)


def card_usage(ctx, facts, by_contract):
    for contract in ctx.rows("contracts"):
        if category(contract) != CAT_CARD:
            continue
        history = by_contract.get(contract.get("CBContractId")) or []
        if not history or not number(contract.get("Current_CreditLimit")) \
                and not any(number(r.get("CreditLimit")) for _, r in history):
            continue
        label = contract_label(ctx, contract)
        _cycling(facts, label, contract, history)
        _cash_like(facts, label, contract, history)
        _minpay_spend(facts, label, history)
