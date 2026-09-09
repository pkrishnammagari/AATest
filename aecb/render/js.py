"""Builds the client-side data blob and emits the page script.

report.js reads everything from window.__AECB. This module assembles that object
from the payload, so wiring a chart means changing what is built here -- the
JavaScript does not change.

Nothing in here fabricates a value. Where the payload has no data the key is
omitted or set to null, and report.js returns early rather than inventing a
series -- section 08 emits no `applications` key when no application row
carries a usable date.

The section 03 and 04 timelines are not here: they are inline SVG built in
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

# Exactly the tokens report.js reads (utilisation colours and the tooltip
# ground). Shipping the whole palette here just rots: add a name only when
# report.js gains a reader for it.
_CHART_TOKENS = ("red", "green-mid", "ink")

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


def _as_int(value):
    """Payload integer, or None -- installment counts arrive untyped."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _truthy_flag(value) -> bool:
    """Payload booleans arrive as True, 1 or 'Y' variants; None stays False --
    an unreported flag must not become a chip."""
    if value is None:
        return False
    return str(value).strip().upper() in ("1", "Y", "YES", "TRUE")


def _worst_ever(ctx, raw):
    """The contract's dated LIFETIME worst, when it says something adverse.

    Rendered as a row chip so a Default that predates the 36-month window is
    not invisible behind a clean-looking strip. Shown only when the delivered
    status ranks below normal (or cannot be ranked -- unknown is not clean),
    or a positive max delay was delivered; a lifetime of "Active Payments"
    at 0 days earns no chip.
    """
    value = raw.get("WorstStatus")
    w_status = ctx.status(value) if value is not None else None
    w_days = _as_int(raw.get("MaxDaysPaymentDelay"))
    adverse_status = w_status is not None and (
        w_status["rank"] is None or w_status["rank"] < 100)
    if not adverse_status and not w_days:
        return None

    out = {}
    if adverse_status:
        out["code"] = w_status["code"]
        out["label"] = w_status["label"]
    when = dates.parse_any(raw.get("WorstStatusDate"))
    if adverse_status and when:
        out["when"] = dates.fmt_short(when)
    if w_days:
        out["maxDays"] = w_days
        d_when = dates.parse_any(raw.get("MaxDaysPaymentDelayDate"))
        if d_when:
            out["maxDaysWhen"] = dates.fmt_short(d_when)
    if raw.get("MaxOverdueAmount"):
        max_od = _money(raw.get("MaxOverdueAmount"))
        if max_od:
            out["maxOverdue"] = max_od
            od_when = dates.parse_any(raw.get("MaxOverdueAmountDate"))
            if od_when:
                out["maxOverdueWhen"] = dates.fmt_short(od_when)
    return out


def _facility_row(ctx, facility) -> dict:
    """One heatmap row: identity, current stats, and the month series.

    `status` and `delays` are keyed by months-ago and contain ONLY months the
    bureau actually reported. report.js paints every other in-window month as
    "not reported" -- which is why unreported months must never be filled in
    with defaults here.
    """
    series = facility.series()

    status, delays, reported, no_dpd = {}, {}, [], []
    bal, od = {}, {}
    for month, point in enumerate(series):
        if point is None:
            continue
        reported.append(month)
        status[str(month)] = point["status"]["code"]
        if point["dpd"]:
            delays[str(month)] = {"days": point["dpd"]}
        elif point["dpd"] is None:
            # Status filed, delay NOT delivered. Without this the cell would
            # paint as "current (0 DPD)" -- a zero the bureau never sent.
            no_dpd.append(month)
        # The month's own money, for the cell tooltips -- the row-level
        # Current_Balance is a single snapshot and must not masquerade as a
        # monthly figure across 36 cells.
        month_bal = _money(point["balance"])
        if month_bal is not None:
            bal[str(month)] = month_bal
        if point["overdue"]:
            month_od = _money(point["overdue"])
            if month_od is not None:
                od[str(month)] = month_od

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
        # None stays None: "nothing reported" must not become "0 days late".
        "maxdpd": facility.max_dpd,
        "status": status,
        "delays": delays,
        "reported": reported,
        "monthsReported": facility.months_reported,
        "possible": facility.possible_months,
    }

    if bal:
        row["bal"] = bal
    if od:
        row["od"] = od
    if no_dpd:
        row["noDpd"] = no_dpd

    raw = facility.raw

    # Row flags and lifetime figures, shipped only when they say something --
    # an omitted key is report.js's cue to draw nothing.
    if _truthy_flag(raw.get("FlagOpenDispute")):
        row["dispute"] = True
    if _truthy_flag(raw.get("HolderIsNotLiable")):
        row["notLiable"] = True
    security = raw.get("SecurityType")
    if security or _truthy_flag(raw.get("SecuredContractFlag")):
        row["secured"] = str(security).strip() if security else ""
    amount = _money(raw.get("TotalAmount"))
    if raw.get("TotalAmount") and amount:
        row["amount"] = amount
    if raw.get("MethodOfPayment"):
        row["method"] = raw.get("MethodOfPayment")
    currency = str(raw.get("OriginalCurrency") or "").strip()
    if currency and currency.upper() != "AED":
        # The whole page renders money under the AED mark; a contract in any
        # other currency must say so on its row.
        row["currency"] = currency
    as_at = dates.parse_any(raw.get("Current_ReferenceDate"))
    if as_at:
        row["asAt"] = dates.fmt_short(as_at)

    worst_ever = _worst_ever(ctx, raw)
    if worst_ever:
        row["worstEver"] = worst_ever

    if util_series is not None:
        row["u"] = util_series
        if facility.utilisation is not None and facility.utilisation > 100:
            row["overLimit"] = True

    installments = _as_int(facility.raw.get("NoOfInstallments"))
    remaining = _as_int(facility.raw.get("NoOfRemainingInstallments"))
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
    value = facility.raw.get("Current_ContractStatus")
    if not value:
        return False
    # A delivered status the config cannot rank (rank None) counts as adverse
    # for this split: filing an unreadable status under "no arrears" is the
    # failure that matters. A status that was never delivered is no signal.
    rank = facility.ctx.status(value)["rank"]
    return rank is None or rank < 100


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
