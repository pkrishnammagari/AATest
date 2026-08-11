"""04 Income & employment.

Sources: employment, incomes.

Two halves over one card: what the bureau delivered, verbatim, on the left; what
can be drawn from it on the right. The left half never depends on the right --
if nothing is drawable the records still stand on their own.

AECB delivers one GrossAnnualIncome per employment row and no series, so the
chart draws what the row's own dates allow. derive/income.py decides which of
four states the payload supports; everything here is rendering.

  trend   two or more datable figures -- points joined
  single  exactly one -- a marker, and a note that a trend needs two
  spans   no datable figure -- employment bars only, no income axis
  none    nothing datable -- no chart, and why in general terms

A figure positioned by DateOfEmployment rather than DateOfLastUpdate is drawn
hollow, because placing a salary at the hire date asserts it was the salary at
hire. The reference payload is entirely in that state.

Nothing on this screen counts the payload's own null fields. Every sentence has
to hold for any payload that lands in the same state -- a note reading "null on
3 of 5 rows" describes one file, not the section, and reads as a defect report
rather than as an underwriting screen.
"""

from __future__ import annotations

from ... import dates
from ...derive import income
from .. import components as c
from .. import svgtime
from .. import tokens

META = {
    "title": "Income &amp; employment",
}

# --- chart geometry (user units; the viewBox scales to its column) ----------
# Width tracks the right half's rendered width at a 1560 viewport, so SVG type
# renders at close to its nominal size instead of being magnified or shrunk.
_W = 520
_PAD_L, _PAD_R, _PAD_T = 46, 14, 16
_INCOME_H = 104        # income plot area, omitted when nothing is plottable
_AXIS_H = 26           # tick label band under the axis
_LANE_H = 30           # one employment lane: name above, bar below
_BAR_H = 11


def render(ctx, meta) -> str:
    model = income.build(ctx)

    if not model["records"]:
        body = c.empty_state(
            "No employment reported",
            "The employment array is empty in this payload. AECB does not say "
            "whether the section was requested and came back empty, or was not "
            "requested at all.")
        return c.section_card(body=body, collapsible=True, closed=True, **meta)

    body = ('<div class="inc-split"><div class="inc-detail">%s%s</div>'
            '<div class="inc-vis">%s</div></div>'
            % (_records(model), _other_income(ctx), _chart_block(ctx, model)))
    return c.section_card(body=body, aside=_latest_label(model),
                          collapsible=True, closed=True, **meta)


# --- the header figure ------------------------------------------------------

def _latest_label(model) -> str:
    """The most recent salary the payload supports, on one line in the header.

    One line because the section loads collapsed: this is the whole of what an
    RRM sees before deciding to open it, so it has to carry the figure, whose it
    is and since when without becoming a block of its own.

    Qualified rather than asserted: 'Latest salary' only when the bureau dated
    the figure. When it dated nothing the heading says the figure is on file
    rather than current, because nothing in the payload establishes that it is.
    """
    latest = model["latest"]
    if not latest:
        placeholder = any(r.placeholder for r in model["records"])
        return ('<div class="inc-latest none"><span class="inc-latest-k">Salary</span>'
                '<span class="inc-latest-v">%s</span></div>'
                % ("No usable figure" if placeholder else "Not reported"))

    rec = latest["record"]
    if latest["dated"]:
        key = "Latest salary"
        basis = ("Dated by the bureau."
                 if rec.point_basis == "updated"
                 else "AECB dated no figure, so this one is placed at its hire "
                      "date.")
    else:
        key = "Salary on file"
        basis = ("AECB dated no figure on any row, so this is the current "
                 "employer's rather than the most recent.")

    # Tenure answers "since when" better than the figure's own date does, and is
    # what an underwriter reads the header for. Where no hire date arrived, the
    # figure's date stands in and says which it is.
    bits = [c.esc(_short(rec.name, 30))]
    if rec.started:
        bits.append("since %s" % dates.fmt_month_year(rec.started))
    elif rec.point_date:
        bits.append("as at %s" % dates.fmt_month_year(rec.point_date))

    providers = ", ".join(rec.providers) or "provider not named"
    return ('<div class="inc-latest" data-info="%s">'
            '<span class="inc-latest-k">%s</span>'
            '<span class="inc-latest-v">%s<small>/yr</small></span>'
            '<span class="inc-latest-s">%s</span></div>'
            % (c.attr("%s, reported by %s. %s" % (rec.name, providers, basis)),
               key, c.aed(rec.income), " · ".join(bits)))


def _short(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- right half: the chart --------------------------------------------------

def _chart_block(ctx, model) -> str:
    head = ('<div class="trend-head">'
            '<span class="trend-title">Income &amp; employment over time</span>'
            '%s</div>' % _provenance(model))

    if model["chart"] == "none":
        return head + _no_chart(model)

    return ('%s%s%s%s%s' % (head, _svg(ctx, model), _legend(model),
                            _chart_note(model), _undated(model)))


def _provenance(model) -> str:
    """delivered when the bureau dated every point; derived when we placed one."""
    if model["chart"] == "none":
        # Nothing is drawn, so there is no provenance to claim. A 'delivered'
        # badge over an empty state would vouch for a chart that is not there.
        return ""
    if model["chart"] == "spans":
        return ('<span class="prov-mark delivered" data-info="Employment dates '
                'as delivered in employment.DateOfEmployment and '
                'DateOfTermination.">delivered</span>')
    if model["inferred"]:
        return ('<span class="prov-mark derived" data-info="Where AECB leaves '
                'DateOfLastUpdate null, a figure is positioned at the hire date '
                'instead. The amount is the bureau\'s; its position on the axis '
                'is ours, and those points are drawn hollow.">derived</span>')
    return ('<span class="prov-mark delivered" data-info="Every figure is '
            'positioned at the DateOfLastUpdate the bureau delivered with '
            'it.">delivered</span>')


def _svg(ctx, model) -> str:
    x0, x1 = model["x0"], model["x1"]
    span_days = float((x1 - x0).days) or 1.0
    inner_w = _W - _PAD_L - _PAD_R

    def sx(day):
        return _PAD_L + (day - x0).days / span_days * inner_w

    has_income = model["chart"] in ("trend", "single")
    income_h = _INCOME_H if has_income else 0
    axis_y = _PAD_T + income_h
    lanes = model["spans"]
    height = axis_y + _AXIS_H + len(lanes) * _LANE_H + 6

    parts = [_defs()]
    if has_income:
        parts.append(_grid(model, axis_y))
    parts.append(_axis(ctx, model, sx, axis_y))

    lane_top = {}
    for i, rec in enumerate(lanes):
        lane_top[id(rec)] = axis_y + _AXIS_H + i * _LANE_H
    for rec in lanes:
        parts.append(_lane(ctx, model, rec, sx, lane_top[id(rec)]))

    if has_income:
        parts.append(_points(model, sx, axis_y, lane_top))

    return ('<svg class="chart-svg inc-svg" viewBox="0 0 %d %d" '
            'preserveAspectRatio="xMidYMid meet" role="img" '
            'aria-label="Employment spans and reported income over time">%s</svg>'
            % (_W, height, "".join(parts)))


def _defs() -> str:
    """A fade for spans whose end the bureau never reported.

    A bar drawn to the axis end would assert the employment ran that long; a bar
    stopping anywhere would assert a leaving date. Fading out asserts neither.
    """
    return ('<defs><linearGradient id="incFade" x1="0" y1="0" x2="1" y2="0">'
            '<stop offset="0" stop-color="%s" stop-opacity=".5"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0"/>'
            '</linearGradient></defs>'
            % (tokens.token("fh-blue"), tokens.token("fh-blue")))


def _grid(model, axis_y) -> str:
    """Three gridlines and their labels: zero, half, top of scale."""
    y1 = model["y1"] or 1
    out = []
    for value in (0, y1 / 2.0, y1):
        y = axis_y - (value / float(y1)) * _INCOME_H
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                   % (_PAD_L, y, _W - _PAD_R, y, tokens.token("dpd-none")))
        out.append('<text x="%.1f" y="%.1f" text-anchor="end" '
                   'font-family="IBM Plex Mono" font-size="8.5" fill="%s">%s</text>'
                   % (_PAD_L - 6, y + 3, tokens.token("ink-4"), _k(value)))
    out.append('<text x="%.1f" y="%.1f" font-family="IBM Plex Mono" '
               'font-size="8" fill="%s">%s /yr</text>'
               % (2, _PAD_T - 5, tokens.token("ink-4"), c.esc(model["currency"])))
    return "".join(out)


def _k(value):
    """Axis label: 20,000 -> '20k'. Scale, not data."""
    if value >= 1000:
        return "%.10gk" % (value / 1000.0)
    return "%.10g" % value


def _axis(ctx, model, sx, axis_y) -> str:
    return svgtime.axis(sx, model["x0"], model["x1"], axis_y,
                        _W, _PAD_L, _PAD_R, _PAD_T, ctx.report_date)


def _lane(ctx, model, rec, sx, top) -> str:
    """One employer's span: name above, bar below."""
    x_start = sx(rec.started)
    bar_y = top + 13

    if rec.ended:
        width = max(3.0, sx(rec.ended) - x_start)
        fill = tokens.token("fh-blue")
        opacity = ' fill-opacity=".55"'
        tail = ""
        note = "%s to %s" % (dates.fmt_month_year(rec.started),
                             dates.fmt_month_year(rec.ended))
    elif rec.historical:
        # Prior employer, no leaving date: the extent is unknown, so the bar
        # fades rather than stopping somewhere or running to the edge.
        width = max(3.0, (_W - _PAD_R) - x_start)
        fill = "url(#incFade)"
        opacity = ""
        tail = ('<text x="%.1f" y="%.1f" font-family="IBM Plex Mono" '
                'font-size="8" fill="%s">end not reported</text>'
                % (min(x_start + width * 0.45, _W - _PAD_R - 80),
                   bar_y + _BAR_H - 2, tokens.token("ink-3")))
        note = ("From %s. DateOfTermination is null, so how long this ran is "
                "not reported." % dates.fmt_month_year(rec.started))
    else:
        width = max(3.0, (_W - _PAD_R) - x_start - 8)
        fill = tokens.token("fh-blue")
        opacity = ' fill-opacity=".55"'
        tip_x = x_start + width
        tail = ('<path d="M %.1f %.1f L %.1f %.1f L %.1f %.1f Z" fill="%s" '
                'fill-opacity=".55"/>'
                % (tip_x, bar_y - 1, tip_x + 8, bar_y + _BAR_H / 2.0,
                   tip_x, bar_y + _BAR_H + 1, tokens.token("fh-blue")))
        note = ("Since %s. No leaving date and not marked historical, so it is "
                "shown running to the report date."
                % dates.fmt_month_year(rec.started))

    # A bar starting near the right edge would push its own label off the
    # canvas, so late lanes label themselves from the right.
    late = x_start > _W * 0.55
    anchor = ' text-anchor="end"' if late else ""
    label_x = (x_start + width) if late else x_start

    return ('<g data-info="%s">'
            '<text x="%.1f" y="%.1f"%s font-size="9.5" font-weight="600" '
            'font-family="IBM Plex Sans" fill="%s">%s</text>'
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%d" rx="3" fill="%s"%s/>'
            '%s</g>'
            % (c.attr("%s — %s" % (rec.name, note)),
               label_x, top + 9, anchor, tokens.token("ink-2"),
               c.esc(_short(rec.name, 34)),
               x_start, bar_y, width, _BAR_H, fill, opacity, tail))


def _points(model, sx, axis_y, lane_top) -> str:
    """Income markers, plus the line when there are two or more."""
    y1 = model["y1"] or 1
    points = model["points"]
    blue = tokens.token("fh-blue")

    def py(value):
        return axis_y - (float(value) / y1) * _INCOME_H

    out = []
    if model["chart"] == "trend":
        path = " ".join("%s %.1f %.1f" % ("M" if i == 0 else "L",
                                          sx(r.point_date), py(r.income))
                        for i, r in enumerate(points))
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="2" '
                   'stroke-linejoin="round"/>' % (path, blue))

    for rec in points:
        x, y = sx(rec.point_date), py(rec.income)

        # A dropped line ties the figure to the employment it came from.
        top = lane_top.get(id(rec))
        if top is not None:
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="%s" stroke-dasharray="2 3"/>'
                       % (x, y + 6, x, top + 13, tokens.token("fh-blue-line")))

        inferred = rec.point_basis == "started"
        if inferred:
            marker = ('<circle cx="%.1f" cy="%.1f" r="5" fill="#fff" '
                      'stroke="%s" stroke-width="2.2"/>' % (x, y, blue))
            basis = ("Positioned at the hire date — AECB left DateOfLastUpdate "
                     "null, so the bureau never dated this figure.")
        else:
            marker = ('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" '
                      'stroke="#fff" stroke-width="1.5"/>' % (x, y, blue))
            basis = "Dated by DateOfLastUpdate."

        out.append('<g data-info="%s">%s<text x="%.1f" y="%.1f" '
                   'text-anchor="middle" font-family="IBM Plex Mono" '
                   'font-size="9" font-weight="600" fill="%s">%s</text></g>'
                   % (c.attr("%s: %s %s /yr, reported by %s. %s"
                             % (rec.name, model["currency"],
                                c.format_number(rec.income),
                                ", ".join(rec.providers) or "an unnamed provider",
                                basis)),
                      marker, x, y - 11, tokens.token("ink-2"),
                      c.format_number(rec.income)))
    return "".join(out)


def _legend(model) -> str:
    items = []
    if model["chart"] in ("trend", "single"):
        items.append('<span class="inc-lg"><i class="dot solid"></i>'
                     'Dated by the bureau</span>')
        if model["inferred"]:
            items.append('<span class="inc-lg"><i class="dot hollow"></i>'
                         'Positioned at the hire date</span>')
    if any(r.historical and not r.ended for r in model["spans"]):
        items.append('<span class="inc-lg"><i class="bar fade"></i>'
                     'End not reported</span>')
    if any(not r.historical and not r.ended for r in model["spans"]):
        items.append('<span class="inc-lg"><i class="bar"></i>Running at the '
                     'report date</span>')
    return ('<div class="inc-legend">%s</div>' % "".join(items)) if items else ""


def _chart_note(model) -> str:
    """Why the chart is as thin as it is. True of any payload in this state."""
    if model["chart"] == "single":
        return ('<div class="inc-note"><b>One figure could be placed in time, '
                'so there is no trend.</b> A trend needs two figures the bureau '
                'has dated.</div>')
    if model["chart"] == "spans":
        return ('<div class="inc-note"><b>Employment only — no income is '
                'plotted.</b> %s.</div>' % _income_reason(model))
    return ""


def _no_chart(model) -> str:
    """Nothing is datable. Says what AECB would have to carry, not what it lacks."""
    return c.empty_state(
        "Nothing can be placed in time",
        "A figure reaches the timeline through DateOfLastUpdate, or failing "
        "that its employment's hire date. Neither arrived, so the employers "
        "and any figures against them are listed alongside instead.")


def _income_reason(model) -> str:
    if any(r.placeholder for r in model["records"]):
        return ("Every figure is missing or below the usable floor of %s %s a "
                "year" % (model["currency"], c.format_number(model["floor"])))
    return "No employment row carries a GrossAnnualIncome"


def _undated(model) -> str:
    """Figures that exist but are not drawn, each saying why.

    'Placeholder' named the classification rather than the consequence. What an
    underwriter needs from this row is which figures the chart is not accounting
    for, and what stopped each one.
    """
    if not model["undated"]:
        return ""
    chips = []
    for rec in model["undated"]:
        if not rec.income_usable:
            why = "not a usable figure"
        else:
            why = "no date to place it"
        chips.append('<span class="inc-chip">%s <b>%s %s</b>'
                     '<span class="inc-why">%s</span></span>'
                     % (c.esc(_short(rec.name, 24)), model["currency"],
                        c.format_number(rec.income), why))
    return ('<div class="inc-tray"><span class="inc-tray-k">Not on the chart</span>'
            '<div class="inc-chips">%s</div></div>' % "".join(chips))


# --- left half: the records -------------------------------------------------

def _records(model) -> str:
    head = ('<div class="trend-head"><span class="trend-title">Employers</span>'
            '<span class="prov-mark delivered" data-info="Every value below is '
            'as AECB delivered it, collapsed only where providers repeated the '
            'same employer.">delivered</span></div>')
    return ('%s<div class="rec-list">%s</div>'
            % (head, "".join(_employer(model, r) for r in model["records"])))


def _employer(model, rec) -> str:
    flag = ('<span class="histflag">Prior</span>' if rec.historical
            else '<span class="emp-cur">Current</span>')

    meta = [_dates_cell(rec), _income_cell(model, rec)]
    if rec.emp_type:
        meta.append(c.esc(rec.emp_type))
    badges = c.prov_badges(rec.providers)
    if badges:
        meta.append('<span class="emp-prov">via %s</span>' % badges)

    return ('<div class="rec"><div class="rec-h"><span class="emp-name">%s</span>'
            '%s%s</div><div class="rec-meta">%s</div></div>'
            % (c.esc(rec.name), flag, _dispute(rec),
               "".join("<span>%s</span>" % m for m in meta)))


def _dispute(rec) -> str:
    """Only rendered when the bureau actually reported the flag.

    Unexercised by the reference payload -- FlagOpenDispute is null on every row
    there -- so silence must not be read as 'no dispute'; it is rendered only
    when there is something to render.
    """
    if rec.disputed is None:
        return ""
    if rec.disputed:
        return c.tag("Open dispute", "bad")
    return c.tag("No dispute")


def _dates_cell(rec) -> str:
    if not rec.started:
        return '<span class="na">Dates not reported</span>'
    since = dates.fmt_month_year(rec.started)
    if rec.ended:
        return "<b>%s</b> to <b>%s</b>" % (since, dates.fmt_month_year(rec.ended))
    if rec.historical:
        return 'From <b>%s</b> · <span class="na">end not reported</span>' % since
    return "Since <b>%s</b>" % since


def _income_cell(model, rec) -> str:
    if rec.income is None:
        return '<span class="na">Income not reported</span>'
    if rec.placeholder:
        # The figure stays on screen -- it is what the bureau sent. The warning
        # is a mark rather than a phrase so the row still reads as a figure and
        # not as a sentence about one.
        return ('<span class="na">%s %s</span> <span class="attn" '
                'data-info="Not a usable figure: below the floor of %s %s a '
                'year set in config/income.json. Delivered by the bureau as-is '
                'and shown unchanged, but kept out of the chart scale.">!</span>'
                % (model["currency"], c.format_number(rec.income),
                   model["currency"], c.format_number(model["floor"])))
    if not float(rec.income):
        return ('<b>%s 0</b>/yr <span class="histflag">reported as zero</span>'
                % model["currency"])
    return "<b>%s</b>/yr" % c.aed(rec.income)


def _other_income(ctx) -> str:
    rows = [r for r in ctx.rows("incomes") if r.get("Source")]
    if not rows:
        return ""
    items = []
    for row in rows:
        amount = row.get("GrossAnnualIncome")
        when = dates.fmt_month_year(row.get("DateOfLastUpdate"), dash="")
        items.append(
            '<div class="oi-line"><span>%s%s</span><span>%s</span></div>'
            % (c.esc(row.get("Source")),
               (' <span class="when">%s · %s</span>'
                % (c.esc(row.get("ProviderNo")), when)) if when else "",
               ("%s/yr" % c.aed(amount)) if amount
               else '<span class="na">Amount not reported</span>'))
    return ('<div class="other-inc"><div class="trend-title" '
            'style="margin-bottom:9px">Other income</div>%s</div>' % "".join(items))
