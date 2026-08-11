"""Contract and conduct derivation -- the join behind sections 07 and 08.

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
    """{CBContractId: {months_ago: history_row}} for the report window."""
    grouped = {}
    report_date = ctx.report_date
    for row in ctx.rows("contractsHistory"):
        idx = month_index(report_date, row.get("ReferenceDate"))
        if idx is None or idx < 0:
            continue
        grouped.setdefault(row.get("CBContractId"), {})[idx] = row
    return grouped


class Facility(object):
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
                "dpd": row.get("DaysPaymentDelay"),
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
    def max_dpd(self):
        """Deepest delay in the window, or None if nothing was reported."""
        seen = [row.get("DaysPaymentDelay") for row in self.history.values()
                if row.get("DaysPaymentDelay") is not None]
        return max(seen) if seen else None

    @property
    def worst_status(self):
        """Lowest-ranked (most severe) status in the window."""
        seen = [self.ctx.status(row.get("ContractStatus"))
                for row in self.history.values() if row.get("ContractStatus")]
        return min(seen, key=lambda s: s["rank"]) if seen else None

    @property
    def final_status(self):
        """Status in the closing month -- what AECB carries for the closure."""
        if not self.closed:
            return None
        idx = self.closed_at_month
        row = self.history.get(idx) if idx is not None else None
        if row:
            return self.ctx.status(row.get("ContractStatus"))
        return self.ctx.status(self.raw.get("WorstStatus"))

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


# --- section 07 aggregates --------------------------------------------------

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


# --- section 06 -------------------------------------------------------------

def worst_in_window(ctx, months):
    """Deepest delinquency across the whole book in the last `months`.

    Returns {'max_dpd', 'status', 'facility', 'when', 'reported_months'} or None
    when no history covers the window at all.

    CURRENTLY UNCALLED, and deliberately kept. Section 05 drove its 36-month
    panel from this until 7 Aug 2026, when that panel became "To be built"
    pending an RRM decision on what the window should measure. Two things in
    here are the expensive part and are worth not rediscovering: a clean book
    must not attribute a "worst" to whichever contract iterated first, and a
    severe STATUS outranks a raw DPD number when naming what happened. Whatever
    the 36-month rule turns out to be, it starts here. Delete it only if that
    decision lands somewhere else entirely.
    """
    worst_dpd, worst_status, holder, when = None, None, None, None
    reported = 0

    for facility in all_facilities(ctx):
        for month, row in facility.history.items():
            if month >= months:
                continue
            reported += 1
            dpd = row.get("DaysPaymentDelay")
            # Strictly greater, and only a real delay counts as an event -- a
            # book of zeroes must not attribute a "worst" to whichever contract
            # happened to be iterated first.
            if dpd and (worst_dpd is None or dpd > worst_dpd):
                worst_dpd, holder = dpd, facility
                when = dates.parse_any(row.get("ReferenceDate"))
            status = ctx.status(row.get("ContractStatus"))
            if status and (worst_status is None or status["rank"] < worst_status["rank"]):
                worst_status = status
                # A severe status outranks a raw DPD number for "what happened".
                if status["rank"] < 100:
                    holder = facility
                    when = dates.parse_any(row.get("ReferenceDate"))

    if not reported:
        return None

    # A clean window has no worst event to point at. Report the delay as 0 (the
    # bureau did report zeroes) but leave facility and date empty, so section 06
    # renders "no delinquency" rather than naming an innocent contract.
    clean = not worst_dpd and (worst_status is None or worst_status["rank"] >= 100)
    return {
        "max_dpd": 0 if worst_dpd is None else worst_dpd,
        "status": worst_status,
        "facility": None if clean else holder,
        "when": None if clean else when,
        "clean": clean,
        "reported_months": reported,
    }
