"""Score & bureau history.

Sources: score.DataIndex (the number), score.FHScoreBand, score.DataRange
(AECB band letter), score.ErrorNumber / ErrorDescription (why no score came
back), contractsTotalSummary.OldestContractOpenDate.

IMPORTANT -- the delivered FH band is authoritative. The chip shows what AECB
sent in FHScoreBand; the dial is only configured geometry from
config/bands.json. Do not "tidy" this by deriving the band from the number:
for the reference payload the configured cut-offs put 732 in VLR while the
bureau delivers LR, so computing it would silently contradict the bureau.
When the two disagree the dial carries an amber '!' saying so (decision,
24 Sep 2026) -- the delivered band still wins, the config gets checked.

Layout (24 Sep 2026, user decision): a half-width card beside section 03
(worst statuses). A semicircular dial -- FH band zones, marker at the score,
the score in the middle -- with the FH chip, the AECB chip, the vintage bar
and the bureau-history line stacked to its right. Colour follows the FH bands
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
_FILL = {"red": "var(--red)", "amber": "var(--amber)",
         "green-mid": "var(--green-mid)", "green": "var(--green)"}
# Text on each fill. The light green-mid (LR) takes dark ink: white on it
# reads at ~3:1, and the chip must match its dial zone exactly (colour follows
# the configured FH bands, 24 Sep 2026) rather than borrow VLR's darker green.
_INK = {"green-mid": "var(--ink)"}

# Dial zone opacity per configured tone, over the tone's own token colour.
# The zones are the backdrop the marker is read against, so they stay lighter
# than the solid chips; red is lightest because it is the widest zone.
_ZONE_OPACITY = {"red": .32, "amber": .45, "green-mid": .6, "green": .6}

# Dial geometry, in SVG user units. The dial is a 180-degree arc: the scale
# minimum at the left end, the maximum at the right, the score in the bowl.
_W, _H = 250, 132
_CX, _CY = 125, 108
_R, _STROKE = 86, 16


def render(ctx, meta) -> str:
    # A missing score no longer blanks the card (24 Sep 2026): the bands and
    # the bureau history come from other fields -- one of them another array
    # -- and hiding them with the score was information loss.
    gauge = scoring.gauge(ctx)
    body = ('<div class="sp">%s%s</div>'
            % (_dial_block(ctx, gauge), _side_block(ctx)))
    return c.section_card(body=body, **meta)


# --- the dial ---------------------------------------------------------------

def _angle(frac):
    """Scale fraction 0..1 -> angle in radians, pi (left) .. 0 (right)."""
    return math.pi * (1.0 - max(0.0, min(1.0, frac)))


def _point(frac, radius):
    a = _angle(frac)
    return _CX + radius * math.cos(a), _CY - radius * math.sin(a)


def _arc(frac_from, frac_to):
    x1, y1 = _point(frac_from, _R)
    x2, y2 = _point(frac_to, _R)
    return "M %.2f %.2f A %d %d 0 0 1 %.2f %.2f" % (x1, y1, _R, _R, x2, y2)


def _dial_block(ctx, gauge) -> str:
    """The semicircular dial: FH zones, tick values, marker, score.

    Geometry comes from scoring.gauge() when there is a score; without one
    the zones still draw (they are config, not payload) and the bowl says
    the score is not reported -- with the bureau's own reason when it sent
    one.
    """
    geo = gauge or scoring.scale_geometry(ctx)
    lo, hi = geo["min"], geo["max"]
    span = float(hi - lo)

    zones, start = [], 0.0
    for z in geo["zones"]:
        end = start + z["width"] / 100.0
        zones.append('<path d="%s" stroke="%s" stroke-opacity="%.2f"/>'
                     % (_arc(start, end), tokens.token(z["tone"] or "ink-4"),
                        _ZONE_OPACITY.get(z["tone"], .3)))
        start = end

    ticks = []
    for t in geo["ticks"]:
        frac = (t["value"] - lo) / span
        if frac <= 0.001 or frac >= 0.999:
            # The scale ends sit under the arc's feet, not beside them.
            x = _CX + (-_R if frac < .5 else _R)
            ticks.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>'
                         % (x, _CY + 16, t["value"]))
            continue
        x, y = _point(frac, _R + _STROKE / 2 + 9)
        anchor = "end" if x < _CX - 8 else "start" if x > _CX + 8 else "middle"
        ticks.append('<text x="%.1f" y="%.1f" text-anchor="%s">%s</text>'
                     % (x, y + 3, anchor, t["value"]))

    if gauge:
        mx, my = _point(gauge["pct"] / 100.0, _R)
        marker = ('<circle class="sp-mark" cx="%.2f" cy="%.2f" r="7"/>'
                  % (mx, my))
        centre = ('<text class="sp-val" x="%d" y="%d" text-anchor="middle">'
                  '%d</text><text class="sp-k" x="%d" y="%d" '
                  'text-anchor="middle">SCORE</text>'
                  % (_CX, _CY - 12, gauge["value"], _CX, _CY + 4))
    else:
        marker = ""
        centre = ('<text class="sp-na" x="%d" y="%d" text-anchor="middle">'
                  'Score not reported</text>' % (_CX, _CY - 14))

    svg = ('<svg class="sp-svg" viewBox="0 0 %d %d" role="img" '
           'aria-label="%s"><g class="sp-zones" fill="none" '
           'stroke-width="%d">%s</g><g class="sp-ticks">%s</g>%s%s</svg>'
           % (_W, _H, c.attr("Score %s on the FH scale %d to %d"
                             % (gauge["value"] if gauge else "not reported",
                                lo, hi)),
              _STROKE, "".join(zones), "".join(ticks), marker, centre))

    return ('<div class="sp-dial" data-info="%s">%s%s%s</div>'
            % (c.attr(_ranges_tip(ctx)), svg, _mismatch_mark(ctx, gauge),
               _error_line(ctx, gauge)))


def _ranges_tip(ctx) -> str:
    """'FH risk bands: HR 300–619 · MR 620–678 · LR 679–729 · VLR 730–900.'

    Each band runs from its own 'from' to one below the next band's 'from';
    the last runs to the scale maximum. bands.json deliberately has no 'to'.
    """
    bands = ctx.bands.get("fh_bands") or []
    top = (ctx.bands.get("scale") or {}).get("max", 900)
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

def _side_block(ctx) -> str:
    return ('<div class="sp-side">%s%s</div>'
            % (_band_block(ctx), _history_block(ctx)))


def _band_block(ctx) -> str:
    """The two delivered bands, stacked as equal-width tiles.

    Both tiles carry ONE tone, the delivered FH band's -- the colour coding
    follows the FH bands (user decision, 24 Sep 2026); the AECB tile only
    names AECB's own band. When only AECB is delivered there is no FH tone to
    borrow and its tile stays neutral.
    """
    fh = scoring.fh_band(ctx)
    aecb = scoring.aecb_band(ctx)
    tone = fh["tone"] if fh else None
    chips = []

    if fh:
        chips.append(_band_chip("%s · %s" % (fh["code"], fh["label"]), "FH",
                                tone, mark=_fh_field_conflict(ctx)))
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
        return '<div class="ss-bands"><span class="na">Band not reported</span></div>'
    return '<div class="ss-bands">%s</div>' % "".join(chips)


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
    fill = _FILL.get(tone, "var(--green)")
    return ('<span class="ss-band" style="background:%s; color:%s; '
            'border-color:%s"%s>%s%s<em>%s</em></span>'
            % (fill, _INK.get(tone, "#fff"), fill, hover, c.esc(label), mark,
               source))


def _history_block(ctx) -> str:
    """Vintage bar, then bureau file length and the oldest facility date."""
    months = scoring.history_months(ctx)
    oldest = ctx.totals.get("OldestContractOpenDate")
    vintage = scoring.vintage_band(ctx)

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

    bar = ""
    if vintage.get("code"):
        bar = ('<div class="ss-vint" data-info="%s">'
               '<span class="ss-vint-k">Vintage</span><span>%s</span></div>'
               % (c.attr(_vintage_tip(ctx)), c.esc(vintage["code"])))

    since = ('<span class="ss-hs">since %s</span>' % dates.fmt_month_year(oldest)
             ) if oldest else ""

    # File length is computed from OldestContractOpenDate rather than delivered.
    tip = ("Bureau history, computed from "
           "contractsTotalSummary.OldestContractOpenDate against the report "
           "date. AECB does not deliver a file length.")
    return ('<div class="ss-hist">%s'
            '<div class="ss-hline" data-info="%s">'
            '<span class="ss-hv">%d</span><span class="ss-hu">months</span>%s'
            '</div></div>'
            % (bar, c.attr(tip), months, since))


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
