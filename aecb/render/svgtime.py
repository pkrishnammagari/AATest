"""Shared time axis for the inline-SVG timelines (sections 04 and 05).

Both sections draw events against calendar time ending at the report date, so
the tick strategy, the label-collision rule and the report-date marker live
here once. Section-specific geometry (padding, heights) stays in the section;
this module only needs the numbers, not the layout.
"""

from __future__ import annotations

import datetime

from .. import dates
from . import components as c
from . import tokens

# IBM Plex Mono advance width at the 8.5-unit axis size. Used to keep tick
# labels from colliding -- SVG cannot measure text before it is laid out.
CHAR_W = 5.1


def ticks(x0, x1):
    """Year boundaries, or half-years over a short domain. 3-8 labels.

    The columns these axes live in are half a card wide, so a label every year
    crowds a long file -- the step widens until the labels fit.
    """
    years = (x1.year - x0.year) + 1
    out = []
    if years >= 3:
        step = 1 if years <= 5 else (2 if years <= 10 else 3)
        for year in range(x0.year + 1, x1.year + 1, step):
            when = datetime.date(year, 1, 1)
            if x0 <= when <= x1:
                out.append((when, str(year)))
    else:
        for year in range(x0.year, x1.year + 1):
            for month in (1, 7):
                when = datetime.date(year, month, 1)
                if x0 <= when <= x1:
                    out.append((when, dates.fmt_mon(when)))
    # Always anchor the left edge, so the axis says where it starts.
    out.insert(0, (x0, dates.fmt_mon(x0)))
    return out


def axis(sx, x0, x1, axis_y, width, pad_l, pad_r, pad_t, report_date) -> str:
    """Baseline, tick marks and labels, and the report-date closing marker.

    The report date closes the axis: everything to its right is unknown, not
    empty -- marked so a bar or event near the edge is not read as running to
    today.
    """
    out = ['<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
           % (pad_l, axis_y, width - pad_r, axis_y, tokens.token("line-2"))]

    # The domain anchor is always drawn, so a period tick that would print on
    # top of it is dropped. Measured against the anchor's actual width rather
    # than a fixed gap: "Feb '14" is twice the width of "2015", and a constant
    # that clears one collides on the other.
    all_ticks = ticks(x0, x1)
    anchor_end = sx(x0) + CHAR_W * len(all_ticks[0][1]) + 10
    for i, (when, label) in enumerate(all_ticks):
        x = sx(when)
        if i and (x - CHAR_W * len(label) / 2.0) < anchor_end:
            continue
        anchor = "middle"
        if x < pad_l + 14:
            anchor = "start"
        elif x > width - pad_r - 14:
            anchor = "end"
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                   % (x, axis_y, x, axis_y + 4, tokens.token("line-2")))
        out.append('<text x="%.1f" y="%.1f" text-anchor="%s" '
                   'font-family="IBM Plex Mono" font-size="8.5" fill="%s">%s</text>'
                   % (x, axis_y + 14, anchor, tokens.token("ink-3"), label))

    if report_date and x0 <= report_date <= x1:
        x = sx(report_date)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                   'stroke-dasharray="3 3"/>'
                   % (x, pad_t - 6, x, axis_y, tokens.token("ink-4")))
        out.append('<text x="%.1f" y="%.1f" text-anchor="end" '
                   'font-family="IBM Plex Mono" font-size="8" fill="%s" '
                   'data-info="Report date %s -- the bureau reports nothing '
                   'after it.">report</text>'
                   % (x - 4, pad_t - 8, tokens.token("ink-3"),
                      c.attr(dates.fmt_short(report_date))))
    return "".join(out)
