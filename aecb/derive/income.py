"""Income and employment reduction.

AECB delivers ONE GrossAnnualIncome per employment row, never a series. What can
honestly be drawn therefore depends entirely on which of the row's dates arrived,
so this module resolves the rows into Records and reports which of four chart
states the payload supports. The section renders that decision; it does not make
it, and it never fills a gap.

Three payload behaviours drive the shape of this:

  * A figure is positioned in time by DateOfLastUpdate. When that is null the
    hire date stands in, and `point_basis` records which was used -- putting a
    salary at the hire date asserts it was the salary AT HIRE, and an inference
    has to stay visible as one.
  * GrossAnnualIncome arrives as 1 on rows a provider did not really fill in.
    A figure between zero and the configured floor is kept and shown, flagged,
    but excluded from the chart scale, where a sentinel flattens every real
    point onto the axis. Exactly zero is a delivered fact and is plotted.
  * Employment carries no current/prior flag. The '(Historical)' suffix on the
    name is the only marker, and DateOfTermination is routinely null even on
    rows that carry it -- so a prior employer usually has a start and no end.
    That is an unknown extent, not an open-ended one.
"""

from __future__ import annotations

import datetime

from .. import dates
from . import identity

class Record(object):
    """One employer, collapsed across the providers that reported it."""

    def __init__(self, entry):
        self.name = entry.value
        self.providers = list(entry.providers)
        self.historical = entry.historical

        self.income = entry.extra.get("GrossAnnualIncome")
        self.income_usable = False       # set by _classify_income
        self.placeholder = False

        self.started = dates.parse_any(entry.extra.get("DateOfEmployment"))
        self.ended = dates.parse_any(entry.extra.get("DateOfTermination"))
        self.updated = None              # latest DateOfLastUpdate, any provider
        self.emp_type = entry.extra.get("EmploymentType")
        self.disputed = None             # True / False / None(not reported)

        self.point_date = None
        self.point_basis = None          # 'updated' | 'started'

    @property
    def plottable(self) -> bool:
        return self.income_usable and self.point_date is not None

    @property
    def dated(self) -> bool:
        """Has any date at all -- otherwise it cannot appear on the timeline."""
        return bool(self.started or self.updated)

    def __repr__(self):
        return "<Record %r income=%r point=%r/%s>" % (
            self.name, self.income, self.point_date, self.point_basis)


def build(ctx) -> dict:
    """Everything section 04 needs, with the chart decision already made.

    Returns a dict; `chart` is one of:

        'trend'  two or more datable figures -- a line can be drawn
        'single' exactly one -- a marker, but no trend
        'spans'  no datable figure but at least one dated employment
        'none'   nothing can be placed in time
    """
    cfg = ctx.income_cfg or {}
    floor = cfg.get("placeholder_floor") or 0

    records = _records(ctx)
    for rec in records:
        _classify_income(rec, floor)
        _place_point(rec)

    points = [r for r in records if r.plottable]
    # Lanes run in date order, earliest at the top, so the timeline reads the
    # way it is drawn. The record list below the chart stays current-first,
    # which is the order an underwriter reads employment in.
    spans = sorted((r for r in records if r.started), key=lambda r: r.started)
    undated = [r for r in records if r.income is not None and not r.plottable]

    if len(points) >= 2:
        chart = "trend"
    elif len(points) == 1:
        chart = "single"
    elif spans:
        chart = "spans"
    else:
        chart = "none"

    x0, x1 = _domain(ctx, points, spans)

    # The scale describes what is DRAWN, so it is set by the plotted points
    # alone. Scaling to a figure that never reaches the chart -- an undated
    # 153,900 against a plotted 18,450 -- pins the one real point to the axis.
    plotted = [r.income for r in points]
    return {
        "records": records,
        "points": sorted(points, key=lambda r: r.point_date),
        "spans": spans,
        "undated": undated,
        "chart": chart,
        "x0": x0,
        "x1": x1,
        "y1": _nice_ceiling(max(plotted)) if plotted else None,
        "latest": _latest(records, points),
        "floor": floor,
        "currency": cfg.get("currency") or "AED",
        "inferred": any(r.point_basis == "started" for r in points),
        "rows": len(ctx.rows("employment")),
    }


# --- resolution -------------------------------------------------------------

def _records(ctx):
    """identity.employers() collapsed into Records, then enriched.

    identity.employers() already dedups by employer name, splits the
    '(Historical)' suffix and keeps the provider set. It merges its extras
    first-non-null-wins, which is wrong for two of the fields here: the update
    date wants the LATEST across providers, and a dispute reported by any one
    provider is a dispute. Both are resolved in a second pass over the raw rows.
    """
    current, prior = identity.employers(ctx)
    records = [Record(e) for e in current] + [Record(e) for e in prior]
    by_key = dict((identity.base_type(r.name).upper(), r) for r in records)

    for row in ctx.rows("employment"):
        rec = by_key.get(identity.base_type(row.get("EmploymentName")).upper())
        if rec is None:
            continue

        updated = dates.parse_any(row.get("DateOfLastUpdate"))
        if updated and (rec.updated is None or updated > rec.updated):
            rec.updated = updated

        # A dispute raised with one provider is still a dispute; only when no
        # provider reported the flag at all does it stay unknown.
        flag = row.get("FlagOpenDispute")
        if flag is not None:
            rec.disputed = bool(rec.disputed) or bool(flag)

    return records


def _classify_income(rec, floor) -> None:
    """Split a delivered figure into usable / placeholder / not reported."""
    if rec.income is None:
        return
    try:
        value = float(rec.income)
    except (TypeError, ValueError):
        rec.income = None
        return

    # Zero is a delivered fact ("reported as zero"), not a placeholder, and
    # reads very differently on a credit screen -- it is plotted.
    if 0 < value < floor:
        rec.placeholder = True
        return
    rec.income_usable = True


def _place_point(rec) -> None:
    """Choose the date that positions this figure, and remember which it was."""
    if rec.updated:
        rec.point_date, rec.point_basis = rec.updated, "updated"
    elif rec.started:
        rec.point_date, rec.point_basis = rec.started, "started"


def _domain(ctx, points, spans):
    """Time axis: earliest thing known, to the report date.

    The report date is a real anchor, so the right-hand edge is never invented.
    Only a domain that collapses to a single day gets widened, and the axis
    tooltip says so.
    """
    starts = [r.point_date for r in points] + [r.started for r in spans]
    starts = [s for s in starts if s]
    if not starts:
        return None, None

    x0 = min(starts)
    ends = [r.ended for r in spans if r.ended]
    if ctx.report_date:
        ends.append(ctx.report_date)
    ends.extend(r.point_date for r in points)
    x1 = max(ends) if ends else x0

    if x1 <= x0:
        x1 = x0 + datetime.timedelta(days=365)
    return x0, x1


def _latest(records, points):
    """The most recent salary the payload supports, and how it was arrived at.

    Preference order, because "latest" is only as good as the dating: the newest
    figure the bureau dated, else the current employer's, else any usable one.
    `dated` says which, so the screen can qualify what it is showing rather than
    implying a currency the payload does not support.
    """
    if points:
        return {"record": max(points, key=lambda r: r.point_date), "dated": True}

    usable = [r for r in records if r.income_usable]
    if not usable:
        return None
    current = [r for r in usable if not r.historical]
    return {"record": (current or usable)[0], "dated": False}


def _nice_ceiling(value):
    """Round an axis top up to 1, 2 or 5 x 10^n so the gridlines read cleanly."""
    value = float(value) * 1.15
    if value <= 0:
        return 1
    step = 10 ** (len(str(int(value))) - 1)
    for mult in (1, 2, 2.5, 5, 10):
        if value <= step * mult:
            return int(step * mult)
    return int(step * 10)
