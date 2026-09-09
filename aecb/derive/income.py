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

class Record:
    """One employer, collapsed across the providers that reported it."""

    def __init__(self, entry):
        self.name = entry.value
        self.providers = list(entry.providers)
        self.historical = entry.historical

        self.income = entry.extra.get("GrossAnnualIncome")
        self.income_usable = False       # set by _classify_income
        self.placeholder = False
        self.income_others = []          # (value, provider) figures outranked
                                         # by the shown one -- see _resolve_income

        self.started = dates.parse_any(entry.extra.get("DateOfEmployment"))
        self.ended = dates.parse_any(entry.extra.get("DateOfTermination"))
        self.updated = None              # latest DateOfLastUpdate, any provider
        self.emp_type = entry.extra.get("EmploymentType")
        self.disputed = None             # True / False / None(not reported)

        self.point_date = None
        self.point_basis = None          # 'updated' | 'started'
        # Does DateOfLastUpdate still vouch for this row at the report date?
        # True / False / None(no update date arrived -- unknown, NOT unconfirmed)
        self.confirmed = None

    @property
    def plottable(self) -> bool:
        return self.income_usable and self.point_date is not None

    @property
    def stale(self) -> bool:
        """Positively known to be unrefreshed. Absence of an update date is not.

        Only ever True when DateOfLastUpdate actually arrived and fell outside
        the configured window, so a payload that omits the field entirely -- as
        both current ones do on every employment row -- never trips this.
        """
        return self.confirmed is False

    @property
    def contradictory(self) -> bool:
        """Ends before it starts. Impossible, so nothing may be drawn from it.

        Left visible as two dates and a mark rather than absorbed: the bar
        drawing clamps its width to a 3px minimum, which would render this as a
        plausible-looking short job instead of the data error it is.
        """
        return bool(self.started and self.ended and self.ended < self.started)

    @property
    def ongoing(self) -> bool:
        """Eligible to be the current job.

        A '(Historical)' name or a DateOfTermination each say the bureau
        considers this employment finished, and either one disqualifies it
        however recently it started -- a job that has ended cannot be the
        current one.
        """
        return not self.historical and self.ended is None

    @property
    def dated(self) -> bool:
        """Has any date at all -- otherwise it cannot appear on the timeline."""
        return bool(self.started or self.updated)

    def __repr__(self):
        return "<Record %r income=%r point=%r/%s>" % (
            self.name, self.income, self.point_date, self.point_basis)


def build(ctx) -> dict:
    """Everything section 03 needs, with the chart decision already made.

    Returns a dict; `chart` is one of:

        'trend'  two or more datable figures -- a line can be drawn
        'single' exactly one -- a marker, but no trend
        'spans'  no datable figure but at least one dated employment
        'none'   nothing can be placed in time
    """
    cfg = ctx.income_cfg or {}
    floor = cfg.get("placeholder_floor") or 0

    records = _order(_records(ctx))
    for rec in records:
        _classify_income(rec, floor)
        _place_point(rec)
        _confirm(rec, ctx.report_date, cfg.get("confirmation_window_months"))

    current = _current(records)
    points = [r for r in records if r.plottable]
    # Lanes run in date order, earliest at the top, so the timeline reads the
    # way it is drawn. The record list below the chart stays current-first,
    # which is the order an underwriter reads employment in.
    #
    # A row whose end precedes its start is excluded outright: there is no
    # honest bar to draw for it, and the list still shows both dates.
    spans = sorted((r for r in records if r.started and not r.contradictory),
                   key=lambda r: r.started)
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
    # Coerced here because rec.income keeps the delivered value verbatim (the
    # renderer prints it), while max() needs comparable numbers -- a payload
    # mixing '18450' and 18450 must not compare strings lexicographically.
    plotted = [float(r.income) for r in points]
    return {
        "records": records,
        "current": current,
        "points": sorted(points, key=lambda r: r.point_date),
        "spans": spans,
        "undated": undated,
        "chart": chart,
        "x0": x0,
        "x1": x1,
        "y1": _nice_ceiling(max(plotted)) if plotted else None,
        "latest": _latest(records, points, current),
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
    first-non-null-wins, which is wrong for every field that matters here, so
    all of them are resolved in a second pass over the raw rows:

      DateOfLastUpdate    LATEST across providers -- freshness is the newest
                          time anyone vouched for the row.
      FlagOpenDispute     a dispute raised with any one provider is a dispute.
      DateOfEmployment    EARLIEST -- the job started once, and the earliest
                          date any provider reports is the best evidence of
                          when. A later start is a provider that only began
                          reporting mid-employment.
      DateOfTermination   LATEST -- if one provider says it ended in 2022 and
                          another in 2023, the job demonstrably ran to 2023.
      GrossAnnualIncome   the MOST RECENTLY REFRESHED row's figure, with rows
                          not marked historical outranking superseded ones and
                          dated rows outranking undated -- see _resolve_income.
                          Figures the winner outranks are kept, not dropped:
                          the row carries a disagreement marker naming them.

    Left to first-non-null, all five answer to payload order instead, which is
    to say to nothing.
    """
    current, prior = identity.employers(ctx)
    records = [Record(e) for e in current] + [Record(e) for e in prior]
    by_key = dict((identity.base_type(r.name).upper(), r) for r in records)

    candidates = {}
    for order, row in enumerate(ctx.rows("employment")):
        rec = by_key.get(identity.base_type(row.get("EmploymentName")).upper())
        if rec is None:
            continue

        updated = dates.parse_any(row.get("DateOfLastUpdate"))
        if updated and (rec.updated is None or updated > rec.updated):
            rec.updated = updated

        started = dates.parse_any(row.get("DateOfEmployment"))
        if started and (rec.started is None or started < rec.started):
            rec.started = started

        ended = dates.parse_any(row.get("DateOfTermination"))
        if ended and (rec.ended is None or ended > rec.ended):
            rec.ended = ended

        # A dispute raised with one provider is still a dispute; only when no
        # provider reported the flag at all does it stay unknown.
        flag = row.get("FlagOpenDispute")
        if flag is not None:
            rec.disputed = bool(rec.disputed) or bool(flag)

        if row.get("GrossAnnualIncome") is not None:
            candidates.setdefault(id(rec), []).append((
                not identity.is_historical(row.get("EmploymentName")),
                updated,
                -order,
                row.get("GrossAnnualIncome"),
                row.get("ProviderNo"),
            ))

    for rec in records:
        _resolve_income(rec, candidates.get(id(rec)) or [])

    return records


def _resolve_income(rec, cands) -> None:
    """Pick the figure shown for an employer; keep what it outranks visible.

    Providers repeat an employer, and their figures can disagree. The shown
    figure is the one with the strongest claim to be current: a row not marked
    historical beats a superseded one, a dated row beats an undated one, a
    newer refresh beats an older one, and payload order settles what remains.
    Every outranked figure that DIFFERS lands in rec.income_others -- the
    renderer marks the disagreement and names them, because dropping a
    delivered figure is information loss and hiding the disagreement would
    present a contested number as settled.
    """
    if not cands:
        return

    def rank(cand):
        current_row, updated, order, _value, _provider = cand
        return (current_row, updated is not None,
                updated or datetime.date.min, order)

    def num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    ordered = sorted(cands, key=rank, reverse=True)
    best = ordered[0]
    rec.income = best[3]

    chosen = num(best[3])
    seen = set()
    for cand in ordered[1:]:
        value = num(cand[3])
        differs = (str(cand[3]) != str(best[3]) if value is None or chosen is None
                   else value != chosen)
        key = value if value is not None else str(cand[3])
        if differs and key not in seen:
            seen.add(key)
            rec.income_others.append((cand[3], cand[4]))


def _classify_income(rec, floor) -> None:
    """Split a delivered figure into usable / placeholder / not reported."""
    if rec.income is None:
        return
    try:
        value = float(rec.income)
    except (TypeError, ValueError):
        rec.income = None
        return

    # A negative annual income is not a plottable fact. It stays visible in
    # the record list (undated tail) but must not set the chart scale.
    if value < 0:
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


def _confirm(rec, report_date, window_months) -> None:
    """Does DateOfLastUpdate still vouch for this row at the report date?

    This is the ONLY job the update date has in deciding employment status, and
    it is a qualifying one: it can say a claim is unrefreshed, never that it
    holds. Which employer is current is settled by the start dates alone --
    otherwise any bank re-touching a 2019 record would promote it over a 2025
    job (see _current).

    Stays None when no update date arrived, or when no window is configured:
    unknown is not the same as unconfirmed, and only a delivered date can make
    the difference.
    """
    if rec.updated is None or not report_date or not window_months:
        return

    # A record last touched before the job it describes even began cannot be
    # vouching for that job.
    if rec.started and rec.updated < rec.started:
        rec.confirmed = False
        return

    # dates.months_between is the ONE month-arithmetic in this codebase (it
    # backs off until the day-of-month comes round, so "12 months" means
    # twelve whole months). A private variant here once made the window up to
    # a month looser than the configured value.
    months = dates.months_between(rec.updated, report_date)
    rec.confirmed = months is not None and months <= window_months


def _order(records):
    """Display order: most recent job first, rows with no job date last.

    Employment reads newest-job-first, the way an underwriter asks the question.
    The anchor ladder is start, else END, else nothing -- a row that carries a
    termination but no hire date is still placeable in time, and dropping it in
    with the undated rows would throw away the one date it does have.

    DateOfLastUpdate is deliberately NOT an anchor. It measures when a provider
    last touched the record, not when the job ran, and letting it rank against
    real job dates is the confusion this whole module now separates. It orders
    only WITHIN the undated tail, where there is nothing better and the rows
    are otherwise indistinguishable.

    sorted() is stable, so rows with nothing at all keep the bureau's own order
    -- three of the reference payload's five employers are exactly this.

    The timeline lanes are NOT reordered with this; they stay earliest-at-top,
    which is how a span chart reads. See build().
    """
    def key(rec):
        anchor = rec.started or rec.ended
        if anchor:
            return (0, -anchor.toordinal(), 0)
        return (1, 0, -rec.updated.toordinal() if rec.updated else 0)

    return sorted(records, key=key)


def _current(records):
    """The employer the subject works for now.

    The most recent start date wins, among the jobs the bureau has not marked
    finished. AECB delivers no current/prior flag on employment, so the newest
    start is the only evidence available for which job is the live one --
    hence the whole of the rule.

    Rows are filtered by `ongoing` FIRST and ranked second: a job that carries
    an end date is out however recently it began, so a short recent stint that
    has already finished cannot displace a long-running current one.

    None when nothing qualifies -- every employer finished, or no start date
    arrived at all. Nothing is promoted on absence of evidence.

    Two employers starting the same day are separated by whichever record was
    refreshed more recently, and failing that by the bureau's own order --
    `records` arrives from _order(), whose sort is stable, and max() returns the
    first of equals. Freshness breaks a tie it is not allowed to create.
    """
    dated = [r for r in records if r.ongoing and r.started]
    if not dated:
        return None
    return max(dated, key=lambda r: (r.started, r.updated or datetime.date.min))


def _latest(records, points, current):
    """The header figure, and what it is a figure FOR.

    It follows the CURRENT employer rather than the newest figure on file:
    naming a salary while a different employer is the live one answers a
    question nobody asked. Where the current employer reports no usable figure
    the header says so, rather than borrowing another employer's number to
    fill the slot.

    Only when no employer qualifies as current does it fall back to the newest
    figure the bureau dated, and then to any usable one. `basis` records which
    of the three happened, so the screen can qualify what it is showing instead
    of implying a currency the payload does not support.
    """
    if current is not None:
        return {"record": current, "basis": "current",
                "dated": current.point_basis == "updated"}

    if points:
        return {"record": max(points, key=lambda r: r.point_date),
                "basis": "newest", "dated": True}

    usable = [r for r in records if r.income_usable]
    if not usable:
        return None
    ongoing = [r for r in usable if r.ongoing]
    return {"record": (ongoing or usable)[0], "basis": "undated", "dated": False}


def _nice_ceiling(value):
    """Round an axis top up to 1, 2 or 5 x 10^n so the gridlines read cleanly."""
    value = float(value) * 1.15
    if value <= 0:
        return 1
    step = 10 ** (len(str(int(value))) - 1)
    for mult in (1, 2, 2.5, 5):
        if value <= step * mult:
            return int(step * mult)
    return int(step * 10)
