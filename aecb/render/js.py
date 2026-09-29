"""Builds the client-side data blob and emits the page script.

report.js reads everything from window.__AECB. This module assembles that object
from the payload, so wiring a chart means changing what is built here -- the
JavaScript does not change.

Nothing in here fabricates a value. Where the payload has no data the key is
omitted or set to null, and report.js returns early rather than inventing a
series -- no `applications` key is emitted when no application row
carries a usable date.

The income and returns timelines are not here: they are inline SVG built in
their section modules, because whether a timeline can be drawn at all depends
on which dates the payload carries and that decision belongs beside the data.
"""

from __future__ import annotations

import json
import os

from .. import dates
from ..coerce import flag, nonzero, number, truncated
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

# The data blob sits inside an inline <script>. Escaping only "</" is not
# enough: "<!--" followed by "<script" switches the HTML tokenizer into a state
# where the real "</script>" no longer closes the element. Every character that
# can open or close markup is therefore written as a JSON \u escape, along with
# the two line separators older JS engines reject inside string literals. The
# parsed values are unchanged.
_SCRIPT_SAFE = {
    ord("<"): "\\u003c",
    ord(">"): "\\u003e",
    ord("&"): "\\u0026",
    0x2028: "\\u2028",
    0x2029: "\\u2029",
}


def json_for_script(data) -> str:
    """JSON text that is safe to place verbatim inside an inline <script>."""
    return json.dumps(data, ensure_ascii=False).translate(_SCRIPT_SAFE)


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
        # The colour-band cut-offs, so report.js grades exactly as Python does.
        "severeMax": ctx.status_codes["severity"]["severe_max"],
        "normalMin": ctx.status_codes["severity"]["normal_min"],
    }


def _money(value):
    """Thousands-separated string for the row stats, or None."""
    amount = number(value)
    return None if amount is None else "{:,.0f}".format(amount)


def _adverse_worst_status(ctx, raw):
    """The resolved lifetime WorstStatus when it ranks below normal or cannot
    be ranked (unknown is not clean); None otherwise or when not delivered."""
    value = raw.get("WorstStatus")
    if value is None:
        return None
    status = ctx.status(value)
    return status if ctx.severity(status["rank"]) != "normal" else None


def _dated(out, key, value) -> None:
    """out[key] = the short date of `value`, when it parses."""
    when = dates.parse_any(value)
    if when:
        out[key] = dates.fmt_short(when)


def _worst_ever(ctx, raw):
    """The contract's dated LIFETIME worst, when it says something adverse.

    Rendered as a row chip so a Default that predates the 36-month window is
    not invisible behind a clean-looking strip. Shown only when the delivered
    status ranks below normal (or cannot be ranked -- unknown is not clean),
    or a positive max delay was delivered; a lifetime of "Active Payments"
    at 0 days earns no chip.
    """
    status = _adverse_worst_status(ctx, raw)
    w_days = truncated(raw.get("MaxDaysPaymentDelay"))
    if status is None and not w_days:
        return None

    out = {}
    if status is not None:
        out["code"] = status["code"]
        out["label"] = status["label"]
        _dated(out, "when", raw.get("WorstStatusDate"))
    if w_days:
        out["maxDays"] = w_days
        _dated(out, "maxDaysWhen", raw.get("MaxDaysPaymentDelayDate"))
    max_od = (_money(raw.get("MaxOverdueAmount"))
              if nonzero(raw.get("MaxOverdueAmount")) else None)
    if max_od:
        out["maxOverdue"] = max_od
        _dated(out, "maxOverdueWhen", raw.get("MaxOverdueAmountDate"))
    return out


def _month_series(series) -> dict:
    """The per-month keys of a heatmap row, keyed by months-ago.

    Contains ONLY months the bureau actually reported; report.js paints every
    other in-window month as "not reported" -- which is why unreported months
    must never be filled in with defaults here.
    """
    status, delays, reported, no_dpd = {}, {}, [], []
    bal, od = {}, {}
    for month, point in enumerate(series):
        if point is None:
            continue
        key = str(month)
        reported.append(month)
        status[key] = point["status"]["code"]
        if point["dpd"]:
            delays[key] = {"days": point["dpd"]}
        elif point["dpd"] is None:
            # Status filed, delay NOT delivered. Without this the cell would
            # paint as "current (0 DPD)" -- a zero the bureau never sent.
            no_dpd.append(month)
        # The month's own money, for the cell tooltips -- the row-level
        # Current_Balance is a single snapshot and must not masquerade as a
        # monthly figure across 36 cells.
        month_bal = _money(point["balance"])
        if month_bal is not None:
            bal[key] = month_bal
        month_od = _money(point["overdue"]) if nonzero(point["overdue"]) else None
        if month_od is not None:
            od[key] = month_od
    return {"status": status, "delays": delays, "reported": reported,
            "noDpd": no_dpd, "bal": bal, "od": od}


def _row_flags(raw) -> dict:
    """Row flags and lifetime figures, shipped only when they say something
    -- an omitted key is report.js's cue to draw nothing."""
    out = {}
    if flag(raw.get("FlagOpenDispute")):
        out["dispute"] = True
    if flag(raw.get("HolderIsNotLiable")):
        out["notLiable"] = True
    security = raw.get("SecurityType")
    if security or flag(raw.get("SecuredContractFlag")):
        out["secured"] = str(security).strip() if security else ""
    amount = _money(raw.get("TotalAmount"))
    if nonzero(raw.get("TotalAmount")) and amount:
        out["amount"] = amount
    if raw.get("MethodOfPayment"):
        out["method"] = raw.get("MethodOfPayment")
    currency = str(raw.get("OriginalCurrency") or "").strip()
    if currency and currency.upper() != "AED":
        # The whole page renders money under the AED mark; a contract in any
        # other currency must say so on its row.
        out["currency"] = currency
    _dated(out, "asAt", raw.get("Current_ReferenceDate"))
    return out


def _tenor(raw):
    """'paid / total' instalments, the total alone, or None."""
    installments = truncated(raw.get("NoOfInstallments"))
    if not installments:
        return None
    remaining = truncated(raw.get("NoOfRemainingInstallments"))
    if remaining is None:
        return "%d" % installments
    return "%d / %d" % (installments - remaining, installments)


def _contract_ids(raw) -> dict:
    """The contract's own numbers, for the name hover -- what someone needs
    to raise this facility with AECB or the lender."""
    ids = {}
    if raw.get("CBContractId"):
        ids["cb"] = str(raw.get("CBContractId"))
    if raw.get("ProviderContractNo"):
        ids["lender"] = str(raw.get("ProviderContractNo"))
    return ids


def _put(row, key, value) -> None:
    """row[key] = value, only when value says something."""
    if value:
        row[key] = value


def _facility_row(ctx, facility) -> dict:
    """One heatmap row: identity, current stats, and the month series."""
    months = _month_series(facility.series())
    final = facility.final_status
    raw = facility.raw

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
        "payment": _money(raw.get("PaymentAmount")),
        "util": facility.utilisation,
        # None stays None: "nothing reported" must not become "0 days late".
        "maxdpd": facility.max_dpd,
        "status": months["status"],
        "delays": months["delays"],
        "reported": months["reported"],
        "monthsReported": facility.months_reported,
        "possible": facility.possible_months,
    }
    _put(row, "bal", months["bal"])
    _put(row, "od", months["od"])
    _put(row, "noDpd", months["noDpd"])
    row.update(_row_flags(raw))
    _put(row, "worstEver", _worst_ever(ctx, raw))

    util_series = facility.utilisation_series()
    if util_series is not None:
        row["u"] = util_series
        if facility.utilisation is not None and facility.utilisation > 100:
            row["overLimit"] = True

    _put(row, "tenor", _tenor(raw))
    if nonzero(facility.overdue):
        row["overdueNow"] = _money(facility.overdue)
    # A closure AECB did not date cannot be placed in the closed window, so
    # the row says so rather than leaving a blank that reads as "closed, but
    # not recently".
    if facility.closed and not facility.closed_on:
        row["closedUndated"] = True
    # Delivered values the config cannot read are shown as delivered rather
    # than defaulted: an unknown role is not main holder, an unknown
    # frequency is not absent.
    _put(row, "roleText", facility.role_text)
    _put(row, "freqText", facility.frequency_text)
    _put(row, "ids", _contract_ids(raw))
    return row


def _in_arrears(facility) -> bool:
    """Whether a facility is carrying anything adverse right now.

    Deliberately broad -- an overdue balance, a current delay, OR a current
    contract status the bureau ranks below normal. Filing a service that is in
    arrears under "no arrears" is the failure that matters in this split, so
    every signal counts and not just the money one.
    """
    if nonzero(facility.overdue) or nonzero(facility.raw.get("Current_DaysPaymentDelay")):
        return True
    value = facility.raw.get("Current_ContractStatus")
    if not value:
        return False
    # A delivered status the config cannot rank (rank None) counts as adverse
    # for this split: filing an unreadable status under "no arrears" is the
    # failure that matters. A status that was never delivered is no signal.
    return facility.ctx.severity(facility.ctx.status(value)["rank"]) != "normal"


def _closed_recently(ctx, facility) -> bool:
    """Closed inside the review window.

    A closure AECB did not date cannot be placed in a window at all, and lands
    in the older bucket: claiming a recency the payload does not support is the
    worse error of the two. The row says the date was not reported rather than
    leaving a blank that reads as "not recent".
    """
    if not facility.closed_on or not ctx.report_date:
        return False
    return facility.closed_on >= dates.add_months(
        ctx.report_date, -ctx.bands["closed_window_months"])


def _split_book(ctx):
    """(live, closed recently, closed earlier, quiet services)."""
    all_rows = facilities.all_facilities(ctx)
    active = [f for f in all_rows if not f.closed]
    quiet_services = [f for f in active
                      if f.category == "S" and not _in_arrears(f)]
    quiet_ids = set(id(f) for f in quiet_services)
    live = [f for f in active if id(f) not in quiet_ids]
    closed = [f for f in all_rows if f.closed]
    recent = [f for f in closed if _closed_recently(ctx, f)]
    older = [f for f in closed if not _closed_recently(ctx, f)]
    return live, recent, older, quiet_services


def _heatmap(ctx) -> dict:
    """Four blocks, each grouped by AECB category.

    Active first, because that is the book being lent against. Then the two
    closed windows, then the active services carrying nothing adverse -- which
    are context rather than a finding, and are the reason the active block is
    not simply "everything not closed".
    """
    live, recent, older, quiet_services = _split_book(ctx)

    # config/bands.json, validated as a positive whole number at load.
    window = ctx.bands["closed_window_months"]
    blocks = [
        _block(ctx, "facActive", "Active facilities", live, False),
        _block(ctx, "facClosed6", "Closed · last %d months" % window, recent, True),
        _block(ctx, "facClosedOld", "Closed · beyond %d months" % window, older, True),
        _block(ctx, "facSvcOk", "Services — no arrears", quiet_services, True),
    ]

    data = {
        "months": facilities.WINDOW_MONTHS,
        "closedWindow": window,
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

    # The facilities section's utilisation line is rendered in Python from
    # contractsTotalSummary.CreditUtilizationRate and needs no key here; the
    # heatmap's own utilisation sub-strip rides on the heatmap key above.

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

    return "window.__AECB = %s;\n%s" % (json_for_script(build_data(ctx)),
                                        _cache[REPORT_JS])


def clear_cache() -> None:
    _cache.clear()
