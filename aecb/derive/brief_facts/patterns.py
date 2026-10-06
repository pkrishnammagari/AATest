"""Pattern arithmetic shared by the risk lenses and the hypothesis verifiers.

One definition per pattern: the always-on lenses (cycling, seasonality,
cleanup, concentration) state a pattern as a fact whenever the evidence
exists, and the verifiers (aecb/brief/hypotheses/verify.py) answer the
model's hypothesis about it. Both call the functions here, so a threshold
is documented once (docs/AI_ANALYSIS_MRM.md section 3a/3b) and changes once.

Everything takes histories as (month 'YYYY-MM', row) pairs sorted by month,
as _common.history_by_contract builds them, and returns plain values; no
text is composed here.
"""

from __future__ import annotations

from ... import dates
from ...coerce import flag, number
from .. import income


def month_add(when: str, delta: int) -> str:
    return dates.add_months(when + "-01", delta).strftime("%Y-%m")


def months_apart(earlier: str, later: str) -> int:
    return ((int(later[:4]) - int(earlier[:4])) * 12
            + int(later[5:7]) - int(earlier[5:7]))


def dpd(row):
    return number(row.get("DaysPaymentDelay"))


# --- balance swings (cycling) -------------------------------------------------------

def balances_with_limit(contract, history, cutoff: str) -> list:
    """(month, balance, limit) from the cutoff month on; the row's limit, or
    the contract's current limit where the row carries none."""
    fallback = number(contract.get("Current_CreditLimit"))
    out = []
    for when, row in history:
        balance = number(row.get("Balance"))
        limit = number(row.get("CreditLimit"))
        limit = fallback if limit is None else limit
        if when >= cutoff and balance is not None:
            out.append((when, balance, limit))
    return out


def swings(pairs, trough_share: float, peak_share: float) -> list:
    """((trough month, balance), (peak month, balance)) per pay-down-then-
    re-use swing: a balance at or below trough_share of the limit followed
    by one at or above peak_share of it."""
    out, trough = [], None
    for when, balance, limit in pairs:
        if not limit:
            continue
        if balance <= trough_share * limit:
            if trough is None or balance < trough[1]:
                trough = (when, balance)
        elif balance >= peak_share * limit and trough is not None:
            out.append((trough, (when, balance)))
            trough = None
    return out


def _utilisation(row, fallback_limit):
    """The row's utilisation %, by the delivered rate where present, else
    the balance against the limit; None when neither can be read."""
    util = number(row.get("UtilizationRate"))
    if util is not None:
        return util
    balance, limit = number(row.get("Balance")), number(row.get("CreditLimit"))
    limit = fallback_limit if limit is None else limit
    return balance * 100.0 / limit if balance is not None and limit else None


def _longest_run(history, hit) -> tuple:
    """(months, first, last) of the longest run of consecutive reported
    months for which hit(row) is true."""
    best = run = 0
    start = best_start = best_end = None
    for when, row in history:
        if hit(row):
            run += 1
            start = start or when
            if run > best:
                best, best_start, best_end = run, start, when
        else:
            run, start = 0, None
    return best, best_start, best_end


def maxed_run(contract, history, share: float) -> tuple:
    """(months, first month, last month) of the longest run of consecutive
    reported months at or above `share` of the limit."""
    fallback = number(contract.get("Current_CreditLimit"))

    def maxed(row):
        util = _utilisation(row, fallback)
        return util is not None and util >= share * 100
    return _longest_run(history, maxed)


def minpay_spend_streak(history) -> tuple:
    """(months, first, last) of the longest run of reported months with the
    minimum-payment flag set AND spending or billing above zero. Zero when
    the card-activity fields are not delivered -- absence is not evidence."""
    def hit(row):
        spent = (number(row.get("AmountSpent")) or 0) + (number(row.get("BilledAmount")) or 0)
        return flag(row.get("MinimumPaymentFlag")) is True and spent > 0
    return _longest_run(history, hit)


# --- delays ---------------------------------------------------------------------------

def delayed_years(histories) -> tuple:
    """({calendar month: years with a delayed month}, all years reported)
    over labelled histories [(label, history), ...]."""
    years_by_month, years = {}, set()
    for _label, history in histories:
        for when, row in history:
            year, cal = int(when[:4]), int(when[5:7])
            years.add(year)
            if (dpd(row) or 0) > 0:
                years_by_month.setdefault(cal, set()).add(year)
    return years_by_month, years


def delay_onsets(histories) -> list:
    """Sorted (month, label) where a contract's delay began after a clean
    reported month (or at its first reported month)."""
    onsets = []
    for label, history in histories:
        clean = True
        for when, row in history:
            delay = dpd(row)
            if delay is None:
                continue
            if delay > 0 and clean:
                onsets.append((when, label))
            clean = delay == 0
    return sorted(onsets)


def clearances(histories, cutoff: str) -> list:
    """(label, overdue amount, last overdue month, cleared month) for each
    contract whose overdue went from above zero to zero at or after the
    cutoff month and stayed at zero."""
    out = []
    for label, history in histories:
        last = previous = None
        for when, row in history:
            overdue = number(row.get("OverdueAmount"))
            if overdue is None:
                continue
            if previous and previous[1] > 0 and overdue == 0 and when >= cutoff:
                last = (previous[0], previous[1], when)
            previous = (when, overdue)
        if last is not None and (previous is None or previous[1] == 0):
            out.append((label, last[1], last[0], last[2]))
    return out


# --- income ---------------------------------------------------------------------------

def income_sequence(ctx) -> list:
    """Dated, usable income figures as (date, amount, employer name), oldest
    first. The date is the record's last update, else its start date."""
    story = income.build(ctx)
    dated = [((r.updated or r.started), number(r.income), r.name)
             for r in story["records"]
             if r.income_usable and number(r.income) and (r.updated or r.started)]
    return sorted(dated, key=lambda item: item[0])
