"""Score & bureau history.

Sources: score.DataIndex (the number), score.FHScoreBand, score.DataRange
(AECB band letter), contractsTotalSummary.OldestContractOpenDate.

IMPORTANT -- the delivered band is authoritative. The chip shows what AECB sent
in FHScoreBand; the bar geometry is only configured positioning from
config/bands.json. Do not "tidy" this by deriving the band from the number: for
the reference payload the configured cut-offs put 732 in VLR while the bureau
delivers LR, so computing it would silently contradict the bureau. The cut-offs
are provisional and still need reconciling against the FH scorecard -- that is a
config question, which is why it is recorded here rather than printed on screen.

Layout is a single strip -- score, delivered bands, gauge, history -- following
the same grammar as the top-bar validity strip.
"""

from __future__ import annotations

from ... import dates
from ...derive import scoring
from .. import components as c

META = {
    "title": "Score &amp; Bureau History",
}

# Tones for the band chips, keyed by the band's configured tone.
#
# SOLID, not the pale wash these used to carry. The band is the one thing an
# underwriter reads off this section, and a wash chip at 12px was something
# they had to hunt for. Solid fill is far louder at identical height -- which
# matters, because the strip's height is fixed by .ss-hist and the chips only
# had ~13px of slack to spend. Red/amber/green is the correct vocabulary here
# despite the "risk only" rule: a score band IS a risk grade.
#
# Anything not in these maps falls through to the green default below, which is
# also what an unknown tone gets -- see scoring.fh_band(), which defaults to
# "green" for an unrecognised band code.
_FILL = {"red": "var(--red)", "amber": "var(--amber)"}
_LINE = {"red": "var(--red)", "amber": "var(--amber)"}

# Fill for each zone of the gauge bar.
_ZONE_FILL = {
    "red": "rgba(176,36,48,.32)",
    "amber": "rgba(179,117,22,.40)",
    "green-mid": "rgba(79,163,125,.55)",
    "green": "rgba(31,122,82,.55)",
}


def render(ctx, meta) -> str:
    gauge = scoring.gauge(ctx)

    if not gauge:
        body = c.empty_state(
            "Score not reported",
            "score.DataIndex is absent. The bureau returns no score when the "
            "file is too thin to grade, or when the score product was not "
            "requested.")
        return c.section_card(body=body, **meta)

    # Number, then where it sits on the scale, then what the two scorecards call
    # that position -- the gauge answers "how good" before the chips name it.
    body = ('<div class="score-strip">%s%s%s%s</div>'
            % (_score_block(gauge), _gauge_block(ctx, gauge),
               _band_block(ctx), _history_block(ctx)))
    return c.section_card(body=body, **meta)


def _score_block(gauge) -> str:
    return ('<div class="ss-score"><span class="ss-val">%d</span>'
            '<span class="ss-k">Score</span></div>' % gauge["value"])


def _band_block(ctx) -> str:
    """The two delivered bands, stacked as equal-width tiles.

    The FH and AECB scales are taken to grade the same thing, so one score
    produces one verdict and both tiles carry ONE tone -- two colours against a
    single position would read as two opinions. The tone comes from the FH band
    because that is the band FH policy acts on; when only AECB is delivered
    there is nothing to borrow and its tile stays neutral. If the two scales are
    ever confirmed to diverge, this is the line to revisit.
    """
    fh = scoring.fh_band(ctx)
    aecb = scoring.aecb_band(ctx)
    tone = fh["tone"] if fh else None
    chips = []

    if fh:
        chips.append(_band_chip("%s · %s" % (fh["code"], fh["label"]), "FH", tone))
    if aecb:
        chips.append(_band_chip(aecb["label"], "AECB", tone))

    if not chips:
        return '<div class="ss-bands"><span class="na">Band not reported</span></div>'
    return '<div class="ss-bands">%s</div>' % "".join(chips)


def _band_chip(label, source, tone) -> str:
    """One band tile: the band on the left, the scorecard that named it right."""
    if tone is None:
        return ('<span class="ss-band neutral">%s<em>%s</em></span>'
                % (c.esc(label), source))
    return ('<span class="ss-band" style="background:%s; color:#fff; '
            'border-color:%s">%s<em>%s</em></span>'
            % (_FILL.get(tone, "var(--green)"),
               _LINE.get(tone, "var(--green)"),
               c.esc(label), source))


def _gauge_block(ctx, gauge) -> str:
    """Zone bar, marker at the delivered score, tick numbers beneath.

    Zone names live in the tooltip rather than as a third stacked row -- the
    band chip already names where the applicant sits, so the bar only has to
    show the position.
    """
    bar = "".join(
        '<i style="width:%.2f%%; background:%s"></i>'
        % (z["width"], _ZONE_FILL.get(z["tone"], _ZONE_FILL["green"]))
        for z in gauge["zones"])

    # Each tick sits at its true position on the scale, not evenly spaced --
    # otherwise a label and the marker cannot be compared by eye.
    ticks = "".join('<i style="left:%.2f%%">%s</i>' % (t["pct"], t["value"])
                    for t in gauge["ticks"])

    ranges = " · ".join(
        "%s %s–%s" % (b.get("code"), b.get("from"), b.get("to"))
        for b in (ctx.bands.get("fh_bands") or []))
    tip = ("FH risk bands: %s. Cut-offs are shared with the AECB scale; the "
           "band shown on the chip is the one AECB delivered." % ranges)

    return ('<div class="ss-gauge" data-info="%s">'
            '<div class="ss-bar">%s</div>'
            '<span class="ss-marker" style="left:%.2f%%"></span>'
            '<div class="ss-ticks">%s</div></div>'
            % (c.attr(tip), bar, gauge["pct"], ticks))


def _history_block(ctx) -> str:
    """Bureau file length, vintage band and the oldest facility date."""
    months = scoring.history_months(ctx)
    oldest = ctx.totals.get("OldestContractOpenDate")
    vintage = scoring.vintage_band(ctx)

    if months is None:
        return ('<div class="ss-hist"><span class="na">Bureau history '
                'not reported</span></div>')

    # The vintage band leads the block as a full-width bar rather than sitting
    # beside the figure as a chip. It is the thing an underwriter must not miss,
    # and a chip glued to a 46px number loses that contest every time.
    #
    # It is paid for, not added: .ss-hist sets the whole strip's height and had
    # ZERO slack (measured 82.17 closed / 74.09 open, exactly the strip). The
    # bar is funded by folding "months" and "Since ..." into the column beside
    # the figure -- they fit inside the line the figure already occupies -- and
    # by dropping the "Bureau history" caption, whose provenance tooltip moves
    # onto the figure so nothing is lost but the word. Net: the block gets
    # SHORTER, so section 02 does not grow. Re-measure if any of this changes.
    bar = ""
    if vintage.get("code"):
        # Two flex children, pushed apart by justify-content on .ss-vint. The
        # code needs no class of its own -- it inherits the bar's own type,
        # which is the loud half by design.
        bar = ('<div class="ss-vint" data-info="%s">'
               '<span class="ss-vint-k">Vintage</span><span>%s</span></div>'
               % (c.attr(_vintage_tip(ctx)), c.esc(vintage["code"])))

    # Omitted rather than emitted empty -- an empty span still claims its line
    # box and would open a gap in the column.
    since = ('<span class="ss-hs">Since %s</span>' % dates.fmt_month_year(oldest)
             ) if oldest else ""

    # File length is computed from OldestContractOpenDate rather than delivered.
    # The provenance now hangs off the figure itself, since the caption that
    # used to carry it has gone.
    tip = ("Bureau history, computed from "
           "contractsTotalSummary.OldestContractOpenDate against the report "
           "date. AECB does not deliver a file length.")
    return ('<div class="ss-hist">%s'
            '<div class="ss-hline">'
            '<span class="ss-hv" data-info="%s">%d</span>'
            '<span class="ss-hunit"><span class="ss-hu">months</span>%s</span>'
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
