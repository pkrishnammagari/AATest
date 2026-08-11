"""Cheque and direct-debit return reduction.

Source: paymentOrder. Each row is one returned instrument -- an event, not a
balance -- so the reduction here is thin on purpose: nothing is aggregated,
and any count the screen shows is a count of the rows beneath it.

The summary block also carries return counters (Amount_checks_returned_3mon,
Amount_DD_returned_3mon). This section deliberately does NOT read them: their
three-month window cannot describe a list that reaches back years, and whether
the figure is an amount or a count is unverified. RRM decision, Aug 2026 --
the section is built from paymentOrder alone.

Type and Severity arrive as display text with no vocabulary alongside, so both
resolve through config/returns.json. A Type matching neither known kind is
shown verbatim with a neutral marker; an unknown Severity renders neutral
rather than being guessed into a risk colour.
"""

from __future__ import annotations

from .. import dates


class Return(object):
    """One returned instrument, as delivered."""

    def __init__(self, row, cfg):
        self.type_text = row.get("Type")
        self.kind = _kind(self.type_text, cfg)      # 'cheque' | 'dd' | None

        self.amount = _number(row.get("Amount"))
        self.reason = row.get("Reason")
        self.beneficiary = row.get("BeneficiaryName")
        self.iban = row.get("IBAN")
        self.number = row.get("Number")
        self.provider = row.get("ProviderNo")
        self.date = dates.parse_any(row.get("ReturnDate"))

        self.severity = row.get("Severity")
        tones = cfg.get("severity_tones") or {}
        self.severity_tone = _lookup(tones, self.severity) or "neutral"

        flag = row.get("FlagOpenDispute")
        self.disputed = None if flag is None else bool(flag)

    def __repr__(self):
        return "<Return %s %r on %s>" % (self.kind, self.amount, self.date)


def build(ctx) -> dict:
    """Everything section 05 needs.

    `chart` is 'timeline' when at least one return carries a date, else
    'none'. Records without a date stay in `undated` -- listed, never plotted.

    The configured review window (last N months before the report date) splits
    the dated returns into `recent` and `older`. The window is presentation
    policy, not payload: when the report date cannot be resolved,
    `window_start` is None and no split is claimed -- an "outside the window"
    heading over a window we could not anchor would be an invention.
    """
    cfg = ctx.returns_cfg or {}
    records = [Return(row, cfg) for row in ctx.rows("paymentOrder")]

    # Newest first for the list -- the most recent return is the one an
    # underwriter acts on. Undated rows sink to the end rather than sorting
    # as if they were oldest.
    records.sort(key=lambda r: (r.date is None,
                                -(r.date.toordinal() if r.date else 0)))

    dated = [r for r in records if r.date]
    undated = [r for r in records if not r.date]

    window_months = cfg.get("window_months") or 6
    window_start = (dates.add_months(ctx.report_date, -window_months)
                    if ctx.report_date else None)
    if window_start:
        recent = [r for r in dated if r.date >= window_start]
        older = [r for r in dated if r.date < window_start]
    else:
        recent, older = [], list(dated)

    x0 = min((r.date for r in dated), default=None)
    x1 = ctx.report_date
    if dated and (x1 is None or max(r.date for r in dated) > x1):
        x1 = max(r.date for r in dated)
    # With returns inside the window, the whole window belongs on the axis --
    # the band must not start mid-air because the earliest event is newer
    # than the window's left edge.
    if recent and window_start and window_start < x0:
        x0 = window_start

    return {
        "records": records,
        "dated": dated,
        "undated": undated,
        "recent": recent,
        "older": older,
        "window_months": window_months,
        "window_start": window_start,
        "chart": "timeline" if dated else "none",
        "x0": x0,
        "x1": x1,
    }


def _kind(type_text, cfg):
    """Delivered Type text -> 'cheque' | 'dd' | None.

    Exact match against the configured labels first; containment second, so a
    singular/plural drift ('Bounced Cheque') still lands. Anything else stays
    None and the screen shows the delivered text with a neutral marker.
    """
    if not type_text:
        return None
    text = str(type_text).strip().lower()
    types = cfg.get("types") or {}
    for kind in ("cheque", "dd"):
        label = str(types.get(kind) or "").strip().lower()
        if label and text == label:
            return kind
    if "cheque" in text or "check" in text:
        return "cheque"
    if "direct debit" in text:
        return "dd"
    return None


def _lookup(mapping, key):
    """Case-insensitive, whitespace-tolerant dict lookup for delivered text."""
    if not key:
        return None
    needle = str(key).strip().lower()
    for name, value in mapping.items():
        if name.strip().lower() == needle:
            return value
    return None


def _number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
