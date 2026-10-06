"""Clean-up lens: contracts closed and overdue amounts cleared in the months
just before the enquiry. Tidying the file before applying is rational
behaviour; it is also exactly what the enquiry-date snapshot hides."""

from __future__ import annotations

from ...derive.facilities import closed_date
from . import patterns
from ._common import F_HIST_DATE, RISK, SEC_FACILITIES, contract_label, month

# Months before the report date in which a closure or a clearance counts as
# pre-enquiry clean-up (the verifier's closure_before_enquiry takes the
# window the model names; this lens uses the team's 1-3 month reading).
WINDOW_MONTHS = 3


def pre_enquiry_cleanup(ctx, facts, labelled):
    if not ctx.report_date:
        return
    report_month = ctx.report_date.strftime("%Y-%m")
    cutoff = patterns.month_add(report_month, -WINDOW_MONTHS)
    closed = ["%s closed %s" % (contract_label(ctx, c), month(c.get("ClosedDate")))
              for c in ctx.rows("contracts")
              if closed_date(c) and cutoff <= month(c.get("ClosedDate")) <= report_month]
    cleared = ["%s overdue AED %s (%s) cleared to 0 by %s"
               % (label, "{:,}".format(int(amount)) if amount == int(amount) else amount,
                  last, when)
               for label, amount, last, when in patterns.clearances(labelled, cutoff)]
    if not closed and not cleared:
        return
    facts.add(RISK,
              "Pre-enquiry clean-up in the %d months before the report date %s: "
              "%s. Closures and clearances this close to an application can be "
              "the applicant tidying the file; ask what was repaid with what."
              % (WINDOW_MONTHS, report_month, "; ".join(closed + cleared)),
              ["contracts[].ClosedDate", "contractsHistory[].OverdueAmount",
               F_HIST_DATE],
              SEC_FACILITIES)
