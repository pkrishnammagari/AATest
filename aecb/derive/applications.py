"""Applications placed on a split time axis for the applications section.

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
the heatmap's buckets are: what counts as the focus window is a business fact
about the payload, not a drawing detail. report.js only places what it is given.

The shared linear axis in render/svgtime.py is deliberately NOT used. The
income and returns sections share it so their two timelines cannot drift;
this one has a different scale by design and could not share it without
becoming linear again.
"""

from __future__ import annotations

import datetime

from .. import dates
from ..coerce import flag, number

# The window RRM asks about. Also the split point.
FOCUS_DAYS = 90

# Share of the width the focus window takes. The rest holds everything older,
# however long that is.
FOCUS_FRACTION = 0.62

# Marker glyph by contract type, matched on a keyword so a new wording ("Auto
# Loan", "Personal Finance") still lands somewhere sensible. The letters are the
# AECB category set the rest of the page uses -- I / C / S -- so a reader who has
# looked at the facilities or detail section already knows them. An unmatched
# type gets no glyph and says so on hover rather than being filed under a
# category we guessed.
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
# three places holding the same number is how the returns tile mirror got out of step.
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


def _role_letter(ctx, row):
    """The row's role letter; None for main holder or no Role; '?' for a
    delivered role the config cannot read.

    Main holder is the default across the book and earns no mark -- a
    guarantor or co-holder application is the exception that changes whose
    credit hunger the marker records. Same A/C/G vocabulary and the same rule
    as the detail heatmap: an unrecognised role is never assumed to be main
    holder.
    """
    text = str(row.get("Role") or "").strip()
    if not text:
        return None
    letter = (ctx.status_codes.get("role_labels") or {}).get(text)
    if letter is None:
        return "?"
    return letter if letter != "A" else None


def _role_label(ctx, letter):
    if letter == "?":
        return "Unrecognised role"
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
    return in_window_at(ctx.report_date, rows, days)


def in_window_at(anchor, rows, days=FOCUS_DAYS):
    """in_window() against any anchor date -- used to test whether AECB's
    delivered counter was computed at its own data pull date."""
    if not anchor:
        return []
    out = []
    for row in rows:
        when = applied_on(row)
        if when and 0 <= (anchor - when).days < days:
            out.append(row)
    return out


class _SplitAxis:
    """Days-ago to a percentage of the axis width: the focus window linear
    on the right, everything older compressed linearly on the left, the two
    meeting exactly at the FOCUS_DAYS boundary."""

    def __init__(self, oldest_days):
        self.oldest_days = oldest_days
        # When every dated application sits inside the focus window there is
        # no older zone to compress: the focus takes the whole axis, split
        # lands at 0 and the renderer draws no break -- claiming a compressed
        # zone that holds nothing would misstate the axis.
        self.focus_fraction = FOCUS_FRACTION if oldest_days > FOCUS_DAYS else 1.0
        self.split_pct = (1.0 - self.focus_fraction) * 100.0

    def x_of(self, days_ago):
        if days_ago <= FOCUS_DAYS:
            return 100.0 - (days_ago / float(FOCUS_DAYS)) * self.focus_fraction * 100.0
        span = max(1.0, self.oldest_days - FOCUS_DAYS)
        travelled = (days_ago - FOCUS_DAYS) / span
        return (1.0 - travelled) * self.split_pct


def _dated(report_date, rows):
    """[(days ago, date, row)] for rows with a usable date, oldest first."""
    dated = []
    for row in rows:
        when = applied_on(row)
        if when:
            dated.append((max(0, (report_date - when).days), when, row))
    dated.sort(key=lambda item: -item[0])
    return dated


def _assign_lane(x, lane_ends):
    """First lane whose last marker is far enough to the left, capped.

    Lanes stack upward, so a collision lifts the newer marker rather than
    shifting it along the axis, which would put it at the wrong date.
    """
    lane = 0
    while lane < len(lane_ends) and x - lane_ends[lane] < _LANE_GAP:
        lane += 1
    lane = min(lane, MAX_LANES - 1)
    if lane == len(lane_ends):
        lane_ends.append(x)
    else:
        lane_ends[lane] = x
    return lane


def _event(ctx, x, lane, days_ago, when, row):
    phase = ctx.phase(row.get("Phase"))
    event = {
        "x": round(x, 3),
        "lane": lane,
        "days": days_ago,
        "focus": days_ago < FOCUS_DAYS,
        "glyph": _glyph(row.get("ContractType")),
        # Filled = Disbursed (B), hollow = Requested (R). Every other phase --
        # Declined, Rejected, Not taken up, or one the config does not know
        # -- is neither, so it draws dashed and the legend names the phases
        # present.
        "taken": phase["code"] == "B",
        "otherPhase": phase["code"] not in ("B", "R"),
        "phase": phase["label"],
        "provider": ctx.provider(row.get("ProviderNo"))["code"],
        "info": _info(row, when, days_ago, ctx),
    }
    # Exceptions only: a marker gets a dispute ring or a role letter only when
    # the payload delivers one, and the keys are omitted otherwise.
    if flag(row.get("FlagOpenDispute")):
        event["disp"] = True
    role = _role_letter(ctx, row)
    if role:
        event["role"] = role
    return event


def timeline(ctx, rows):
    """Everything the applications chart needs, or None when it cannot be drawn.

    Returns {'events', 'ticks', 'split', 'focusDays', 'lanes', ...}.
    Positions are percentages of the axis width, left to right, oldest to
    newest.
    """
    report_date = ctx.report_date
    if not report_date or not rows:
        return None
    dated = _dated(report_date, rows)
    if not dated:
        return None

    axis = _SplitAxis(dated[0][0])
    events, lane_ends = [], []
    for days_ago, when, row in dated:
        x = axis.x_of(days_ago)
        events.append(_event(ctx, x, _assign_lane(x, lane_ends), days_ago,
                             when, row))

    lanes = len(lane_ends)
    role_letters = sorted(set(e["role"] for e in events if e.get("role")))
    return {
        "events": events,
        "ticks": _ticks(axis, report_date),
        "split": round(axis.split_pct, 3),
        "focusDays": FOCUS_DAYS,
        "lanes": lanes,
        "lanePitch": LANE_PITCH,
        "height": BASE_HEIGHT + max(0, lanes - 1) * LANE_PITCH,
        # For the section's conditional legend -- nothing renders when empty.
        "disputed": any(e.get("disp") for e in events),
        "otherPhase": any(e["otherPhase"] for e in events),
        # The other phases present, for the legend: configured ones in config
        # order (Declined, Rejected, Not taken up), then any unconfigured text.
        "otherPhases": _phase_order(ctx, set(
            e["phase"] for e in events if e["otherPhase"])),
        "roles": [{"code": letter, "label": _role_label(ctx, letter)}
                  for letter in role_letters],
    }


def _phase_order(ctx, labels):
    configured = [label for code, label in
                  (ctx.status_codes.get("application_phases") or {}).items()
                  if not code.startswith("_")]
    return ([label for label in configured if label in labels]
            + sorted(labels - set(configured)))


def _ticks(axis, report_date):
    """Day marks inside the focus window, calendar years outside it.

    The two zones are labelled in different units on purpose: it is the
    clearest way to show that they are not the same scale.
    """
    out = [{"x": round(axis.x_of(0), 3), "label": "report", "lead": True}]
    for days in (30, 60, FOCUS_DAYS):
        if days <= axis.oldest_days:
            out.append({"x": round(axis.x_of(days), 3), "label": "%dd" % days,
                        "lead": days == FOCUS_DAYS})
    if axis.oldest_days > FOCUS_DAYS:
        out.extend(_year_ticks(axis, report_date))
    return out


def _year_ticks(axis, report_date):
    """Year boundaries in the compressed zone, newest first, dropped once they
    would collide -- the zone can hold years in a few percent of the width."""
    oldest = report_date - datetime.timedelta(days=axis.oldest_days)
    placed, out = [], []
    for year in range(report_date.year, oldest.year - 1, -1):
        when = datetime.date(year, 1, 1)
        days = (report_date - when).days
        if not oldest <= when <= report_date or days <= FOCUS_DAYS:
            continue
        x = axis.x_of(days)
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

    # The configured description, whether the payload sent it or the code;
    # an unconfigured phase shows exactly as delivered.
    parts.append("Phase: %s" % ctx.phase(row.get("Phase"))["label"])

    # Delivered-only: role named when it is not main holder (the exception
    # that changes whose application this is), dispute state whenever the
    # bureau delivered the flag -- in either direction.
    role = _role_letter(ctx, row)
    if role == "?":
        parts.append("Role: %s (not a configured role)"
                     % str(row.get("Role")).strip())
    elif role:
        parts.append("Role: %s" % _role_label(ctx, role))
    disputed = flag(row.get("FlagOpenDispute"))
    if disputed is not None:
        parts.append("Open dispute" if disputed else "No dispute")

    amount = _aed(row.get("TotalAmount"))
    limit = _aed(row.get("CreditLimit"))
    if amount:
        parts.append("Amount %s" % amount)
    if limit:
        parts.append("Limit sought %s" % limit)
    installments = row.get("NoOfInstallments")
    if installments:
        parts.append("%s installments" % installments)

    # The application's own numbers -- what someone needs to raise it with
    # AECB or the lender. Delivered-only, like everything on this line.
    if row.get("CBApplicationId"):
        parts.append("AECB application %s" % row.get("CBApplicationId"))
    if row.get("ProviderApplicationNo"):
        parts.append("lender application no. %s" % row.get("ProviderApplicationNo"))

    return " · ".join(parts)


def _aed(value):
    """'AED 12,500', or None when the payload delivers nothing numeric.

    Amounts are untrusted input: a non-numeric value drops out of the hover
    line rather than raising mid-render and taking the report with it.
    """
    amount = number(value)
    if amount is None:
        return None
    return "AED {:,.0f} (currency assumed)".format(amount)
