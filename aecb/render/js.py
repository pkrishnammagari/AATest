"""Builds the client-side data blob and emits the page script.

report.js reads everything from window.__AECB. This module assembles that object
from the payload, so wiring a chart means changing what is built here -- the
JavaScript does not change.

Nothing in here fabricates a value. Where the payload has no data the key is
omitted or set to null, and report.js returns early rather than inventing a
series -- section 08 emits no `applications` key when no application row
carries a usable date.

The section 04 and 05 timelines are not here: they are inline SVG built in
their section modules, because whether a timeline can be drawn at all depends
on which dates the payload carries and that decision belongs beside the data.
"""

from __future__ import annotations

import json
import os

from .. import dates
from ..derive import applications, facilities
from ..loader import CATEGORY_LABEL
from . import tokens

_HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_JS = os.path.join(_HERE, "report.js")

_cache = {}

_CHART_TOKENS = (
    "red", "green", "green-mid", "amber",
    "ink-2", "ink-3", "ink-4", "line-2", "dpd-none", "red-line",
)

_CATEGORY_ORDER = ("I", "C", "N", "S")


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _status_tables(ctx) -> dict:
    codes = ctx.status_codes.get("codes") or {}
    return {
        "statusCodes": dict((k, v) for k, v in codes.items() if not k.startswith("_")),
        "roles": ctx.status_codes.get("roles") or {},
        "frequency": dict((k, v) for k, v in (ctx.status_codes.get("frequency") or {}).items()
                          if not k.startswith("_")),
        "dpdBuckets": ctx.status_codes.get("dpd_buckets") or [],
    }


def _money(value):
    """Thousands-separated string for the row stats, or None."""
    if value is None:
        return None
    try:
        return "{:,.0f}".format(float(value))
    except (TypeError, ValueError):
        return None


def _facility_row(ctx, facility) -> dict:
    """One heatmap row: identity, current stats, and the month series.

    `status` and `delays` are keyed by months-ago and contain ONLY months the
    bureau actually reported. report.js paints every other in-window month as
    "not reported" -- which is why unreported months must never be filled in
    with defaults here.
    """
    series = facility.series()

    status, delays, reported = {}, {}, []
    for month, point in enumerate(series):
        if point is None:
            continue
        reported.append(month)
        status[str(month)] = point["status"]["code"]
        if point["dpd"]:
            delays[str(month)] = {"days": point["dpd"]}

    util_series = facility.utilisation_series()
    final = facility.final_status

    row = {
        "id": facility.id,
        "name": facility.label,
        "provider": facility.provider["name"],
        "badge": facility.provider["kind"],
        "code": facility.provider["code"],
        "role": facility.role_code,
        "freq": facility.frequency_code,
        "openMonths": facility.open_months,
        "closedAtMonth": facility.closed_at_month,
        "closedOn": dates.fmt_short(facility.closed_on) if facility.closed_on else None,
        "finalStatus": final["code"] if final else None,
        "limit": _money(facility.limit),
        "os": _money(facility.balance),
        "payment": _money(facility.raw.get("PaymentAmount")),
        "util": facility.utilisation,
        "maxdpd": facility.max_dpd or 0,
        "status": status,
        "delays": delays,
        "reported": reported,
        "monthsReported": facility.months_reported,
    }

    if util_series is not None:
        row["u"] = util_series
        if facility.utilisation is not None and facility.utilisation > 100:
            row["overLimit"] = True

    installments = facility.raw.get("NoOfInstallments")
    remaining = facility.raw.get("NoOfRemainingInstallments")
    if installments:
        paid = (installments - remaining) if remaining is not None else None
        row["tenor"] = ("%d / %d" % (paid, installments)) if paid is not None \
            else "%d" % installments

    overdue = facility.overdue
    if overdue:
        row["overdueNow"] = _money(overdue)

    # A closure AECB did not date. It cannot be placed in the 6-month window,
    # so the row says so rather than leaving the blank where a date would be --
    # which would read as "closed, but not recently".
    if facility.closed and not facility.closed_on:
        row["closedUndated"] = True

    return row


CLOSED_WINDOW_MONTHS = 6


def _in_arrears(facility) -> bool:
    """Whether a facility is carrying anything adverse right now.

    Deliberately broad -- an overdue balance, a current delay, OR a current
    contract status the bureau ranks below normal. Filing a service that is in
    arrears under "no arrears" is the failure that matters in this split, so
    every signal counts and not just the money one.
    """
    if facility.overdue:
        return True
    if facility.raw.get("Current_DaysPaymentDelay"):
        return True
    status = facility.ctx.status(facility.raw.get("Current_ContractStatus"))
    return bool(status) and status["rank"] < 100


def _closed_recently(ctx, facility) -> bool:
    """Closed inside the review window.

    A closure AECB did not date cannot be placed in a window at all, and lands
    in the older bucket: claiming a recency the payload does not support is the
    worse error of the two. The row says the date was not reported rather than
    leaving a blank that reads as "not recent".
    """
    if not facility.closed_on or not ctx.report_date:
        return False
    return facility.closed_on >= dates.add_months(ctx.report_date,
                                                  -CLOSED_WINDOW_MONTHS)


def _heatmap(ctx) -> dict:
    """Four blocks, each grouped by AECB category.

    Active first, because that is the book being lent against. Then the two
    closed windows, then the active services carrying nothing adverse -- which
    are context rather than a finding, and are the reason the active block is
    not simply "everything not closed".
    """
    all_rows = facilities.all_facilities(ctx)
    active = [f for f in all_rows if not f.closed]

    quiet_services = [f for f in active
                      if f.category == "S" and not _in_arrears(f)]
    quiet_ids = set(id(f) for f in quiet_services)
    live = [f for f in active if id(f) not in quiet_ids]

    closed = [f for f in all_rows if f.closed]
    recent = [f for f in closed if _closed_recently(ctx, f)]
    older = [f for f in closed if not _closed_recently(ctx, f)]

    window = CLOSED_WINDOW_MONTHS
    blocks = [
        _block(ctx, "facActive", "Active facilities", live, False),
        _block(ctx, "facClosed6", "Closed · last %d months" % window, recent, True),
        _block(ctx, "facClosedOld", "Closed · beyond %d months" % window, older, True),
        _block(ctx, "facSvcOk", "Services — no arrears", quiet_services, True),
    ]

    data = {
        "months": facilities.WINDOW_MONTHS,
        "reportDate": _iso(ctx.report_date),
        "blocks": [b for b in blocks if b],
    }
    data.update(_status_tables(ctx))
    return data


def _block(ctx, key, label, rows, collapsed):
    """One top-level block, its facilities grouped by AECB category.

    An empty category is OMITTED rather than stated, and an empty block with
    it. Section 06 is where a category's absence is a finding; repeating it
    here would cost up to sixteen headings across four blocks to say nothing,
    which is the opposite of what this section is for.
    """
    by_cat = facilities.by_category(rows)
    groups = []
    for cat in _CATEGORY_ORDER:
        got = by_cat.get(cat) or []
        if not got:
            continue
        groups.append({
            "cat": cat,
            "label": CATEGORY_LABEL.get(cat, cat),
            "rows": [_facility_row(ctx, f) for f in got],
        })
    if not groups:
        return None
    return {"key": key, "label": label, "collapsed": collapsed,
            "n": len(rows), "groups": groups}


def build_data(ctx) -> dict:
    """The window.__AECB payload.

    Keys for unwired sections are deliberately absent: report.js returns early
    when its config is missing, leaving the chart empty rather than inventing one.
    """
    data = {
        "tokens": dict((k, tokens.TOKENS[k]) for k in _CHART_TOKENS),
        "reportDate": _iso(ctx.report_date),
        "heatmap": _heatmap(ctx),
    }

    # Section 06 used to take two keys from here -- a `utilisation` trend and a
    # `donut`. Both went with its 7 Aug 2026 rebuild: the trend chart was
    # dropped outright, and the donut became a Python-rendered line reading
    # contractsTotalSummary.CreditUtilizationRate directly. The heatmap's own
    # utilisation sub-strip is unaffected; it rides on the heatmap key below.

    # Section 08's application timeline. The split axis is computed in
    # derive/applications.py -- what counts as the focus window is a business
    # fact about the payload, not a drawing detail -- so what arrives here is
    # already positioned and report.js only places it.
    timeline = applications.timeline(ctx, ctx.rows("applications"))
    if timeline:
        data["applications"] = timeline

    return data


def script(ctx) -> str:
    """The complete <script> contents: data blob then behaviour."""
    if REPORT_JS not in _cache:
        with open(REPORT_JS, encoding="utf-8") as fh:
            _cache[REPORT_JS] = fh.read()

    # '</script>' inside a JSON string would close the tag early.
    blob = json.dumps(build_data(ctx), ensure_ascii=False).replace("</", "<\\/")
    return "window.__AECB = %s;\n%s" % (blob, _cache[REPORT_JS])


def clear_cache() -> None:
    _cache.clear()
