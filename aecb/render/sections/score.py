"""Score & bureau history.

Sources: score.DataIndex (the number), score.FHScoreBand, score.DataRange
(AECB band letter), score.ErrorNumber / ErrorDescription (why no score came
back), contractsTotalSummary.OldestContractOpenDate.

IMPORTANT -- the delivered FH band is authoritative. The chip shows what AECB
sent in FHScoreBand; the dial is only configured geometry from
config/bands.json. Do not "tidy" this by deriving the band from the number:
whenever the cut-offs and the bureau disagree, computing it would silently
contradict the bureau. When the two disagree the dial carries an amber '!'
saying so -- the delivered band still wins, the config gets checked.

Layout: a half-width card beside the worst-statuses section. A dial (a
120-degree arc) -- FH band zones, marker at the score, the score in the
middle -- with the FH chip, the AECB chip, the vintage bar and the
bureau-history line stacked to its right. Colour follows the FH bands
everywhere: the dial zones by configured tone, both chips by the delivered FH
band's tone.
"""

from __future__ import annotations

import math

from ... import dates
from ...derive import scoring
from .. import components as c
from .. import tokens

META = {
    "title": "Score &amp; Bureau History",
}

# Tones for the band chips, keyed by the band's configured tone.
#
# SOLID fill: the band is the one thing an underwriter reads off this section.
# Red/amber/green is the correct vocabulary here despite the "risk only" rule:
# a score band IS a risk grade. An unrecognised band code arrives with an
# empty tone from scoring.fh_band() and renders as the neutral chip -- an
# unknown risk band has earned no colour, least of all green.
#
# The seven FH bands (U, SPR, VHR, HR, MR, LR, VLR) run a red->green ramp:
# red-ink, red, dpd3 (orange-red), amber, dpd1 (yellow), green-mid, green.
_FILL = {"red-ink": "var(--red-ink)", "red": "var(--red)",
         "dpd3": "var(--dpd3)", "amber": "var(--amber)",
         "dpd1": "var(--dpd1)", "green-mid": "var(--green-mid)",
         "green": "var(--green)"}
# Text on each fill. The light fills -- dpd1 (MR) and green-mid (LR) -- take
# dark ink: white on them reads at ~3:1 or worse, and the chip must match its
# dial zone exactly (colour follows the configured FH bands).
_INK = {"dpd1": "var(--ink)", "green-mid": "var(--ink)"}


def _checked_tone(tone):
    """A configured band tone, which must be one this section can draw.

    An unknown tone is a configuration fault and fails loudly: it must neither
    crash the dial on one path nor silently paint the chip green on another.
    """
    if tone and tone not in _FILL:
        raise ValueError("config/bands.json fh_bands tone %r is not one of %s."
                         % (tone, ", ".join(sorted(_FILL))))
    return tone

# Dial zone opacity per configured tone, over the tone's own token colour.
# The zones are the backdrop the marker is read against, so they stay lighter
# than the solid chips; U's red-ink is lightest because it is the widest zone.
_ZONE_OPACITY = {"red-ink": .3, "red": .55, "dpd3": .6, "amber": .6,
                 "dpd1": .7, "green-mid": .6, "green": .6}

# Dial geometry, in SVG user units. The dial is a 120-degree arc of a wide
# circle: the scale minimum at the left foot, the maximum at the right, the
# score in the bowl.
#
# The dial is the section's hero. Its HEIGHT is fixed by the
# section (report.css caps it), so the shape decides how big it can look: a
# semicircle is only 2:1, while a 120-degree sweep is ~2.8:1 -- the same height
# buys a far wider, larger-radius dial that fills the card's width beside the
# chips (140 degrees still left ~100px of the card empty at 1560px). Every
# label sits INSIDE the bowl and
# the viewBox is cropped to what is drawn, so no width or height is spent on
# margins. The viewBox ratio reaches the CSS as --dial-ratio (see _dial_block).
_SWEEP = math.radians(120)
_R, _STROKE = 150, 20
_MARK_R = 9                               # .sp-mark adds a 3.5 stroke
_MARK_REACH = _MARK_R + 1.75
_HALF = _SWEEP / 2

# Tick labels: 7.5-unit mono text (report.css .sp-ticks) centred on a ring just
# inside the arc. Boundaries fill the outer ring first, then the leftovers try
# a second, deeper ring; one that fits neither is dropped -- 632 / 647 / 653
# sit 15 and 6 points apart and cannot all print. The hover lists every range.
# _TICK_CH is the mono advance (0.6em) at 7.5 units. At 8 units 720 no
# longer fits beside 685 and 750, so 7.5 is the ceiling for the current bands.
_TICK_RINGS = (_R - _STROKE / 2 - 7.5, _R - _STROKE / 2 - 17.5)
_TICK_CH, _TICK_H, _TICK_PAD = 4.5, 7.5, 0.5

# The score figure (report.css .sp-val, 44 units) and its cap height.
_VAL_SIZE, _VAL_CAP = 44, 32


def _extent():
    """viewBox width/height and the circle centre, cropped to what is drawn:
    the arc's outer edge and the marker at the top and at either foot, and
    the scale-end labels, which sit lowest of all."""
    pad = 1.5
    reach = _R + max(_STROKE / 2, _MARK_REACH)
    half_w = max((_R + _STROKE / 2) * math.sin(_HALF),
                 _R * math.sin(_HALF) + _MARK_REACH) + pad
    cy = reach + pad
    bottom = max(cy - (_R - _STROKE / 2) * math.cos(_HALF),
                 cy - _R * math.cos(_HALF) + _MARK_REACH,
                 cy - _TICK_RINGS[0] * math.cos(_HALF) + _TICK_H / 2) + pad
    return 2 * half_w, bottom, half_w, cy


_W, _H, _CX, _CY = _extent()


def render(ctx, meta) -> str:
    # A missing score does not blank the card: the bands and the bureau
    # history come from other fields -- one of them another array -- and
    # hiding them with the score would be information loss.
    gauge = scoring.gauge(ctx)
    body = ('<div class="sp">%s%s</div>'
            % (_dial_block(ctx, gauge), _side_block(ctx)))
    return c.section_card(body=body, **meta)


# --- the dial ---------------------------------------------------------------

def _angle(frac):
    """Scale fraction 0..1 -> angle from vertical, -_HALF (left) .. +_HALF."""
    return _SWEEP * max(0.0, min(1.0, frac)) - _HALF


def _point(frac, radius):
    a = _angle(frac)
    return _CX + radius * math.sin(a), _CY - radius * math.cos(a)


def _arc(frac_from, frac_to):
    # Every zone is under 180 degrees (the whole sweep is 120), so the
    # large-arc flag is always 0.
    x1, y1 = _point(frac_from, _R)
    x2, y2 = _point(frac_to, _R)
    return "M %.2f %.2f A %d %d 0 0 1 %.2f %.2f" % (x1, y1, _R, _R, x2, y2)


def _dial_block(ctx, gauge) -> str:
    """The dial: FH zones, tick values, marker, score.

    Geometry comes from scoring.gauge() when there is a score; without one
    the zones still draw (they are config, not payload) and the bowl says
    the score is not reported -- with the bureau's own reason when it sent
    one.
    """
    geo = gauge or scoring.scale_geometry(ctx)
    lo, hi = geo["min"], geo["max"]

    zones, start = [], 0.0
    for z in geo["zones"]:
        end = start + z["width"] / 100.0
        zones.append('<path d="%s" stroke="%s" stroke-opacity="%.2f"/>'
                     % (_arc(start, end),
                        tokens.token(_checked_tone(z["tone"]) or "ink-4"),
                        _ZONE_OPACITY.get(z["tone"], .3)))
        start = end

    ticks = _tick_labels(geo, gauge)

    if gauge:
        mx, my = _point(gauge["pct"] / 100.0, _R)
        marker = ('<circle class="sp-mark" cx="%.2f" cy="%.2f" r="%d"/>'
                  % (mx, my, _MARK_R))
        centre = ('<text class="sp-val" x="%.1f" y="%.1f" '
                  'text-anchor="middle">%d</text><text class="sp-k" x="%.1f" '
                  'y="%.1f" text-anchor="middle">SCORE</text>'
                  % (_CX, _val_baseline(), gauge["value"], _CX, _H - 3))
    else:
        marker = ""
        centre = ('<text class="sp-na" x="%.1f" y="%.1f" text-anchor="middle">'
                  'Score not reported</text>' % (_CX, _H - 22))

    svg = ('<svg class="sp-svg" viewBox="0 0 %.1f %.1f" role="img" '
           'aria-label="%s"><g class="sp-zones" fill="none" '
           'stroke-width="%d">%s</g><g class="sp-ticks">%s</g>%s%s</svg>'
           % (_W, _H, c.attr("Score %s on the FH scale %d to %d"
                             % (gauge["value"] if gauge else "not reported",
                                lo, hi)),
              _STROKE, "".join(zones), "".join(ticks), marker, centre))

    # --dial-ratio lets report.css turn its height budget into a width cap.
    return ('<div class="sp-dial" style="--dial-ratio:%.4f" data-info="%s">'
            '%s%s%s</div>'
            % (_W / _H, c.attr(_ranges_tip(ctx)), svg,
               _mismatch_mark(ctx, gauge), _error_line(ctx, gauge)))


def _val_baseline():
    """The score figure sits just above its SCORE caption."""
    return _H - 15


def _tick_labels(geo, gauge):
    """Scale ends and band boundaries as <text>, all inside the bowl.

    Each sits at its true angle. The ends go on the outer ring first, so they
    are never crowded out; boundaries are then placed in two passes: first every one the outer ring can
    hold, then the leftovers on the inner ring; what fits neither is left off.
    Fit is judged by box overlap against every label already placed and the
    score figure, so no two ever print on top of each other. Outer-ring-first
    keeps the labels on one line wherever the bands allow it -- placing each
    boundary on its first free ring in scale order zig-zagged, and let a
    crowded low boundary take the room a later one needed.
    """
    lo, hi = geo["min"], geo["max"]
    span = float(hi - lo)
    placed, out = [], []
    if gauge:
        # The score figure: ~0.62em per display digit, cap height _VAL_CAP.
        half = 0.31 * _VAL_SIZE * len(str(gauge["value"])) + 2
        base = _val_baseline()
        placed.append((_CX - half, base - _VAL_CAP - 2, _CX + half, base + 2))

    def box(x, y, text):
        half = len(text) * _TICK_CH / 2 + _TICK_PAD
        return (x - half, y - _TICK_H / 2 - _TICK_PAD,
                x + half, y + _TICK_H / 2 + _TICK_PAD)

    def clear(b):
        return all(b[2] <= p[0] or b[0] >= p[2] or b[3] <= p[1] or b[1] >= p[3]
                   for p in placed)

    ends, inner = [], []
    for t in geo["ticks"]:
        frac = (t["value"] - lo) / span
        (inner if 0.001 < frac < 0.999 else ends).append((frac, str(t["value"])))

    for frac, text in ends:
        x, y = _point(frac, _TICK_RINGS[0])
        placed.append(box(x, y, text))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                   % (x, y + _TICK_H / 2 - 1, text))

    for ring in _TICK_RINGS:
        left_over = []
        for frac, text in inner:
            x, y = _point(frac, ring)
            b = box(x, y, text)
            if not clear(b):
                left_over.append((frac, text))
                continue
            placed.append(b)
            out.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s'
                       '</text>' % (x, y + _TICK_H / 2 - 1, text))
        inner = left_over
    return out


def _ranges_tip(ctx) -> str:
    """'FH risk bands: U 300–631 · SPR 632–646 · … · VLR 750–900.'

    Each band runs from its own 'from' to one below the next band's 'from';
    the last runs to the scale maximum. bands.json deliberately has no 'to'.
    """
    bands = ctx.bands.get("fh_bands") or []
    top = ctx.bands["scale"]["max"]
    parts = []
    for i, band in enumerate(bands):
        end = bands[i + 1].get("from") - 1 if i + 1 < len(bands) else top
        parts.append("%s %s–%s" % (band.get("code"), band.get("from"), end))
    return ("FH risk bands (config/bands.json): %s. The chip shows the band "
            "AECB delivered, which is authoritative." % " · ".join(parts))


def _mismatch_mark(ctx, gauge) -> str:
    """Amber '!' when the configured zone under the marker is not the
    delivered FH band. The delivered band wins; the config needs checking."""
    fh = scoring.fh_band(ctx)
    zone = scoring.configured_band(ctx)
    if not (gauge and fh and zone) or zone == fh["code"]:
        return ""
    return ('<span class="attn sp-attn" data-info="%s">!</span>' % c.attr(
        "The configured cut-offs place %d in %s, but AECB delivered %s. The "
        "delivered band is authoritative — check the cut-offs in "
        "config/bands.json against the FH scorecard."
        % (gauge["value"], zone, fh["code"])))


def _error_line(ctx, gauge) -> str:
    """The bureau's own reason for a missing score, when it sent one."""
    if gauge:
        return ""
    number = ctx.score.get("ErrorNumber")
    text = ctx.score.get("ErrorDescription")
    if not (number or text):
        return ('<div class="sp-err na">No score and no error reason '
                'delivered</div>')
    reason = c.esc(text) if text else "no description"
    ref = (" (error %s)" % c.esc(number)) if number not in (None, "") else ""
    return '<div class="sp-err">Score not returned — %s%s</div>' % (reason, ref)


# --- the right-hand column ---------------------------------------------------
# The chips and the vintage bar share one stack (.ss-bands), sized by its
# widest tile; the file-length line sits under it.

def _side_block(ctx) -> str:
    """The FH chip, the AECB chip and the vintage bar as ONE stack of tiles --
    one width, the widest tile's (the column is only as wide as its content
    needs, so the dial gets the rest) -- then the file length."""
    return ('<div class="sp-side"><div class="ss-bands">%s%s</div>%s</div>'
            % (_band_block(ctx), _vintage_bar(ctx), _history_block(ctx)))


def _band_block(ctx) -> str:
    """The two delivered bands, stacked as equal-width tiles.

    Both tiles carry ONE tone, the delivered FH band's -- the colour coding
    follows the FH bands; the AECB tile only
    names AECB's own band. When only AECB is delivered there is no FH tone to
    borrow and its tile stays neutral.
    """
    fh = scoring.fh_band(ctx)
    aecb = scoring.aecb_band(ctx)
    tone = fh["tone"] if fh else None
    chips = []

    if fh:
        # Most FH descriptions are the code itself ("SPR"); show it once.
        label = ("%s · %s" % (fh["code"], fh["label"])
                 if fh["label"] != fh["code"] else fh["code"])
        chips.append(_band_chip(label, "FH", tone,
                                mark=_fh_field_conflict(ctx)))
    if aecb:
        # The delivered letter leads: the label is a provisional config
        # mapping, so what the bureau actually sent must stay visible.
        label = ("%s · %s" % (aecb["code"], aecb["label"])
                 if aecb["label"] != aecb["code"] else aecb["code"])
        chips.append(_band_chip(label, "AECB", tone, info=(
            "score.DataRange %s, labelled by config/bands.json aecb_ranges — "
            "a provisional mapping pending the AECB scorecard spec."
            % aecb["code"])))

    if not chips:
        return '<span class="na">Band not reported</span>'
    return "".join(chips)


def _fh_field_conflict(ctx) -> str:
    """Amber '!' when FHScoreBand and FHScoreBand1 both arrive and differ.

    The chip reads FHScoreBand and falls back to FHScoreBand1; a second,
    different band would otherwise vanish behind the first.
    """
    first = ctx.score.get("FHScoreBand")
    second = ctx.score.get("FHScoreBand1")
    if not (first and second) or str(first).strip() == str(second).strip():
        return ""
    return (' <span class="attn" data-info="%s">!</span>' % c.attr(
        "score.FHScoreBand is %s but score.FHScoreBand1 is %s. The chip shows "
        "FHScoreBand; what FHScoreBand1 represents is to be confirmed with "
        "AECB." % (first, second)))


def _band_chip(label, source, tone, info="", mark="") -> str:
    """One band tile: the band on the left, the scorecard that named it right."""
    hover = ' data-info="%s"' % c.attr(info) if info else ""
    if not tone:
        return ('<span class="ss-band neutral"%s>%s%s<em>%s</em></span>'
                % (hover, c.esc(label), mark, source))
    fill = _FILL[_checked_tone(tone)]
    return ('<span class="ss-band" style="background:%s; color:%s; '
            'border-color:%s"%s>%s%s<em>%s</em></span>'
            % (fill, _INK.get(tone, "#fff"), fill, hover, c.esc(label), mark,
               source))


def _vintage_bar(ctx) -> str:
    """The vintage tile, or nothing when the file length can't be worked out."""
    vintage = scoring.vintage_band(ctx)
    if scoring.history_months(ctx) is None or not vintage.get("code"):
        return ""
    return ('<div class="ss-vint" data-info="%s">'
            '<span class="ss-vint-k">Vintage</span><span>%s</span></div>'
            % (c.attr(_vintage_tip(ctx)), c.esc(vintage["code"])))


def _history_block(ctx) -> str:
    """Bureau file length and the oldest facility date."""
    months = scoring.history_months(ctx)
    oldest = ctx.totals.get("OldestContractOpenDate")

    if months is None:
        # Say which part is missing -- the oldest date may well have arrived.
        if oldest and dates.parse_any(oldest) and ctx.report_date is None:
            text = ("Bureau history unknown — no report date (since %s)"
                    % dates.fmt_month_year(oldest))
        elif oldest and not dates.parse_any(oldest):
            text = ("Bureau history unknown — oldest contract date %s is "
                    "unreadable" % c.esc(oldest))
        else:
            text = "Bureau history not reported"
        return '<div class="ss-hist"><span class="na">%s</span></div>' % text

    since = ('<span class="ss-hs">since %s</span>' % dates.fmt_month_year(oldest)
             ) if oldest else ""

    # File length is computed from OldestContractOpenDate rather than delivered.
    tip = ("Bureau history, computed from "
           "contractsTotalSummary.OldestContractOpenDate against the report "
           "date. AECB does not deliver a file length.")
    return ('<div class="ss-hist">'
            '<div class="ss-hline" data-info="%s">'
            '<span class="ss-hv">%d</span><span class="ss-hu">months</span>%s'
            '</div></div>'
            % (c.attr(tip), months, since))


def _vintage_tip(ctx) -> str:
    bands = (ctx.bands.get("vintage_bands") or {}).get("bands") or []
    parts = []
    for band in bands:
        hi = band.get("to_months")
        lo = band.get("from_months")
        # The open-ended top band reads "96+ mo", not "96–+ mo".
        parts.append("%s %d+ mo" % (band.get("code"), lo) if hi is None
                     else "%s %d–%d mo" % (band.get("code"), lo, hi))
    return ("AECB vintage band, a configured policy mapping over file length: "
            "%s. The screen renders the band; it does not set the cut-offs."
            % " · ".join(parts))
