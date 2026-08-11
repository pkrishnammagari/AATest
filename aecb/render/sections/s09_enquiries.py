"""08 Recent applications -- credit sought elsewhere, on a split time axis.

Sources: applications, contractsTotalSummary.Applications90D.

The section is one chart. The counts it used to lead with are gone: four tiles
saying 5 / 6 / 4 / 15 answered a question nobody was asking, while the thing an
underwriter actually needs -- WHEN the customer went looking, and how the recent
weeks compare to the years behind them -- was not on the screen at all.

The axis maths lives in derive/applications.py, beside the payload decisions it
depends on. This module only lays out what that returns.

The phase pills that used to block this section are settled. AECB delivers two
states here, Requested and Disbursed, and they are encoded as a hollow and a
filled marker. The mockup's not-taken-up / approved / rejected states are not in
the payload and are not invented -- there is nothing left to remap.
"""

from __future__ import annotations

from ...derive import applications
from .. import components as c

META = {
    "title": "Recent Applications",
}


def render(ctx, meta) -> str:
    rows = ctx.rows("applications")
    delivered_90d = ctx.totals.get("Applications90D")

    if not rows:
        return c.section_card(
            body=c.empty_state("No applications reported",
                               "The applications array is empty in this payload."),
            aside=_aside(ctx, rows, delivered_90d), **meta)

    chart = applications.timeline(ctx, rows)
    if not chart:
        # Rows exist but none can be dated, so nothing can be placed in time.
        # The records are still on file and the section says so rather than
        # rendering an empty axis that reads as "no applications".
        body = c.empty_state(
            "Applications cannot be placed in time",
            "The bureau delivered no usable date on any application row, so "
            "there is no position to draw them at.")
        return c.section_card(body=body,
                              aside=_aside(ctx, rows, delivered_90d), **meta)

    return c.section_card(body=_chart(chart), aside=_aside(ctx, rows, delivered_90d),
                          **meta)


def _chart(chart) -> str:
    """The timeline shell. report.js fills it from window.__AECB.

    The height comes from the chart data because it depends on how many lanes
    the events needed, which is a property of the payload rather than of the
    layout -- and it is computed in ONE place, beside the lane pitch it derives
    from, so the two cannot drift.
    """
    height = chart["height"]
    return (
        '<div class="enq-tl" id="enqTimeline" style="height:%dpx"></div>'
        '<div class="enq-key">'
        '<span class="ek"><i class="ek-mk taken"></i>Disbursed</span>'
        '<span class="ek"><i class="ek-mk"></i>Requested</span>'
        '<span class="ek-note">Last %d days expanded; everything earlier is '
        'compressed into the left of the break.</span>'
        '</div>' % (height, chart["focusDays"])
    )


def _aside(ctx, rows, delivered_90d):
    """The one figure worth a pill: how much credit was sought recently.

    A single application is not adverse and no marker is coloured for risk. A
    cluster in ninety days is, and that is what this grades.
    """
    if delivered_90d is None:
        counted = len(applications.in_window(ctx, rows))
        if not rows:
            return c.tag("No applications on file")
        return c.tag("%d in %d days" % (counted, applications.FOCUS_DAYS))

    tone = "bad" if delivered_90d >= 4 else ("warn" if delivered_90d >= 2 else "good")
    tag = c.tag("%d in %d days %s"
                % (delivered_90d, applications.FOCUS_DAYS,
                   '<span class="prov-mark delivered" data-info="Delivered by '
                   'AECB in contractsTotalSummary.Applications90D.">delivered</span>'),
                tone)

    # The delivered counter and the rows delivered beside it should agree. When
    # they do not, that is a finding rather than something to smooth over -- but
    # it is one line, not the banner it used to be.
    counted = len(applications.in_window(ctx, rows))
    if counted != delivered_90d:
        tag += c.tag("%d row%s in window" % (counted, "" if counted == 1 else "s"),
                     "warn")
    return tag
