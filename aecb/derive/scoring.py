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
    """score.DataIndex as a whole number, or None.

    Numeric text is accepted ("732", "732.0") -- a score delivered as text is
    still a score. A non-whole or non-numeric value is not.
    """
    value = ctx.score.get("DataIndex")
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


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
    geo = scale_geometry(ctx)
    if value is None or geo is None:
        return None
    lo, hi = geo["min"], geo["max"]
    geo.update({"value": value,
                "pct": max(0.0, min(100.0, (value - lo) / float(hi - lo) * 100.0))})
    return geo


def scale_geometry(ctx):
    """The configured scale on its own: zones and ticks, no score.

    Returns {'zones', 'ticks', 'min', 'max'}, or None for an unusable scale.
    Split out of gauge() so the dial can draw its FH zones even when no
    score came back -- the zones are config, not payload.
    """
    scale = ctx.bands.get("scale") or {}
    lo, hi = scale.get("min", 300), scale.get("max", 900)
    if hi <= lo:
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
    return {"zones": zones, "ticks": ticks, "min": lo, "max": hi}


def configured_band(ctx):
    """The FH band code the configured cut-offs put the score in, or None.

    For comparison with the DELIVERED band only -- never displayed as the
    band, because the delivered one is authoritative.
    """
    value = score_value(ctx)
    if value is None:
        return None
    code = None
    for band in ctx.bands.get("fh_bands") or []:
        if value >= band.get("from", 0):
            code = band.get("code")
    return code


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


def enquiry_anchor(ctx):
    """The date the VALIDITY verdict ages, and the enquiry scope behind it.

    Since 10 Sep 2026 this IS ctx.report_date's ladder -- the windows and the
    validity strip age the same date. The ladder lives on ReportContext
    (context.enquiry_anchor); this wrapper keeps scoring's public surface so
    shell.py and validity() need no knowledge of the move.

    Returns {'date', 'basis' ('enquiry' | 'pull' | None), 'report_type',
             'enquiry_type', 'enquiry_no', 'scope_source'} -- the scope
    strings verbatim from the winning (latest-dated) sectionStatus row, for
    the top-bar chips.
    """
    return ctx.enquiry_anchor()


def validity(ctx):
    """Report freshness against the configured look-back window.

    The aged date comes from enquiry_anchor() -- since 10 Sep 2026 the same
    ladder that resolves ctx.report_date, so the validity verdict and the
    windows age one date. Returns
    {'report_date', 'age_days', 'window', 'state', 'valid', 'expires', 'pct',
     'basis', 'report_type', 'enquiry_type', 'enquiry_no', 'scope_source'}
    -- the last four passed through from enquiry_anchor(). pct is the marker
    position on
    the meter, clamped to 0..100 so an old report pins at the end rather than
    running off the track.

    state is 'valid' (0 <= age <= window), 'expired' (age > window),
    'future' (report date after today -- a bad date or clock skew, which
    cannot be graded either way) or 'unknown' (no date on the ladder).
    valid is True only in the 'valid' state.

    When no date on the ladder resolves, every date-shaped key is None but
    the scope strings still return, so the bar can state what was pulled even
    while saying the age cannot be established.
    """
    anchor = enquiry_anchor(ctx)
    # Validated as a positive whole number when the context loads.
    window = ctx.bands["validity_days"]
    report_date = anchor["date"]
    scope = {key: anchor[key] for key in
             ("report_type", "enquiry_type", "enquiry_no", "scope_source")}
    if not report_date:
        out = {
            "report_date": None, "age_days": None, "window": window,
            "state": "unknown", "valid": None, "expires": None, "pct": None,
            "basis": None,
        }
        out.update(scope)
        return out
    # Freshness is measured against today, not against anything in the payload:
    # the question is whether this report is still usable now.
    age = dates.days_between(report_date, datetime.date.today())
    if age < 0:
        state = "future"
    elif age <= window:
        state = "valid"
    else:
        state = "expired"
    out = {
        "report_date": report_date,
        "age_days": age,
        "window": window,
        "state": state,
        "valid": state == "valid",
        "expires": report_date + datetime.timedelta(days=window),
        "pct": max(0.0, min(100.0, age / float(window) * 100.0)),
        "basis": anchor["basis"],
    }
    out.update(scope)
    return out
