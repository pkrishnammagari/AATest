"""Which payload variants each file exercises -- the coverage matrix.

A finding says something went wrong; this says what was TRIED. Across a
corpus it answers "have the real reports exercised the path where the score
is missing / a contract is closed without a date / the 36-month panel falls
back to the delivered figure?" -- and, more usefully, lists the variants no
real payload has hit yet, which are still covered only by the synthetic
fixtures.

Each feature is (key, section, label, test). A test reads the Env and returns
a truthy value when the payload exhibits the variant; one that raises simply
does not count (the harness records the exception, it never guesses).

Python 3.9 compatible.
"""

from __future__ import annotations

from aecb import dates
from aecb.derive import applications as d_app
from aecb.derive import facilities as d_fac
from aecb.derive import identity as d_id
from aecb.derive import income as d_income
from aecb.derive import returns as d_returns
from aecb.derive import scoring

from . import pagetext


class Env(object):
    """One payload's context, page and derived models, each built once."""

    def __init__(self, ctx, report_date, raw, page):
        self.ctx = ctx
        self.rd = report_date
        self.raw = raw
        self.page = page
        self._cache = {}

    def _get(self, key, build):
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    @property
    def worst(self):
        return self._get("worst", lambda: d_fac.worst_in_window(self.ctx))

    @property
    def income(self):
        return self._get("income", lambda: d_income.build(self.ctx))

    @property
    def returns(self):
        return self._get("returns", lambda: d_returns.build(self.ctx))

    @property
    def facs(self):
        return self._get("facs", lambda: d_fac.all_facilities(self.ctx))

    @property
    def validity(self):
        return self._get("validity", lambda: scoring.validity(self.ctx))

    @property
    def blob(self):
        return self.page.blob if self.page is not None else None

    @property
    def hm(self):
        return [r for _b, _c, r in pagetext.heatmap_rows(self.blob)]

    @property
    def timeline(self):
        return (self.blob or {}).get("applications") or {}

    def rows(self, name):
        return [r for r in self.ctx.rows(name) if isinstance(r, dict)]

    def ids(self, kind):
        return self._get("id:" + kind, lambda: d_id.identifiers(self.ctx, kind))

    def contacts(self, kind):
        return self._get("ct:" + kind, lambda: d_id.contacts(self.ctx, kind))


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status24(e):
    value = e.ctx.totals.get("WorstStatus24M")
    if value is None or not str(value).strip():
        return "missing"
    meta = e.ctx.status(value)
    rank = meta["rank"]
    if rank is None:
        return "unknown"
    return "severe" if rank <= 60 else ("adverse" if rank < 100 else "clean")


def _floor_applied(e):
    """The derived 36 months came out milder than the delivered 24."""
    d = e.ctx.status(e.ctx.totals.get("WorstStatus24M")) \
        if e.ctx.totals.get("WorstStatus24M") else None
    if not d or d["rank"] is None:
        return False
    calc = e.worst["status"] if e.worst else None
    return calc is None or calc["rank"] > d["rank"]


def _expired_doc(e, kind):
    current, _prior = e.ids(kind)
    if not current or not e.rd:
        return False
    when = dates.parse_any(current[0].extra.get("ExpiryDate"))
    return bool(when and when < e.rd)


def _expiry_disagrees(e):
    for kind in ("EmiratesId", "Passport"):
        cur, prior = e.ids(kind)
        if any(len(x.extra_by_recency("ExpiryDate")) > 1 for x in cur + prior):
            return True
    return False


def _requested(e):
    ss = e.rows("sectionStatus")
    if not ss:
        return None
    return any("bounced cheque" in str(r.get("ReportType") or "").lower()
               for r in ss)


def _fin(e, role):
    return [r for r in e.rows("contractsFinancialSummary")
            if r.get("ContractRole") == role]


FEATURES = (
    # top bar
    ("tb.dated_by_enquiry", "top bar", "Report dated by a sectionStatus enquiry",
     lambda e: e.validity["basis"] == "enquiry"),
    ("tb.dated_by_pull", "top bar", "Report dated by the DataPullDate fallback",
     lambda e: e.validity["basis"] == "pull"),
    ("tb.undated", "top bar", "No report date at all (validity unknown)",
     lambda e: e.rd is None),
    ("tb.several_enquiries", "top bar", "More than one sectionStatus row",
     lambda e: len(e.rows("sectionStatus")) > 1),
    ("tb.no_section_status", "top bar", "sectionStatus empty",
     lambda e: not e.rows("sectionStatus")),
    ("tb.blank_report_type", "top bar", "Winning enquiry has no ReportType",
     lambda e: e.validity["scope_source"] and not e.validity["report_type"]),
    ("tb.valid_now", "top bar", "Report still valid today",
     lambda e: e.validity["state"] == "valid"),
    ("tb.future_dated", "top bar", "Report date after today",
     lambda e: e.validity["state"] == "future"),

    # section 01
    ("id.no_customer", "01 identity", "customerInfo empty",
     lambda e: not e.rows("customerInfo")),
    ("id.name_composed", "01 identity", "FullNameEN absent, name composed from parts",
     lambda e: not e.ctx.customer.get("FullNameEN") and
     (e.ctx.customer.get("FirstName") or e.ctx.customer.get("LastName"))),
    ("id.name_variant", "01 identity", "Name parts spell the name differently",
     lambda e: d_id.name_parts_variant(e.ctx.customer)),
    ("id.arabic_readable", "01 identity", "Readable Arabic name",
     lambda e: d_id.arabic_name(e.ctx.customer)),
    ("id.arabic_unreadable", "01 identity", "Arabic name delivered but garbled",
     lambda e: d_id.arabic_name_unreadable(e.ctx.customer)),
    ("id.resident_unrecognised", "01 identity", "ResidentFlag not a known spelling",
     lambda e: d_id.resident_flag(e.ctx.customer)[0] is None and
     e.ctx.customer.get("ResidentFlag") is not None),
    ("id.resident_missing", "01 identity", "ResidentFlag not delivered",
     lambda e: e.ctx.customer.get("ResidentFlag") is None),
    ("id.non_resident", "01 identity", "Non-resident",
     lambda e: d_id.resident_flag(e.ctx.customer)[0] is False),
    ("id.dob_missing", "01 identity", "DOB not delivered",
     lambda e: not e.ctx.customer.get("DOB")),
    ("id.dob_unreadable", "01 identity", "DOB delivered but unreadable",
     lambda e: e.ctx.customer.get("DOB") and
     dates.parse_any(e.ctx.customer.get("DOB")) is None),
    ("id.cb_id_from_section_status", "01 identity",
     "CB subject id only in sectionStatus",
     lambda e: not e.ctx.customer.get("CBSubjectId") and e.ctx.cb_subject_id),
    ("id.no_cb_id", "01 identity", "No CB subject id anywhere",
     lambda e: e.ctx.cb_subject_id is None),
    ("id.eid_none", "01 identity", "No Emirates ID",
     lambda e: not any(e.ids("EmiratesId"))),
    ("id.eid_several_current", "01 identity", "Several current Emirates IDs",
     lambda e: len(e.ids("EmiratesId")[0]) > 1),
    ("id.eid_historical_only", "01 identity", "Emirates ID historical only",
     lambda e: not e.ids("EmiratesId")[0] and e.ids("EmiratesId")[1]),
    ("id.passport_none", "01 identity", "No passport",
     lambda e: not any(e.ids("Passport"))),
    ("id.passport_expired", "01 identity", "Headline passport expired at report date",
     lambda e: _expired_doc(e, "Passport")),
    ("id.eid_expired", "01 identity", "Headline Emirates ID expired at report date",
     lambda e: _expired_doc(e, "EmiratesId")),
    ("id.expiry_disagreement", "01 identity", "Providers disagree on a document expiry",
     _expiry_disagrees),
    ("id.mobile_several_current", "01 identity", "Several current mobiles",
     lambda e: len(e.contacts("Mobile Number")[0]) > 1),
    ("id.mobile_historical_only", "01 identity", "Mobiles historical only",
     lambda e: not e.contacts("Mobile Number")[0] and e.contacts("Mobile Number")[1]),
    ("id.mobile_invalid", "01 identity", "A mobile that is not a UAE mobile",
     lambda e: any(not d_id.is_uae_mobile(x.value)
                   for x in sum(e.contacts("Mobile Number"), []))),
    ("id.landline", "01 identity", "Phone Number (landline) rows",
     lambda e: any(e.contacts("Phone Number"))),
    ("id.no_phone", "01 identity", "No mobile and no landline",
     lambda e: not any(e.contacts("Mobile Number")) and
     not any(e.contacts("Phone Number"))),
    ("id.email_none", "01 identity", "No e-mail",
     lambda e: not any(e.contacts("E-mail"))),
    ("id.email_invalid", "01 identity", "An e-mail not shaped like one",
     lambda e: any(not d_id.is_email(x.value) for x in sum(e.contacts("E-mail"), []))),
    ("id.email_several", "01 identity", "Several e-mails",
     lambda e: len(sum(e.contacts("E-mail"), [])) > 1),
    ("id.address_partial", "01 identity", "Address row with a location but no Address",
     lambda e: any(r.get("Address") is None and
                   any(r.get(f) is not None for f in ("Emirate", "PoBox", "PlotNo"))
                   for r in e.rows("addresses"))),
    ("id.address_none", "01 identity", "No usable address",
     lambda e: not any(d_id.addresses(e.ctx))),
    ("id.address_several", "01 identity", "More than one distinct address",
     lambda e: len(sum(d_id.addresses(e.ctx), [])) > 1),

    # section 02
    ("sc.score_missing", "02 score", "No usable score",
     lambda e: scoring.score_value(e.ctx) is None),
    ("sc.score_error", "02 score", "Score error reason delivered",
     lambda e: e.ctx.score.get("ErrorDescription") or e.ctx.score.get("ErrorNumber")),
    ("sc.band_mismatch", "02 score", "Configured cut-offs disagree with delivered band",
     lambda e: scoring.fh_band(e.ctx) and scoring.configured_band(e.ctx) and
     scoring.fh_band(e.ctx)["code"] != scoring.configured_band(e.ctx)),
    ("sc.fh_band_missing", "02 score", "No FH band delivered",
     lambda e: scoring.fh_band(e.ctx) is None),
    ("sc.fh_band1_conflict", "02 score", "FHScoreBand and FHScoreBand1 differ",
     lambda e: e.ctx.score.get("FHScoreBand") and e.ctx.score.get("FHScoreBand1") and
     e.ctx.score.get("FHScoreBand") != e.ctx.score.get("FHScoreBand1")),
    ("sc.vintage_B1", "02 score", "Vintage B1 (under a year)",
     lambda e: scoring.vintage_band(e.ctx)["code"] == "B1"),
    ("sc.vintage_B2", "02 score", "Vintage B2",
     lambda e: scoring.vintage_band(e.ctx)["code"] == "B2"),
    ("sc.vintage_B3", "02 score", "Vintage B3",
     lambda e: scoring.vintage_band(e.ctx)["code"] == "B3"),
    ("sc.vintage_B4", "02 score", "Vintage B4",
     lambda e: scoring.vintage_band(e.ctx)["code"] == "B4"),
    ("sc.history_unknown", "02 score", "Bureau history length not computable",
     lambda e: scoring.history_months(e.ctx) is None),

    # section 03
    ("ws.24m_severe", "03 worst", "24-month worst is severe (rank <= 60)",
     lambda e: _status24(e) == "severe"),
    ("ws.24m_adverse", "03 worst", "24-month worst is adverse",
     lambda e: _status24(e) == "adverse"),
    ("ws.24m_clean", "03 worst", "24-month worst is clean",
     lambda e: _status24(e) == "clean"),
    ("ws.24m_missing", "03 worst", "24-month worst not delivered",
     lambda e: _status24(e) == "missing"),
    ("ws.24m_unknown", "03 worst", "24-month worst not in the status table",
     lambda e: _status24(e) == "unknown"),
    ("ws.36m_floor", "03 worst", "Derived 36 months milder than delivered 24",
     _floor_applied),
    ("ws.36m_not_derivable", "03 worst", "Nothing falls in the 36-month window",
     lambda e: e.worst is None),
    ("ws.36m_unranked", "03 worst", "Unrankable statuses inside 36 months",
     lambda e: e.worst and e.worst["unknown"]),
    ("ws.lifetime_nonzero", "03 worst", "Life-time worst status count above zero",
     lambda e: _num(e.ctx.summary.get("Worststatus"))),
    ("ws.summary_conflict", "03 worst", "summary.WorstStatus24M names another status",
     lambda e: e.ctx.summary.get("WorstStatus24M") and
     e.ctx.totals.get("WorstStatus24M") and
     e.ctx.status(e.ctx.summary.get("WorstStatus24M"))["code"] !=
     e.ctx.status(e.ctx.totals.get("WorstStatus24M"))["code"]),

    # section 04
    ("inc.none", "04 income", "No employment rows",
     lambda e: not e.rows("employment")),
    ("inc.trend", "04 income", "Chart: trend (2+ datable figures)",
     lambda e: e.income["chart"] == "trend"),
    ("inc.single", "04 income", "Chart: single figure",
     lambda e: e.income["chart"] == "single"),
    ("inc.spans", "04 income", "Chart: employment spans only",
     lambda e: e.income["chart"] == "spans"),
    ("inc.nothing_datable", "04 income", "Chart: nothing can be placed in time",
     lambda e: e.rows("employment") and e.income["chart"] == "none"),
    ("inc.placeholder", "04 income", "Placeholder income below the floor",
     lambda e: any(r.placeholder for r in e.income["records"])),
    ("inc.zero", "04 income", "Income reported as exactly zero",
     lambda e: any(_num(r.income) == 0 for r in e.income["records"])),
    ("inc.disagreement", "04 income", "Providers disagree on an employer's income",
     lambda e: any(r.income_others for r in e.income["records"])),
    ("inc.no_current", "04 income", "No employer qualifies as current",
     lambda e: e.rows("employment") and e.income["current"] is None),
    ("inc.hire_date_point", "04 income", "Figure placed at hire date (derived)",
     lambda e: e.income["inferred"]),
    ("inc.stale", "04 income", "An employment record is stale",
     lambda e: any(r.stale for r in e.income["records"])),
    ("inc.contradictory", "04 income", "Termination before hire",
     lambda e: any(r.contradictory for r in e.income["records"])),
    ("inc.disputed", "04 income", "An employment record is disputed",
     lambda e: any(r.disputed for r in e.income["records"])),
    ("inc.other_income", "04 income", "incomes rows present",
     lambda e: e.rows("incomes")),

    # section 05
    ("ret.none_checked", "05 returns", "No returns, product requested (clean)",
     lambda e: not e.rows("paymentOrder") and _requested(e) is True),
    ("ret.none_not_requested", "05 returns", "No returns, product not requested",
     lambda e: not e.rows("paymentOrder") and _requested(e) is False),
    ("ret.none_unverified", "05 returns", "No returns, no sectionStatus",
     lambda e: not e.rows("paymentOrder") and _requested(e) is None),
    ("ret.recent", "05 returns", "Returns inside the review window",
     lambda e: e.returns["recent"]),
    ("ret.older_only", "05 returns", "Returns, none inside the window",
     lambda e: e.returns["records"] and not e.returns["recent"]),
    ("ret.undated", "05 returns", "An undated return",
     lambda e: e.returns["undated"]),
    ("ret.other_type", "05 returns", "A return of an unknown instrument type",
     lambda e: any(r.kind is None for r in e.returns["records"])),
    ("ret.flag_conflict", "05 returns", "PaymentOrderFlag contradicts the rows",
     lambda e: 'class="attn"' in pagetext.aside(e.page.sec("returns"))),

    # section 06
    ("fac.coholder", "06 overview", "Co-holder (role C) figures",
     lambda e: any(_num(r.get("Balance")) for r in _fin(e, "C"))),
    ("fac.guarantor_figures", "06 overview", "Guarantor (role G) figures",
     lambda e: any(_num(r.get(f)) for r in _fin(e, "G")
                   for f in ("Balance", "CreditLimit", "OverdueAmount"))),
    ("fac.guaranteed_balance", "06 overview", "TotalBalanceGuaranteed non-zero",
     lambda e: _num(e.ctx.totals.get("TotalBalanceGuaranteed"))),
    ("fac.guaranteed_overdue", "06 overview", "TotalOverdueGuaranteed non-zero",
     lambda e: _num(e.ctx.totals.get("TotalOverdueGuaranteed"))),
    ("fac.outcomes", "06 overview", "Declined / rejected / not-taken-up counters",
     lambda e: any(_num(r.get(f)) for r in e.rows("contractsSummary")
                   for f in ("DeclinedNo", "RejectedNo", "NotTakenUpNo"))),
    ("fac.card_over_limit", "06 overview", "Card utilisation at or above 100%",
     lambda e: (_num(e.ctx.totals.get("CreditUtilizationRate")) or 0) >= 100),
    ("fac.exposure_missing", "06 overview", "TotalExposure not delivered",
     lambda e: e.ctx.totals.get("TotalExposure") is None),
    ("fac.empty_category", "06 overview", "A category card says 'No facilities'",
     lambda e: '<div class="fac empty">' in e.page.sec("facilities")),

    # section 07
    ("hm.no_contracts", "07 detail", "contracts empty",
     lambda e: not e.rows("contracts")),
    ("hm.closed_recent", "07 detail", "Closed inside the recent window",
     lambda e: any(b.get("key") == "facClosed6"
                   for b in ((e.blob or {}).get("heatmap") or {}).get("blocks") or [])),
    ("hm.closed_older", "07 detail", "Closed beyond the recent window",
     lambda e: any(b.get("key") == "facClosedOld"
                   for b in ((e.blob or {}).get("heatmap") or {}).get("blocks") or [])),
    ("hm.closed_undated", "07 detail", "Closed with no ClosedDate",
     lambda e: any(r.get("closedUndated") for r in e.hm)),
    ("hm.services_quiet", "07 detail", "Services with no arrears (folded block)",
     lambda e: any(b.get("key") == "facSvcOk"
                   for b in ((e.blob or {}).get("heatmap") or {}).get("blocks") or [])),
    ("hm.non_main_role", "07 detail", "Co-holder / guarantor contract",
     lambda e: any(r.get("role") not in ("A", None) for r in e.hm)),
    ("hm.unknown_role", "07 detail", "Contract role the config cannot read",
     lambda e: any(r.get("roleText") for r in e.hm)),
    ("hm.unknown_frequency", "07 detail", "Payment frequency the config cannot read",
     lambda e: any(r.get("freqText") for r in e.hm)),
    ("hm.dispute", "07 detail", "Contract in open dispute",
     lambda e: any(r.get("dispute") for r in e.hm)),
    ("hm.not_liable", "07 detail", "HolderIsNotLiable set",
     lambda e: any(r.get("notLiable") for r in e.hm)),
    ("hm.secured", "07 detail", "Secured contract",
     lambda e: any("secured" in r for r in e.hm)),
    ("hm.non_aed", "07 detail", "Contract in a currency other than AED",
     lambda e: any(r.get("currency") for r in e.hm)),
    ("hm.worst_ever", "07 detail", "Adverse lifetime worst chip",
     lambda e: any(r.get("worstEver") for r in e.hm)),
    ("hm.over_limit", "07 detail", "Utilisation over 100%",
     lambda e: any(r.get("overLimit") for r in e.hm)),
    ("hm.overdue_now", "07 detail", "Current overdue amount",
     lambda e: any(r.get("overdueNow") for r in e.hm)),
    ("hm.unknown_status_cell", "07 detail", "A month with an unknown status code",
     lambda e: any("?" in (r.get("status") or {}).values() for r in e.hm)),
    ("hm.status_without_dpd", "07 detail", "Status reported with no DPD delivered",
     lambda e: any(r.get("noDpd") for r in e.hm)),
    ("hm.utilisation_strip", "07 detail", "Monthly utilisation strip",
     lambda e: any(r.get("u") for r in e.hm)),
    ("hm.thin_coverage", "07 detail", "Less than half the facility-months reported",
     lambda e: e.facs and sum(f.months_reported for f in e.facs) * 2 <
     sum(f.possible_months for f in e.facs)),
    ("hm.no_history", "07 detail", "Contracts but no contractsHistory",
     lambda e: e.rows("contracts") and not e.rows("contractsHistory")),

    # section 08
    ("app.none", "08 applications", "applications empty",
     lambda e: not e.rows("applications")),
    ("app.none_datable", "08 applications", "Rows exist, none can be dated",
     lambda e: e.rows("applications") and
     not any(d_app.applied_on(r) for r in e.rows("applications"))),
    ("app.all_in_90d", "08 applications", "Every application inside 90 days",
     lambda e: e.timeline and e.timeline.get("split") == 0),
    ("app.other_phase", "08 applications", "Declined / rejected / unconfigured phase",
     lambda e: e.timeline.get("otherPhase")),
    ("app.disputed", "08 applications", "Disputed application",
     lambda e: e.timeline.get("disputed")),
    ("app.role", "08 applications", "Non-main-holder application",
     lambda e: e.timeline.get("roles")),
    ("app.lane_cap", "08 applications", "Markers hit the lane cap",
     lambda e: e.timeline.get("lanes") == d_app.MAX_LANES),
    ("app.count_mismatch", "08 applications", "Applications90D disagrees with the rows",
     lambda e: "in window" in pagetext.text(pagetext.aside(e.page.sec("applications")))),
    ("app.no_delivered_count", "08 applications", "Applications90D not delivered",
     lambda e: e.ctx.totals.get("Applications90D") is None),
)

def features(env):
    """Keys of every feature this payload exhibits. Without a rendered page
    (render crashed) the page-reading features raise and are not counted."""
    out = []
    for key, _section, _label, test in FEATURES:
        try:
            if test(env):
                out.append(key)
        except Exception:   # noqa: BLE001 -- an unmeasurable variant is not counted
            continue
    return out


def catalogue():
    return [{"key": k, "section": s, "label": l} for k, s, l, _t in FEATURES]
