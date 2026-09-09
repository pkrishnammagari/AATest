"""Applications placed on a split time axis for section 08.

AECB delivers applications spanning years while the underwriting question is
about the last 90 days. On a linear axis that window is a sliver -- in the
reference payload, 90 days of a 990-day file is 9% of the width, and the recent
cluster that matters most would be crushed into it.

So the axis is SPLIT: the last 90 days take a fixed majority of the width and
everything older is compressed into the rest. Both zones are linear within
themselves and they meet exactly at the 90-day boundary, so a marker never
jumps. This is a deliberate distortion and the section states it on screen --
an axis that is not linear but looks linear is a lie, not a simplification.

The positions are computed HERE rather than in report.js for the same reason
section 07's buckets are: what counts as the focus window is a business fact
about the payload, not a drawing detail. report.js only places what it is given.

The shared linear axis in render/svgtime.py is deliberately NOT used. Sections
03 and 04 share it so their two timelines cannot drift; this one has a
different scale by design and could not share it without becoming linear again.
"""

from __future__ import annotations

import datetime

from .. import dates

# The window RRM asks about. Also the split point.
FOCUS_DAYS = 90

# Share of the width the focus window takes. The rest holds everything older,
# however long that is.
FOCUS_FRACTION = 0.62

# Marker glyph by contract type, matched on a keyword so a new wording ("Auto
# Loan", "Personal Finance") still lands somewhere sensible. The letters are the
# AECB category set the rest of the page uses -- I / C / S -- so a reader who has
# looked at section 06 or 07 already knows them. An unmatched type gets no
# glyph and says so on hover rather than being filed under a category we guessed.
_GLYPHS = (
    ("credit card", "C"),
    ("card", "C"),
    ("communication", "S"),
    ("service", "S"),
    ("loan", "I"),
    ("finance", "I"),
)

# How close two markers may sit before one is lifted to the next lane, as a
# percentage of the axis width. Below this they overlap and the provider labels
# collide -- the reference payload has two applications on the same day.
_LANE_GAP = 3.0

# Vertical pitch between lanes, in px. It has to clear a marker (18) plus its
# provider label (~12) plus the gap between them, or a lower lane's label hides
# behind the marker above it. report.js reads this from the blob rather than
# keeping its own copy -- the section's height is computed from it too, and
# three places holding the same number is how §04's tile mirror got out of step.
LANE_PITCH = 34

# Height of the chart below the first lane's marker: the axis strip, the tick
# labels, the stem and the marker-plus-label stack.
BASE_HEIGHT = 89

# Most lanes the chart will stack. Without a cap the section's height becomes a
# function of how many applications happen to share a date -- a payload with
# fifteen on one day produced a 565px chart, which is not a height any layout
# can absorb. Beyond the cap markers pile onto the top lane and overlap; the
# aside pill still counts them all, and each is its own node with its own hover.
MAX_LANES = 4


def _glyph(contract_type):
    text = str(contract_type or "").strip().lower()
    for needle, letter in _GLYPHS:
        if needle in text:
            return letter
    return None


def _truthy_flag(value) -> bool:
    """Payload booleans arrive as True, 1 or 'Y' variants; None stays False."""
    if value is None:
        return False
    return str(value).strip().upper() in ("1", "Y", "YES", "TRUE")


def _role_letter(ctx, row):
    """The row's role letter, or None for main holder / unmapped text.

    Main holder is the default across the book and earns no mark -- a
    guarantor or co-holder application is the exception that changes whose
    credit hunger the marker records. Same A/C/G vocabulary as section 07.
    """
    text = str(row.get("Role") or "").strip()
    if not text:
        return None
    letter = (ctx.status_codes.get("role_labels") or {}).get(text, "A")
    return letter if letter != "A" else None


def _role_label(ctx, letter):
    meta = (ctx.status_codes.get("roles") or {}).get(letter) or {}
    return meta.get("label", letter)


def applied_on(row):
    """The date an application is placed at.

    LastUpdateDate is AECB's movement date for the application; DateOfLastUpdate
    is the record's own. They agree on every row of the reference payload, and
    the first is the one that means "when this application moved".
    """
    return dates.parse_any(row.get("LastUpdateDate")
                           or row.get("DateOfLastUpdate"))


def in_window(ctx, rows, days=FOCUS_DAYS):
    """Applications inside the window, counted the way AECB counts them.

    STRICTLY less than `days` old. That is not arbitrary: on the reference
    payload it is what reconciles the rows with the delivered
    contractsTotalSummary.Applications90D exactly (five, not six -- one
    application sits on day 90 itself). An inclusive bound made the section
    report a conflict with the bureau that was our own off-by-one.
    """
    report_date = ctx.report_date
    if not report_date:
        return []
    out = []
    for row in rows:
        when = applied_on(row)
        if when and 0 <= (report_date - when).days < days:
            out.append(row)
    return out


def timeline(ctx, rows):
    """Everything section 08's chart needs, or None when it cannot be drawn.

    Returns {'events', 'ticks', 'split', 'focusDays', 'lanes'}. Positions are
    percentages of the axis width, left to right, oldest to newest.
    """
    report_date = ctx.report_date
    if not report_date or not rows:
        return None

    dated = []
    for row in rows:
        when = applied_on(row)
        if when:
            dated.append((max(0, (report_date - when).days), when, row))
    if not dated:
        return None

    dated.sort(key=lambda item: -item[0])          # oldest first
    oldest_days = dated[0][0]

    # When every dated application sits inside the focus window there is no
    # older zone to compress: the focus takes the whole axis, split lands at 0
    # and the renderer draws no break -- claiming a compressed zone that holds
    # nothing would misstate the axis.
    focus_fraction = FOCUS_FRACTION if oldest_days > FOCUS_DAYS else 1.0
    split_pct = (1.0 - focus_fraction) * 100.0

    def x_of(days_ago):
        """Days-ago to a percentage. Piecewise, continuous at the boundary."""
        if days_ago <= FOCUS_DAYS:
            return 100.0 - (days_ago / float(FOCUS_DAYS)) * focus_fraction * 100.0
        span = max(1.0, oldest_days - FOCUS_DAYS)
        travelled = (days_ago - FOCUS_DAYS) / span
        return (1.0 - travelled) * split_pct

    events, lane_ends = [], []
    for days_ago, when, row in dated:
        x = x_of(days_ago)

        # First lane whose last marker is far enough to the left. Lanes stack
        # upward, so a collision lifts the newer marker rather than shifting it
        # along the axis, which would put it at the wrong date.
        lane = 0
        while lane < len(lane_ends) and x - lane_ends[lane] < _LANE_GAP:
            lane += 1
        if lane >= MAX_LANES:
            lane = MAX_LANES - 1
        if lane == len(lane_ends):
            lane_ends.append(x)
        else:
            lane_ends[lane] = x

        phase = str(row.get("Phase") or "").strip()
        event = {
            "x": round(x, 3),
            "lane": lane,
            "days": days_ago,
            "focus": days_ago < FOCUS_DAYS,
            "glyph": _glyph(row.get("ContractType")),
            # Two states are all AECB delivers here, so they are encoded as
            # filled and hollow rather than pilled with invented wording.
            "taken": phase.lower() == "disbursed",
            "provider": ctx.provider(row.get("ProviderNo"))["code"],
            "info": _info(row, when, days_ago, ctx),
        }
        # Exceptions only: a marker gets a dispute ring or a role letter only
        # when the payload delivers one, and the keys are omitted otherwise.
        if _truthy_flag(row.get("FlagOpenDispute")):
            event["disp"] = True
        role = _role_letter(ctx, row)
        if role:
            event["role"] = role
        events.append(event)

    lanes = len(lane_ends)
    role_letters = sorted(set(e["role"] for e in events if e.get("role")))
    return {
        "events": events,
        "ticks": _ticks(ctx, x_of, oldest_days, report_date),
        "split": round(split_pct, 3),
        "focusDays": FOCUS_DAYS,
        "lanes": lanes,
        "lanePitch": LANE_PITCH,
        "height": BASE_HEIGHT + max(0, lanes - 1) * LANE_PITCH,
        # For the section's conditional legend -- nothing renders when empty.
        "disputed": any(e.get("disp") for e in events),
        "roles": [{"code": letter, "label": _role_label(ctx, letter)}
                  for letter in role_letters],
    }


def _ticks(ctx, x_of, oldest_days, report_date):
    """Day marks inside the focus window, calendar years outside it.

    The two zones are labelled in different units on purpose: it is the
    clearest way to show that they are not the same scale.
    """
    out = [{"x": round(x_of(0), 3), "label": "report", "lead": True}]
    for days in (30, 60, FOCUS_DAYS):
        if days <= oldest_days:
            out.append({"x": round(x_of(days), 3), "label": "%dd" % days,
                        "lead": days == FOCUS_DAYS})

    # Year boundaries in the compressed zone, newest first, dropped once they
    # would collide -- the zone can hold years in a few percent of the width.
    if oldest_days > FOCUS_DAYS:
        oldest = report_date - datetime.timedelta(days=oldest_days)
        placed = []
        for year in range(report_date.year, oldest.year - 1, -1):
            when = datetime.date(year, 1, 1)
            if not (oldest <= when <= report_date):
                continue
            days = (report_date - when).days
            if days <= FOCUS_DAYS:
                continue
            x = x_of(days)
            if any(abs(x - p) < 7.0 for p in placed):
                continue
            placed.append(x)
            out.append({"x": round(x, 3), "label": str(year), "lead": False})
    return out


def _info(row, when, days_ago, ctx):
    """The hover line. Everything the row carries and nothing it does not."""
    parts = ["%s · %s" % (dates.fmt_short(when),
                          "today" if days_ago == 0 else "%d days ago" % days_ago)]

    kind = str(row.get("ContractType") or "").strip()
    parts.append(kind or "Contract type not reported")

    provider = ctx.provider(row.get("ProviderNo"))
    parts.append("Provider %s" % provider["name"])

    phase = str(row.get("Phase") or "").strip()
    parts.append("Phase: %s" % (phase or "not reported"))

    # Delivered-only: role named when it is not main holder (the exception
    # that changes whose application this is), dispute state whenever the
    # bureau delivered the flag -- in either direction.
    role = _role_letter(ctx, row)
    if role:
        parts.append("Role: %s" % _role_label(ctx, role))
    flag = row.get("FlagOpenDispute")
    if flag is not None:
        parts.append("Open dispute" if _truthy_flag(flag) else "No dispute")

    amount = _aed(row.get("TotalAmount"))
    limit = _aed(row.get("CreditLimit"))
    if amount:
        parts.append("Amount %s" % amount)
    if limit:
        parts.append("Limit sought %s" % limit)
    installments = row.get("NoOfInstallments")
    if installments:
        parts.append("%s installments" % installments)

    return " · ".join(parts)


def _aed(value):
    """'AED 12,500', or None when the payload delivers nothing numeric.

    Amounts are untrusted input: a value like '12,500' must drop out of the
    hover line, not raise mid-render and take the whole report with it.
    """
    try:
        return "AED {:,.0f}".format(float(value))
    except (TypeError, ValueError):
        return None
