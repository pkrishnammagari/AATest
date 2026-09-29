"""Absence lens: what the file does NOT establish. Missing corroboration and
reporting gaps are stated plainly so the model can carry them into findings
and the unknowns list -- an empty heatmap cell must never read as clean."""

from __future__ import annotations

from ... import dates
from ...coerce import number
from .. import income
from ._common import ABSENCE, F_HIST_DATE, SEC_DETAIL, SEC_INCOME, fmt, text


def reporting_gaps(ctx, facts, labelled_active):
    """Months the bureau did NOT report on active contracts, named as blind
    spots -- above all the months nearest the report date, which is exactly
    where the freshest conduct should be."""
    if not ctx.report_date:
        return
    report_month = ctx.report_date.strftime("%Y-%m")
    stale = []
    for label, history in labelled_active:
        last_month = history[-1][0]
        gap = dates.months_between(last_month + "-01", ctx.report_date)
        if gap is not None and gap >= 2:
            stale.append("%s last reported %s, %d month(s) before the "
                         "report month %s" % (label, last_month, gap,
                                              report_month))
    if stale:
        facts.add(ABSENCE,
                  "Reporting blind spots on active contracts (absent months "
                  "are unreported, not clean): %s." % "; ".join(stale),
                  [F_HIST_DATE, "contracts[].ActiveFlag",
                   "sectionStatus[].Last EnquiryDate", "score.DataPullDate"],
                  SEC_DETAIL)


def _incomes_row_note(ctx) -> str:
    rows = ctx.rows("incomes")
    if not rows:
        return "no rows in the incomes array"
    row = rows[0]
    which = ("the single incomes row" if len(rows) == 1
             else "the first of %d incomes rows" % len(rows))
    if number(row.get("GrossAnnualIncome")):
        return ("%s reports AED %s (source '%s')"
                % (which, fmt(row.get("GrossAnnualIncome")),
                   text(row.get("Source") or "?")))
    age = dates.months_between(row.get("DateOfLastUpdate"), ctx.report_date)
    return ("%s carries source '%s'%s and no usable amount"
            % (which, text(row.get("Source") or "?"),
               (", last updated %d month(s) before the report date" % age)
               if age is not None else ""))


def income_corroboration(ctx, facts):
    """Can this file support an income figure at all? Reuses the same income
    resolution as the income section, so 'no usable figure' here means exactly
    what the income section shows."""
    story = income.build(ctx)
    latest = story["latest"]
    if latest is None or not latest["record"].income_usable:
        facts.add(ABSENCE,
                  "The file cannot corroborate current income: %s, and no "
                  "employment record carries a usable figure for a current "
                  "employer. Income evidence must come from outside this "
                  "report." % _incomes_row_note(ctx),
                  ["incomes[].Source", "incomes[].DateOfLastUpdate",
                   "employment[].GrossAnnualIncome"],
                  SEC_INCOME)

    if story["current"] is None:
        facts.add(ABSENCE,
                  "No employment record qualifies as visibly current -- every "
                  "row is terminated, marked historical, or carries no start "
                  "date. The file does not establish a present employer.",
                  ["employment[].DateOfEmployment",
                   "employment[].DateOfTermination"],
                  SEC_INCOME)
