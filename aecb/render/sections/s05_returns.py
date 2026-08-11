"""05 Cheque & direct-debit returns -- a first-order UAE adverse signal.

Source: paymentOrder only. Each row is one returned instrument. The summary
block's three-month counters are deliberately not read -- their window cannot
describe a list that reaches back years, and whether their figure is an amount
or a count is unverified. RRM decision, Aug 2026: the section is built from
the returns themselves.

Two halves over one card, the same grammar as section 04: the returns as
delivered on the left, the same events on a timeline on the right. Severity
arrives as display text (Single / Multiple / Reported per RRM); its screen
tone is a config mapping, and unknown values render neutral rather than being
guessed into a risk colour.

The distinction this section must keep making: an empty paymentOrder is not
the same as an unchecked one. sectionStatus.ReportType says whether the
bounced-cheque product was pulled, and 'requested, came back clean' is a
positive finding while 'never requested' is a gap in the file.
"""

from __future__ import annotations

from ... import dates
from ...derive import returns
from .. import components as c
from .. import svgtime
from .. import tokens

META = {
    "title": "Cheque &amp; direct-debit returns",
}

_CHEQUE_MARKER = "bounced cheque"

# --- chart geometry (user units; the viewBox scales to its column) ----------
# The canvas height is not fixed: it follows the review window, so the chart
# grows and shrinks with the tiles beside it. Each return inside the window
# gets its own stem lane -- necessary as well as tidy, since the window is a
# narrow slice of an axis that can span years and four events inside it would
# otherwise land on top of one another. Returns OUTSIDE the window do not add
# lanes; they pack into the bottom one, so opening the "Earlier" fold never
# changes the chart.
_W = 520
_PAD_L, _PAD_R, _PAD_T = 16, 14, 16
_AXIS_H = 26           # tick label band under the axis
_STEM_MIN = 30         # shortest stem: clearance between axis and lowest marker
_LANE_MIN = 24         # tightest lane pitch, used only when height runs short
_LANE_MAX = 56         # loosest: beyond this the spread stops reading as a set
_MIN_GAP = 46          # x distance under which two markers would collide
_R = 9                 # marker radius

# The canvas is sized to the "Last 6 months" tiles beside it, so the two halves
# of the card stay in step. These mirror the tile box model in report.css --
# .rec (padding + .rec-t head), .rec-item (one return), .rec-list (the gap) --
# and were measured against it; if those rules change, these follow.
#
# They are now measured in the FLUID state. report.css grows .rec-t, .rec-meta
# and .ret-amt with the page, so a tile is taller with the brief rail closed
# than with it open, and these are the closed values because closed is how the
# page loads -- the same rule _COL_W follows below. Re-measure, do not reason:
# render, then read .rec's rendered height and .rec-item's, at 1560 with the
# rail closed. _TILE_ENTRY is .rec-item's height PLUS its 7px margin-top;
# _TILE_BASE is .rec's height minus one entry. They were 37/57 before the
# fluid scale and measured 38.7/61.6 after it.
_TILE_BASE = 39        # a tile with no entries, i.e. a .rec-none statement
_TILE_ENTRY = 62       # one .rec-item inside a tile
_TILE_GAP = 8          # .rec-list gap between tiles
# The SVG scales to fit its column, so a height in user units renders shorter
# than it reads: this column is 706px wide at the 1560 design viewport against
# a 520-unit viewBox. Converting through it makes the chart and the tiles end
# level there.
#
# It tracks the state the page LOADS in, which is the brief rail closed (see
# the comment on <body> in render/page.py). It was 503.0 while the rail loaded
# open; if that default is ever changed back, this has to move with it, and the
# way to get the new number is to measure .inc-vis's content width rather than
# to reason about it.
#
# It is a design width, not a measurement of the live column, and cannot be
# anything else: the SVG is static, so the width it will be rendered at is not
# knowable here. Opening the brief rail narrows this half to about 503px and
# the chart then scales down and stops short of the tile block. The two halves
# still END level -- .inc-split stretches both cells to the row -- so what shows
# is a short tail on one side, not a misalignment. Making it exact in both
# states would mean generating the chart at runtime, which would move the
# drawing out of Python and away from the payload decisions it is built from.
# Not worth that trade.
_COL_W = 706.0

_TONE_FILL = {"red": "red", "amber": "amber", "neutral": "ink-3"}


def render(ctx, meta) -> str:
    model = returns.build(ctx)
    requested = _section_requested(ctx)

    if not model["records"]:
        return c.section_card(body=_no_records(requested),
                              aside=_aside(model, requested), **meta)

    body = ('<div class="inc-split"><div class="inc-detail">%s</div>'
            '<div class="inc-vis">%s</div></div>'
            % (_records(model), _chart_block(ctx, model)))
    return c.section_card(body=body, aside=_aside(model, requested), **meta)


def _section_requested(ctx):
    """Whether the bounced-cheque product appears in sectionStatus.

    None when sectionStatus is absent entirely -- we then cannot tell.
    """
    rows = ctx.rows("sectionStatus")
    if not rows:
        return None
    for row in rows:
        if _CHEQUE_MARKER in str(row.get("ReportType") or "").lower():
            return True
    return False


def _aside(model, requested):
    count = len(model["records"])
    if count:
        # The window verdict leads: a return this half-year is the acute
        # signal, and its absence over an old adverse history is itself worth
        # the header. Without a resolvable window, fall back to the raw count.
        if model["window_start"] is None:
            return c.tag("%d return%s on file"
                         % (count, "" if count == 1 else "s"), "bad")
        recent = len(model["recent"])
        months = model["window_months"]
        if recent:
            return c.tag("%d return%s · last %dm"
                         % (recent, "" if recent == 1 else "s", months), "bad")
        return c.tag("%d on file · none in %dm" % (count, months), "warn")
    if requested is True:
        return c.tag("Checked · none reported", "good")
    if requested is False:
        return c.tag("Section not requested", "warn")
    return c.tag("Unverified", "warn")


# --- empty states -----------------------------------------------------------

def _no_records(requested) -> str:
    if requested is True:
        return c.empty_state(
            "No returns reported — section was checked",
            "sectionStatus confirms the bounced-cheque product was requested "
            "and AECB returned no records. This is a clean result, not "
            "missing data.")
    if requested is False:
        return c.empty_state(
            "Bounced-cheque section not requested",
            "sectionStatus lists no bounced-cheque product for this enquiry, "
            "so the absence of returns is not evidence of a clean record. "
            "Pull the section before relying on it.")
    return c.empty_state(
        "No return detail delivered",
        "paymentOrder is empty and sectionStatus does not confirm whether the "
        "bounced-cheque product was requested. Treat as unverified.")


# --- left half: the returns as delivered ------------------------------------

def _records(model) -> str:
    """Window first, instrument second: a "Last 6 months" section holding one
    tile per instrument, then a folded "Earlier" section with the same tile
    arrangement inside.

    In the open section an instrument with nothing still gets a dashed tile
    saying so -- for an adverse section that absence is a finding. Inside the
    fold, only instruments with records appear: "none earlier" is not a
    finding, and a placeholder tile behind a fold is clutter nobody asked for.
    """
    badge = ('<span class="prov-mark delivered" data-info="Each entry is one '
             'returned instrument as AECB delivered it in paymentOrder. '
             'Nothing is aggregated, and the window grouping is ours, '
             'anchored to the report date.">delivered</span>')

    # No resolvable window: one flat section, no split claimed.
    if model["window_start"] is None:
        label = ('<div class="ret-grp win"><span>On file</span>%s</div>'
                 % badge)
        return label + _tiles(model["records"], none_text="None reported")

    months = model["window_months"]
    label = ('<div class="ret-grp win"><span>Last %d months</span>%s</div>'
             % (months, badge))
    body = _tiles(model["recent"],
                  none_text="none in the last %d months" % months)
    return label + body + _fold(model)


def _tiles(recs, none_text=None) -> str:
    """One tile per instrument. `none_text` set -> absent instruments still
    render, as a dashed statement tile."""
    tiles = []
    for kind, title in (("cheque", "Bounced cheques"),
                        ("dd", "Unpaid direct debits")):
        sub = [r for r in recs if r.kind == kind]
        if sub:
            tiles.append(_tile(title, sub))
        elif none_text is not None:
            tiles.append('<div class="rec-none"><b>%s</b> · %s</div>'
                         % (title, none_text))
    # Only when the payload delivered a Type outside the two known kinds --
    # those entries keep their delivered text.
    other = [r for r in recs if r.kind is None]
    if other:
        tiles.append(_tile("Other instruments", other, show_type=True))
    return '<div class="rec-list">%s</div>' % "".join(tiles)


def _tile(title, recs, show_type=False) -> str:
    return ('<div class="rec"><div class="rec-t">%s · %d</div>%s</div>'
            % (title, len(recs),
               "".join(_entry(r, show_type) for r in recs)))


def _fold(model) -> str:
    """Everything outside the window, folded until asked for."""
    folded = model["older"] + model["undated"]
    if not folded:
        return ""
    dated = [r for r in folded if r.date]
    if dated and len(dated) < len(folded):
        title = "Earlier &amp; undated"
    elif dated:
        title = "Earlier"
    else:
        title = "Undated"
    return ('<div class="sub-wrap slim sub-closed"><div class="sub-bar">'
            '<span class="sub-bar-t">%s · %d</span>'
            '<button class="sec-toggle" aria-expanded="false">▾</button></div>'
            '%s</div>'
            % (title, len(folded), _tiles(folded)))


def _entry(rec, show_type=False) -> str:
    """One return inside an instrument tile. The tile head names the
    instrument, so the entry spends its weight on what varies: amount, date,
    severity.

    The meta line carries only what the bureau delivered. The reason keeps an
    explicit "not reported" because it bears on the decision; the secondary
    identifiers (beneficiary, IBAN, number) are simply absent when absent --
    three grey "not reported"s per entry was noise dressed as honesty.
    """
    head = [_amount_cell(rec), _date_cell(rec), _severity_tag(rec)]
    if show_type:
        head.insert(0, '<span class="rtype">%s</span>'
                       % c.esc(rec.type_text or "Type not reported"))
    dispute = _dispute(rec)
    if dispute:
        head.append(dispute)

    meta = [_reason_cell(rec)]
    if rec.beneficiary:
        meta.append(c.esc(rec.beneficiary))
    if rec.iban:
        meta.append('<span class="mono" data-info="%s">IBAN %s</span>'
                    % (c.attr("As delivered: " + str(rec.iban)),
                       c.esc(_collapse_mask(rec.iban))))
    if rec.number:
        meta.append('<span class="mono">No. %s</span>' % c.esc(rec.number))
    badges = c.prov_badges([rec.provider] if rec.provider else [])
    if badges:
        meta.append('<span class="emp-prov">via %s</span>' % badges)

    return ('<div class="rec-item"><div class="rec-h">%s</div>'
            '<div class="rec-meta">%s</div></div>'
            % ("".join(head),
               "".join("<span>%s</span>" % m for m in meta)))


def _amount_cell(rec) -> str:
    if rec.amount is None:
        return '<span class="na">Amount not reported</span>'
    return '<b class="ret-amt">%s</b>' % c.aed(rec.amount)


def _date_cell(rec) -> str:
    if not rec.date:
        return '<span class="na">Date not reported</span>'
    return '<span class="ret-date">%s</span>' % dates.fmt_short(rec.date)


def _severity_tag(rec) -> str:
    """Delivered severity text in its configured tone.

    'Reported' and unknown values render neutral -- a risk colour is a claim,
    and neither the payload nor the business has defined one for them yet.
    """
    if not rec.severity:
        return ""
    return ('<span class="sev %s" data-info="Severity as delivered by AECB. '
            'Its colour is a configured reading (config/returns.json), not a '
            'bureau ranking.">%s</span>'
            % (rec.severity_tone, c.esc(rec.severity)))


def _dispute(rec) -> str:
    """Only rendered when the bureau actually reported the flag.

    Unexercised by the reference payload -- FlagOpenDispute is null on every
    row seen so far -- so silence must not be read as 'no dispute'.
    """
    if rec.disputed is None:
        return ""
    if rec.disputed:
        return c.tag("Open dispute", "bad")
    return c.tag("No dispute")


def _reason_cell(rec) -> str:
    if not rec.reason:
        return '<span class="na">Reason not reported</span>'
    return c.esc(rec.reason)


def _collapse_mask(iban) -> str:
    """'*********************9801' -> '…9801'.

    The mask run carries no information; twenty asterisks only push the real
    digits off the line. The verbatim value stays in the hover.
    """
    text = str(iban)
    out = []
    in_mask = False
    for ch in text:
        if ch == "*":
            if not in_mask:
                out.append("…")
                in_mask = True
        else:
            out.append(ch)
            in_mask = False
    return "".join(out)


# --- right half: the timeline -----------------------------------------------

def _chart_block(ctx, model) -> str:
    head = ('<div class="trend-head">'
            '<span class="trend-title">Returns over time</span>'
            '%s</div>' % _provenance(model))

    if model["chart"] == "none":
        return head + c.empty_state(
            "Nothing can be placed in time",
            "No return carries a ReturnDate, so the events are listed "
            "alongside but cannot be drawn on a timeline.")

    return "%s%s%s%s%s" % (head, _svg(ctx, model), _legend(model),
                           _window_note(model), _undated(model))


def _provenance(model) -> str:
    if model["chart"] == "none":
        return ""
    return ('<span class="prov-mark delivered" data-info="Every event sits at '
            'the ReturnDate AECB delivered with it; amounts and severities '
            'are the bureau\'s own.">delivered</span>')


def _svg(ctx, model) -> str:
    x0, x1 = model["x0"], model["x1"]
    span_days = float((x1 - x0).days) or 1.0
    inner_w = _W - _PAD_L - _PAD_R

    def sx(day):
        return _PAD_L + (day - x0).days / span_days * inner_w

    lanes, lane_count = _lanes(model, sx)
    height = _height(model, lane_count)
    axis_y = height - _AXIS_H
    lane_y = _lane_positions(axis_y, lane_count)

    # Band first, so the axis and events draw over it.
    parts = [_window_band(model, sx, axis_y)]
    parts.append(svgtime.axis(sx, x0, x1, axis_y, _W, _PAD_L, _PAD_R, _PAD_T,
                              ctx.report_date))
    # Stems for every event first, then the markers and their labels, so a
    # taller neighbour's stem cannot rule through a label beneath it.
    parts.extend(_stem(rec, sx, axis_y, lane_y[lanes.get(id(rec), 0)])
                 for rec in model["dated"])
    parts.extend(_event(rec, sx, lane_y[lanes.get(id(rec), 0)])
                 for rec in reversed(model["dated"]))

    return ('<svg class="chart-svg inc-svg" viewBox="0 0 %d %d" '
            'preserveAspectRatio="xMidYMid meet" role="img" '
            'aria-label="Returned cheques and direct debits over time">%s</svg>'
            % (_W, height, "".join(parts)))


def _height(model, lane_count) -> int:
    """Canvas height, mirroring the "Last 6 months" tiles beside the chart.

    The tiles are what the chart is a picture of, so the two halves should end
    together. Only the window count feeds this -- opening the "Earlier" fold
    lengthens the record column but must leave the chart exactly as it was.

    A payload with more returns than that height can seat at the tightest lane
    pitch grows the canvas instead of stacking markers on top of each other:
    legibility outranks the alignment.
    """
    tiles = 2 + (1 if any(r.kind is None for r in model["recent"]) else 0)
    block = (_TILE_BASE * tiles + _TILE_GAP * (tiles - 1)
             + _TILE_ENTRY * len(model["recent"]))
    target = block * _W / _COL_W
    floor = (_AXIS_H + _STEM_MIN + _R + _PAD_T
             + (lane_count - 1) * _LANE_MIN)
    return int(round(max(target, floor)))


def _lane_positions(axis_y, lane_count):
    """Marker centre for each lane, spread over the free height and centred.

    Bunching the lanes above the axis and leaving the rest blank would waste
    the room the taller canvas just bought; flinging the top lane to the
    ceiling would stop the markers reading as one set. So the stack takes an
    even pitch up to a limit and sits in the middle of what it is given.
    """
    low = axis_y - _STEM_MIN          # bottom lane
    high = _PAD_T + _R                # highest a marker may sit
    band = max(0.0, low - high)

    if lane_count < 2:
        return [low - band / 2.0]

    pitch = min(_LANE_MAX, band / (lane_count - 1))
    offset = (band - pitch * (lane_count - 1)) / 2.0
    return [low - offset - i * pitch for i in range(lane_count)]


def _lanes(model, sx):
    """Stem lane per return, and how many lanes the canvas needs.

    Returns inside the window take one lane each, oldest at the bottom, so the
    height tracks what the window holds -- which is what the tiles beside the
    chart are showing. Everything earlier packs into the bottom lane and only
    steps up to avoid drawing on top of another marker, so the folded section
    cannot stretch the chart.
    """
    lanes = {}
    for i, rec in enumerate(sorted(model["recent"], key=lambda r: r.date)):
        lanes[id(rec)] = i

    placed = []
    for rec in sorted(model["older"], key=lambda r: r.date):
        x = sx(rec.date)
        lane = 0
        while any(pl == lane and abs(x - px) < _MIN_GAP for px, pl in placed):
            lane += 1
        lanes[id(rec)] = lane
        placed.append((x, lane))

    return lanes, max([1] + [i + 1 for i in lanes.values()])


def _window_band(model, sx, axis_y) -> str:
    """The review-window highlight -- drawn only when it holds something.

    An empty band would visually promise recent activity where there is none;
    with no returns inside the window the band is omitted and _window_note()
    states the absence in words instead.
    """
    if not model["recent"] or not model["window_start"]:
        return ""
    months = model["window_months"]
    bx0 = max(sx(model["window_start"]), _PAD_L)
    bx1 = _W - _PAD_R
    return ('<g data-info="%s">'
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" '
            'fill="%s" fill-opacity=".55"/>'
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-dasharray="4 3"/>'
            '<text x="%.1f" y="%.1f" font-family="IBM Plex Mono" font-size="8" '
            'font-weight="600" fill="%s">◂ last %d months</text></g>'
            % (c.attr("Review window: the last %d months before the report "
                      "date. The events are the bureau's; the window is ours, "
                      "configured in config/returns.json." % months),
               bx0, _PAD_T - 6, bx1 - bx0, axis_y - _PAD_T + 6,
               tokens.token("amber-wash"),
               bx0, _PAD_T - 6, bx0, axis_y, tokens.token("amber"),
               bx0 + 5, _PAD_T + 3, tokens.token("amber-ink"), months))


def _window_note(model) -> str:
    """Said in words when the band cannot honestly be drawn."""
    if model["recent"] or not model["window_start"] or not model["dated"]:
        return ""
    count = len(model["dated"])
    return ('<div class="inc-note"><b>No returns in the last %d months.</b> '
            'The %s shown predate%s the window, which runs back from the '
            'report date.</div>'
            % (model["window_months"],
               "return" if count == 1 else "%d returns" % count,
               "s" if count == 1 else ""))


def _stem(rec, sx, axis_y, y) -> str:
    """Hairline from the axis to the marker.

    Kept to one pixel however tall it grows: a heavier line would start to
    read as a bar, as though the height encoded the amount. It does not --
    the amount is the text beside the marker, and the height is only which
    lane the return was given.
    """
    x = sx(rec.date)
    return ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
            % (x, axis_y, x, y, tokens.token("line-2")))


def _event(rec, sx, y) -> str:
    """One return: a marker on its lane, with the amount beside it."""
    x = sx(rec.date)
    fill = tokens.token(_TONE_FILL.get(rec.severity_tone, "ink-3"))
    glyph = {"cheque": "C", "dd": "D"}.get(rec.kind, "?")

    tip = "%s · %s · %s · severity %s%s" % (
        rec.type_text or "Type not reported",
        ("AED %s" % c.format_number(rec.amount)) if rec.amount is not None
        else "amount not reported",
        dates.fmt_short(rec.date),
        rec.severity or "not reported",
        (" · reported by %s" % rec.provider) if rec.provider else "")

    amount = ""
    if rec.amount is not None:
        text = c.format_number(rec.amount)
        # Beside the marker, not above it. Above works for one lane and fails
        # for several: two returns days apart sit at almost the same x, and
        # the lower one's label lands under the upper one's marker.
        width = svgtime.CHAR_W * len(text)
        if x + _R + 4 + width <= _W - _PAD_R:
            lx, anchor = x + _R + 4, "start"
        else:
            lx, anchor = x - _R - 4, "end"
        amount = ('<text x="%.1f" y="%.1f" text-anchor="%s" '
                  'font-family="IBM Plex Mono" font-size="9" font-weight="600" '
                  'fill="%s">%s</text>'
                  % (lx, y + 3.2, anchor, tokens.token("ink-2"), text))

    return ('<g data-info="%s">'
            '%s<circle cx="%.1f" cy="%.1f" r="%d" fill="%s" '
            'stroke="#fff" stroke-width="2"/>'
            '<text x="%.1f" y="%.1f" text-anchor="middle" '
            'font-family="IBM Plex Sans" font-size="9" font-weight="700" '
            'fill="#fff">%s</text></g>'
            % (c.attr(tip), amount, x, y, _R, fill,
               x, y + 3.2, glyph))


def _legend(model) -> str:
    items = []
    kinds = set(r.kind for r in model["dated"])
    if "cheque" in kinds:
        items.append('<span class="inc-lg"><i class="mk-lg">C</i>Bounced '
                     'cheque</span>')
    if "dd" in kinds:
        items.append('<span class="inc-lg"><i class="mk-lg">D</i>Unpaid '
                     'direct debit</span>')
    if None in kinds:
        items.append('<span class="inc-lg"><i class="mk-lg">?</i>Other '
                     'instrument</span>')

    # Only the tones actually on the chart, so the legend never promises a
    # severity the payload did not deliver.
    tones = [(t, label) for t, label in
             (("red", "Multiple"), ("amber", "Single"), ("neutral", "Other"))
             if any(r.severity_tone == t for r in model["dated"])]
    for tone, _label in tones:
        names = sorted(set(str(r.severity) for r in model["dated"]
                           if r.severity_tone == tone and r.severity))
        if names:
            items.append('<span class="inc-lg"><i class="dot" style='
                         '"background:var(--%s)"></i>%s</span>'
                         % (_TONE_FILL[tone] if tone != "neutral" else "ink-3",
                            c.esc(" / ".join(names))))
    return ('<div class="inc-legend">%s</div>' % "".join(items)) if items else ""


def _undated(model) -> str:
    """Returns with no date: listed beside the chart, never plotted."""
    if not model["undated"]:
        return ""
    chips = []
    for rec in model["undated"]:
        amount = (c.aed(rec.amount) if rec.amount is not None
                  else '<span class="na">amount not reported</span>')
        chips.append('<span class="inc-chip">%s <b>%s</b>'
                     '<span class="inc-why">no date to place it</span></span>'
                     % (c.esc(rec.type_text or "Return"), amount))
    return ('<div class="inc-tray"><span class="inc-tray-k">Not on the '
            'timeline</span><div class="inc-chips">%s</div></div>'
            % "".join(chips))
