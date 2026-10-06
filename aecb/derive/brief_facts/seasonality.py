"""Seasonality lens: payment delays that come back in the same calendar
months year after year -- a cash-flow rhythm (school fees, annual rent,
seasonal income) that a 24-month worst-status field cannot show -- and how
much of the 36-month window the file actually covers."""

from __future__ import annotations

from . import patterns
from ._common import F_HIST_DATE, F_HIST_DELAY, RISK, SEC_DETAIL

# A calendar month "recurs" when a delayed month falls in it in at least
# MIN_YEARS distinct years. A cluster is 1..MAX_CLUSTER_MONTHS such months;
# more than that is chronic lateness, not a season (the verifier's
# delay_cluster asks the same question about months the model names).
MIN_YEARS = 2
MAX_CLUSTER_MONTHS = 4

# Coverage: distinct reported months in the 36-month window below this is a
# thin history, said in so many words so it is never read as clean.
WINDOW_MONTHS = 36
THIN_MONTHS = 24

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November",
                "December")


def seasonal_delays(ctx, facts, labelled):
    years_by_month, years = patterns.delayed_years(labelled)
    if len(years) < MIN_YEARS:
        return
    recurring = sorted(m for m, ys in years_by_month.items() if len(ys) >= MIN_YEARS)
    if not recurring or len(recurring) > MAX_CLUSTER_MONTHS:
        return
    facts.add(RISK,
              "Seasonal delays: payment delays recur in %s in %d or more years "
              "(%s) and in no other calendar month across the %d years of "
              "reported history. A delay that returns with the calendar points "
              "to a recurring cash-flow squeeze rather than a one-off event."
              % (", ".join(_MONTH_NAMES[m - 1] for m in recurring), MIN_YEARS,
                 "; ".join("%s: %s" % (_MONTH_NAMES[m - 1],
                                       ", ".join(str(y) for y in sorted(years_by_month[m])))
                           for m in recurring),
                 len(years)),
              [F_HIST_DELAY, F_HIST_DATE], SEC_DETAIL)


def coverage(ctx, facts, labelled):
    if not ctx.report_date or not labelled:
        return
    report_month = ctx.report_date.strftime("%Y-%m")
    cutoff = patterns.month_add(report_month, -(WINDOW_MONTHS - 1))
    months = {when for _label, history in labelled for when, _row in history
              if cutoff <= when <= report_month}
    if len(months) >= THIN_MONTHS:
        return
    facts.add(RISK,
              "Thin conduct history: only %d distinct month(s) of the %d-month "
              "window before the report date carry any reported row (earliest "
              "%s). Absent months are unreported, not clean; the conduct "
              "patterns above are tested on what was reported."
              % (len(months), WINDOW_MONTHS, min(months) if months else "none"),
              [F_HIST_DATE], SEC_DETAIL)
