"""Contract and conduct derivation -- the join behind sections 06 and 07.

The critical rule in here concerns coverage. `contractsHistory` is sparse: in the
reference payload one contract has all 36 months and most have between one and
eight. A month with no history row means the bureau reported nothing, which is
NOT the same as reporting zero days past due. Series() therefore yields None for
unreported months, and the renderer maps None to the "not reported" cell rather
than the "current" cell. Absence must never read as good conduct.

Second rule: a contract is closed when ActiveFlag says so, never because
ClosedDate is populated. On an active installment ClosedDate is the scheduled
maturity -- L32755409 in the reference payload is Active with ClosedDate
25 October 2024, and O31681815 is Active with 25 August 2027.
"""

from __future__ import annotations

from .. import dates
from ..loader import CATEGORY_LABEL

WINDOW_MONTHS = 36


def is_closed(contract) -> bool:
    """Closure is ActiveFlag's business alone. See module docstring."""
    return str(contract.get("ActiveFlag") or "").strip().lower() == "closed"


def closed_date(contract):
    """The closure date, or None if the contract is not actually closed."""
    return dates.parse_any(contract.get("ClosedDate")) if is_closed(contract) else None


def _month_key(value):
    parsed = dates.parse_any(value)
    return (parsed.year, parsed.month) if parsed else None


def month_index(report_date, value):
    """Months back from the report date. 0 = report month, 1 = month before."""
    key = _month_key(value)
    if not key or not report_date:
        return None
    return (report_date.year - key[0]) * 12 + (report_date.month - key[1])


def history_by_contract(ctx):
    """{CBContractId: {months_ago: history_row}} for the report window.

    Rows outside the 36-month window are dropped HERE, not at render time:
    months_reported, max_dpd and worst_status all iterate this dict and claim
    to describe the window, so a month-37 row must never reach them.
    """
    grouped = {}
    report_date = ctx.report_date
    for row in ctx.rows("contractsHistory"):
        idx = month_index(report_date, row.get("ReferenceDate"))
        if idx is None or idx < 0 or idx >= WINDOW_MONTHS:
            continue
        grouped.setdefault(row.get("CBContractId"), {})[idx] = row
    return grouped


class Facility:
    """One contract plus its month-indexed conduct series."""

    def __init__(self, ctx, contract, history):
        self.ctx = ctx
        self.raw = contract
        self.history = history or {}          # months_ago -> history row

        self.id = contract.get("CBContractId")
        self.category = contract.get("ContractCategory")
        self.type = contract.get("ContractType")
        self.provider = ctx.provider(contract.get("ProviderNo"))
        self.closed = is_closed(contract)
        self.closed_on = closed_date(contract)
        self.opened = dates.parse_any(contract.get("OpenDate"))

    # --- positions on the 36-month grid ------------------------------------

    @property
    def open_months(self):
        """Months back to the open date, clamped to the window.

        Cells older than this render as pre-open rather than as missing data.
        """
        idx = month_index(self.ctx.report_date, self.opened)
        if idx is None:
            return WINDOW_MONTHS
        return max(0, min(WINDOW_MONTHS, idx))

    @property
    def closed_at_month(self):
        idx = month_index(self.ctx.report_date, self.closed_on) if self.closed_on else None
        return idx if (idx is not None and 0 <= idx < WINDOW_MONTHS) else None

    # --- series -------------------------------------------------------------

    def series(self):
        """Per-month conduct for the window, newest first.

        Each entry is None (nothing reported) or a dict with dpd, status,
        balance, overdue and utilisation.
        """
        out = []
        for m in range(WINDOW_MONTHS):
            row = self.history.get(m)
            if row is None:
                out.append(None)
                continue
            out.append({
                "dpd": _as_days(row.get("DaysPaymentDelay")),
                "status": self.ctx.status(row.get("ContractStatus")),
                "balance": row.get("Balance"),
                "overdue": row.get("OverdueAmount"),
                "utilisation": _as_number(row.get("UtilizationRate")),
            })
        return out

    def utilisation_series(self):
        """Monthly utilisation, newest first. None where unreported.

        Returns None entirely when the contract never reports utilisation --
        installments and services do not carry it.
        """
        values = [(s or {}).get("utilisation") for s in self.series()]
        return values if any(v is not None for v in values) else None

    @property
    def months_reported(self) -> int:
        return len(self.history)

    @property
    def possible_months(self) -> int:
        """Window months this facility was actually open -- the honest
        denominator for its coverage figures. Counting 36 for a loan open
        three months understates its coverage; "3 of 3" and "3 of 36" are
        different claims. Spans the opening month down to the closure month
        (or the report month while open; an undated closure conservatively
        spans to the report month). Clamped to at least months_reported so
        contradictory data can never push coverage past 100%.
        """
        newest = self.closed_at_month if self.closed_at_month is not None else 0
        possible = min(WINDOW_MONTHS, self.open_months - newest + 1)
        return max(possible, self.months_reported, 0)

    @property
    def max_dpd(self):
        """Deepest delay in the window, or None if nothing was reported."""
        seen = [_as_days(row.get("DaysPaymentDelay"))
                for row in self.history.values()]
        seen = [v for v in seen if v is not None]
        return max(seen) if seen else None

    @property
    def final_status(self):
        """Status in the closing month, when the payload reports one.

        None when the closing month carries no history row -- including every
        closure outside the 36-month window. The lifetime WorstStatus is NOT an
        acceptable stand-in: presenting a 2017 arrangement as the status a loan
        closed on in 2019 mislabels a cured contract, so the renderer says
        "not reported" instead.
        """
        if not self.closed:
            return None
        idx = self.closed_at_month
        row = self.history.get(idx) if idx is not None else None
        return self.ctx.status(row.get("ContractStatus")) if row else None

    # --- current-state passthroughs ----------------------------------------

    @property
    def limit(self):
        return self.raw.get("Current_CreditLimit")

    @property
    def balance(self):
        return self.raw.get("Current_Balance")

    @property
    def overdue(self):
        return self.raw.get("Current_OverdueAmount")

    @property
    def utilisation(self):
        return _as_number(self.raw.get("Current_UtilizationRate"))

    @property
    def role_code(self):
        """Role as a letter code; the payload delivers the display text."""
        text = str(self.raw.get("Role") or "").strip()
        mapping = self.ctx.status_codes.get("role_labels") or {}
        return mapping.get(text, "A")

    @property
    def frequency_code(self):
        """Payment frequency as a letter, matched from the long description.

        AECB delivers 'monthly instalments-30 days'; the row label wants 'M'.
        """
        text = str(self.raw.get("PaymentFrequency") or "").strip().lower()
        if not text:
            return None
        for code, meta in (self.ctx.status_codes.get("frequency") or {}).items():
            if code.startswith("_"):
                continue
            if str(meta.get("long", "")).strip().lower() == text:
                return code
        return None

    @property
    def label(self) -> str:
        return self.type or CATEGORY_LABEL.get(self.category, "Facility")

    def __repr__(self):
        return "<Facility %s %s %s>" % (self.id, self.category,
                                        "closed" if self.closed else "open")


def all_facilities(ctx):
    """Every contract as a Facility, with its history attached."""
    grouped = history_by_contract(ctx)
    return [Facility(ctx, c, grouped.get(c.get("CBContractId")))
            for c in ctx.rows("contracts")]


def by_category(facilities):
    """{category letter: [Facility]} preserving payload order."""
    out = {}
    for f in facilities:
        out.setdefault(f.category, []).append(f)
    return out


# --- section 05: the derived worst-status window -----------------------------

def worst_in_window(ctx, months=WINDOW_MONTHS):
    """Deepest delinquency across the whole book in the last `months`.

    Reinstated 9 Sep 2026 (deleted 2 Sep 2026; git history) when RRM settled
    the defaults: EVERY contract counts -- closed ones and every role included,
    because a closure inside the window does not erase the conduct that
    preceded it. Two rules survive from the original implementation:

      * a clean book must not attribute a "worst" to whichever contract
        iterated first -- only a real delay or a below-normal status names a
        facility;
      * a severe STATUS outranks a raw DPD number when naming what happened.

    Evidence comes from two delivered places, because monthly coverage is
    sparse: contractsHistory rows inside the window, plus each contract's
    DATED lifetime worst fields (WorstStatus/WorstStatusDate,
    MaxDaysPaymentDelay/MaxDaysPaymentDelayDate) whenever their date falls
    inside the window -- a dated lifetime event is delivered evidence the
    monthly rows may not carry. A status the config cannot rank is counted in
    `unknown`, never graded and never read as clean.

    Returns None when nothing evidences the window at all (which includes any
    payload without a resolvable report date). Otherwise:

        status              worst RANKED status seen, or None if none was
        max_dpd             deepest delay; 0 only when a zero was reported;
                            None when no delay figure was delivered at all
        facility, when      the naming event -- None on a clean book
        clean               no delay and nothing ranked below normal
        unknown             delivered statuses the config cannot rank
        reported_months     monthly history rows inside the window
        facilities_covered  contracts contributing any evidence
        facilities_total    contracts on file
        months              the window, echoed for the renderer
    """
    facs = all_facilities(ctx)
    report_date = ctx.report_date

    worst_dpd, dpd_fac, dpd_when = None, None, None
    worst_status, st_fac, st_when = None, None, None
    dpd_reported = False
    unknown = 0
    reported = 0
    covered = set()
    lifetime_events = 0

    def consider_dpd(dpd, facility, at):
        nonlocal worst_dpd, dpd_fac, dpd_when, dpd_reported
        if dpd is None:
            return
        dpd_reported = True
        if dpd and (worst_dpd is None or dpd > worst_dpd):
            worst_dpd, dpd_fac, dpd_when = dpd, facility, at

    def consider_status(value, ctx_status, facility, at):
        nonlocal worst_status, st_fac, st_when, unknown
        if value is None:
            return
        if ctx_status["rank"] is None:
            unknown += 1
            return
        if worst_status is None or ctx_status["rank"] < worst_status["rank"]:
            worst_status = ctx_status
            if ctx_status["rank"] < 100:
                st_fac, st_when = facility, at

    for facility in facs:
        for month, row in facility.history.items():
            if month >= months:
                continue
            reported += 1
            covered.add(id(facility))
            at = dates.parse_any(row.get("ReferenceDate"))
            consider_dpd(_as_days(row.get("DaysPaymentDelay")), facility, at)
            consider_status(row.get("ContractStatus"),
                            ctx.status(row.get("ContractStatus")), facility, at)

        raw = facility.raw
        w_at = dates.parse_any(raw.get("WorstStatusDate"))
        idx = month_index(report_date, w_at)
        if idx is not None and 0 <= idx < months and raw.get("WorstStatus") is not None:
            lifetime_events += 1
            covered.add(id(facility))
            consider_status(raw.get("WorstStatus"),
                            ctx.status(raw.get("WorstStatus")), facility, w_at)

        d_at = dates.parse_any(raw.get("MaxDaysPaymentDelayDate"))
        idx = month_index(report_date, d_at)
        if idx is not None and 0 <= idx < months:
            dpd = _as_days(raw.get("MaxDaysPaymentDelay"))
            if dpd is not None:
                lifetime_events += 1
                covered.add(id(facility))
                consider_dpd(dpd, facility, d_at)

    if not reported and not lifetime_events:
        return None

    clean = (not worst_dpd
             and (worst_status is None or worst_status["rank"] >= 100))
    naming_fac = st_fac if st_fac is not None else dpd_fac
    naming_when = st_when if st_fac is not None else dpd_when

    return {
        "status": worst_status,
        "max_dpd": worst_dpd if worst_dpd is not None
                   else (0 if dpd_reported else None),
        "facility": None if clean else naming_fac,
        "when": None if clean else naming_when,
        "clean": clean,
        "unknown": unknown,
        "reported_months": reported,
        "facilities_covered": len(covered),
        "facilities_total": len(facs),
        "months": months,
    }


# --- section 06 aggregates ---------------------------------------------------

def financial_summary(ctx, role="A"):
    """{category: contractsFinancialSummary row} for one role."""
    return dict((r.get("ContractCategory"), r)
                for r in ctx.rows("contractsFinancialSummary")
                if r.get("ContractRole") == role)


def count_summary(ctx, role="A"):
    """{category: contractsSummary row} for one role."""
    return dict((r.get("ContractCategory"), r)
                for r in ctx.rows("contractsSummary")
                if r.get("ContractRole") == role)


def _as_number(value):
    """UtilizationRate arrives as a string ('57'). None stays None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_days(value):
    """DaysPaymentDelay as an int. Anything non-numeric counts as not reported.

    The payload usually delivers an int, but the field is untrusted input that
    is compared and interpolated downstream -- a string here would corrupt both
    the DPD bucketing and the heatmap markup.
    """
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
