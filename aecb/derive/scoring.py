"""Score bands, bureau vintage and report validity.

The bureau delivers the score (score.DataIndex), its own band letter
(score.DataRange) and the FH band code (score.FHScoreBand). This module only
looks up labels and positions a marker -- it never recomputes a band from the
number, because the cut-offs are policy and the delivered band is authoritative.
"""

from __future__ import annotations

import datetime

from .. import dates


def score_value(ctx):
    value = ctx.score.get("DataIndex")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fh_band(ctx):
    """The delivered FH band, matched to its configured label.

    Returns {'code', 'label', 'tone'} or None when the payload omits it.
    """
    code = ctx.score.get("FHScoreBand") or ctx.score.get("FHScoreBand1")
    if not code:
        return None
    for band in ctx.bands.get("fh_bands") or []:
        if band.get("code") == code:
            return {"code": code, "label": band.get("label", code),
                    "tone": band.get("tone", "")}
    # A band code the config does not know. Tone stays neutral: green is the
    # best-case colour, and an unrecognised risk band has earned no colour.
    return {"code": code, "label": code, "tone": ""}


def aecb_band(ctx):
    """score.DataRange letter -> the configured AECB descriptive label."""
    letter = ctx.score.get("DataRange")
    if not letter:
        return None
    ranges = ctx.bands.get("aecb_ranges") or {}
    return {"code": letter, "label": ranges.get(letter) or letter}


def gauge(ctx):
    """Marker position, band widths and tick positions as percentages.

    Every position is proportional to the score scale, which is the whole point
    of the gauge: a tick and the marker must be comparable by eye. Ticks
    therefore carry their own pct rather than being spaced evenly -- laying five
    ticks out at 0/25/50/75/100 put the '730' label at 75% while a score of 732
    sat at 72%, making the marker look like it fell BELOW the band boundary it
    was actually above.

    Zone widths are measured boundary-to-boundary so they tile to exactly 100%.

    Returns None when there is no score to place.
    """
    value = score_value(ctx)
    scale = ctx.bands.get("scale") or {}
    lo, hi = scale.get("min", 300), scale.get("max", 900)
    if value is None or hi <= lo:
        return None

    span = float(hi - lo)

    def at(v):
        return max(0.0, min(100.0, (v - lo) / span * 100.0))

    bands = ctx.bands.get("fh_bands") or []
    zones = []
    for i, band in enumerate(bands):
        start = band.get("from", lo)
        # Each zone runs to where the next one begins, so no gap or overlap.
        end = bands[i + 1].get("from") if i + 1 < len(bands) else hi
        zones.append({
            "code": band.get("code"),
            "label": band.get("label"),
            "tone": band.get("tone"),
            "width": max(0.0, at(end) - at(start)),
        })

    # Scale floor, each band boundary, scale ceiling -- each at its true position.
    values = [lo] + [b.get("from") for b in bands[1:]] + [hi]
    ticks = [{"value": v, "pct": at(v)} for v in values]

    return {"value": value, "pct": at(value), "zones": zones, "ticks": ticks,
            "min": lo, "max": hi}


def history_months(ctx):
    """Bureau file length: oldest contract open date to the report date."""
    oldest = ctx.totals.get("OldestContractOpenDate")
    if not oldest or not ctx.report_date:
        return None
    # months_between returns None only for an unparseable date; a genuine 0 --
    # a file opened this month -- is a real length and must reach the B1 band.
    return dates.months_between(oldest, ctx.report_date)


def vintage_band(ctx):
    """AECB vintage band B1-B4 for the file length, from configured cut-offs.

    Returns {'code', 'all'} where 'all' is every band code in order, so the
    renderer can draw the full pip strip with one lit.
    """
    bands = (ctx.bands.get("vintage_bands") or {}).get("bands") or []
    codes = [b.get("code") for b in bands]
    months = history_months(ctx)
    if months is None:
        return {"code": None, "all": codes}
    for band in bands:
        lo = band.get("from_months", 0)
        hi = band.get("to_months")
        if months >= lo and (hi is None or months <= hi):
            return {"code": band.get("code"), "all": codes}
    return {"code": None, "all": codes}


def validity(ctx):
    """Report freshness against the configured look-back window.

    Returns {'report_date', 'age_days', 'window', 'valid', 'expires',
             'pct'} -- pct is the marker position on the meter, clamped to 100
    so an old report pins at the end rather than running off the track.
    """
    report_date = ctx.report_date
    window = ctx.bands.get("validity_days") or 30
    if not report_date:
        return None
    # Freshness is measured against today, not against anything in the payload:
    # the question is whether this report is still usable now.
    age = dates.days_between(report_date, datetime.date.today())
    return {
        "report_date": report_date,
        "age_days": age,
        "window": window,
        "valid": 0 <= age <= window,
        "expires": report_date + datetime.timedelta(days=window),
        "pct": max(0.0, min(100.0, age / float(window) * 100.0)) if window else 0.0,
    }
