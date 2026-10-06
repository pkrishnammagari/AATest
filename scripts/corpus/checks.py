"""The per-payload checks.

run_payload() takes one archived API response and returns every finding the
harness can raise for it, in seven layers:

  load       the file parses and builds a ReportContext, through the same
             context.from_bytes() seam app.py uses;
  render     render_page() completes -- and when it does not, each section is
             rendered alone so the finding names the one that raised;
  no-drop    delivered rows reach the page: scripts/check_report.py's
             assertions, plus contracts, history months, applications,
             contacts and summary rows the page could lose silently;
  recompute  headline figures and pills re-derived from the RAW payload by
             the rules in docs/LowLevelArchitecture.md, then compared with
             the page. These
             restate the spec rather than call the code under test, so a
             regression cannot certify itself;
  hygiene    the page never shows None / NaN / undefined / an empty value /
             broken markup;
  vocabulary delivered values the config cannot read (they render, as
             unknown -- but somebody should decide);
  dates      date shapes the parser cannot read, events after the report date.

Nothing here edits the payload or the page. Findings are plain dicts, so the
report writer and the self-test can read them without importing this module.

Python 3.9 compatible.
"""

from __future__ import annotations

import ast
import collections
import datetime
import glob
import json
import os
import re
import time
import traceback

from aecb import context, dates
from aecb.derive import facilities as d_fac
from aecb.derive import identity as d_id
from aecb.render import sections as r_sections
from aecb.render.page import render_page

import check_report

from . import pagetext, profile, snapshot
from .registry import get as _get_check

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATEGORIES = ("I", "C", "N", "S")
ROLES = ("A", "C", "G")
MAX_DETAILS = 12


# --- plumbing ---------------------------------------------------------------

class Collector(object):
    """Findings for one payload, plus any exception a check itself raised
    (a harness bug must never masquerade as a product failure)."""

    def __init__(self):
        self.findings = []
        self.harness_errors = []

    def add(self, check_id, message, details=None, section=None, data=None):
        chk = _get_check(check_id)
        details = [str(d) for d in (details or [])]
        if len(details) > MAX_DETAILS:
            extra = len(details) - MAX_DETAILS
            details = details[:MAX_DETAILS] + ["... and %d more" % extra]
        self.findings.append({
            "check": check_id,
            "severity": chk.severity,
            "layer": chk.layer,
            "message": message,
            "details": details,
            "section": section,
            "data": data,
        })

    def guarded(self, name, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:   # noqa: BLE001 -- recorded, never swallowed
            self.harness_errors.append("%s raised %s: %s\n%s" % (
                name, type(exc).__name__, exc, "\n".join(tb_lines(exc))))
            return None


def tb_lines(exc, keep=8):
    """A compact traceback: repo-relative frames, innermost last. The
    harness's own frames are dropped -- the defect is in what it called."""
    out = []
    for frame in traceback.extract_tb(exc.__traceback__):
        name = frame.filename
        if name.startswith(REPO):
            name = os.path.relpath(name, REPO)
        else:
            name = os.path.basename(name)
        if name.startswith(os.path.join("scripts", "corpus")):
            continue
        out.append("%s:%d in %s(): %s" % (name, frame.lineno, frame.name,
                                          (frame.line or "").strip()))
    out = out[-keep:]
    out.append("%s: %s" % (type(exc).__name__, exc))
    return out


def rows(ctx, name):
    """A payload array's dict rows. Anything else is a shape problem the
    render layer reports; the payload checks simply skip it."""
    return [r for r in ctx.rows(name) if isinstance(r, dict)]


def number(value):
    """float(value), or None -- bools excluded (True is not a figure)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def fmt0(value):
    """The page's money / count format: thousands-separated, no decimals."""
    n = number(value)
    return "{:,.0f}".format(n) if n is not None else None


def esc(value):
    """components.esc() without the dash -- the markup a payload value
    becomes."""
    text = str(value)
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        text = text.replace(a, b)
    return text


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def ladder(ctx):
    """The report date, restated from docs/LowLevelArchitecture.md (top bar): the latest
    parseable sectionStatus 'Last EnquiryDate', array order breaking ties,
    else score.DataPullDate, else None. Returns (date, basis)."""
    best = None
    for row in rows(ctx, "sectionStatus"):
        parsed = dates.parse_any(row.get("Last EnquiryDate"))
        if parsed and (best is None or parsed > best):
            best = parsed
    if best is not None:
        return best, "enquiry"
    pulled = dates.parse_any(ctx.score.get("DataPullDate"))
    return (pulled, "pull") if pulled else (None, None)


def strict_status(ctx, value):
    """The configured status a text names -- code or label -- or None.
    Mirrors the spec for section 03: resolve strictly, never guess. Labels
    match with hyphens, spacing and case ignored ('Write Off' is
    'Write-off', signed off) -- restated here, not imported, so a
    regression in aecb/context.py cannot certify itself."""
    if value is None:
        return None
    codes = ctx.status_codes.get("codes") or {}
    text = str(value).strip()
    if text in codes:
        return codes[text]
    for meta in codes.values():
        if isinstance(meta, dict) and \
                _label_key(meta.get("label") or "") == _label_key(text):
            return meta
    return None


def _label_key(text):
    return " ".join(str(text).replace("-", " ").split()).lower()


def grade(meta):
    """(tone, state) by the bureau rank: <=60 red, <100 amber, else green;
    unresolved -> uncoloured."""
    if not meta:
        return None, "unknown"
    rank = meta.get("rank", 100)
    if rank <= 60:
        return "red", "severe"
    if rank < 100:
        return "amber", "adverse"
    return "green", "clean"


def is_closed(contract):
    return str(contract.get("ActiveFlag") or "").strip().lower() == "closed"


def applied_on(row):
    """Section 08's placement date, as the code reads it."""
    return dates.parse_any(row.get("LastUpdateDate") or row.get("DateOfLastUpdate"))


_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?: [A-Za-z0-9_]+)?$")
_code_fields = None


def code_fields():
    """Every identifier-shaped string literal in aecb/ -- the field names the
    code can possibly read. Docstrings never match the shape."""
    global _code_fields
    if _code_fields is None:
        names = set()
        for path in glob.glob(os.path.join(REPO, "aecb", "**", "*.py"),
                              recursive=True):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and _FIELD_RE.match(node.value):
                    names.add(node.value)
        _code_fields = names
    return _code_fields


def _delivered_strings(payload):
    """Every string value in the payload, for telling a leaked token from a
    value the bureau actually sent (which the page shows verbatim)."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and node.strip():
            out.append(node.strip())
    walk(payload)
    return "\n".join(out)


def delivered_in(token, text, delivered):
    """Whether `token` in `text` is explained by a delivered value: some
    payload string containing the token appears in that same text. A bare
    'None' in a hover is a leak even if 'None of the above' was delivered
    elsewhere."""
    if token not in delivered:
        return False
    return any(token in s and s in text for s in delivered.split("\n"))


# --- entry point ---------------------------------------------------------------

def run_payload(path, keep_html=False, slow_seconds=5.0):
    """Every check for one file. Returns the result dict the report reads."""
    name = os.path.basename(path)
    col = Collector()
    result = {"file": name, "path": path, "render_ms": None, "features": [],
              "snapshot": None, "fields": {}, "html": None}

    # -- load -----------------------------------------------------------------
    try:
        with open(path, "rb") as fh:
            raw_bytes = fh.read()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:   # noqa: BLE001
        col.add("load.json", "%s: %s" % (type(exc).__name__, exc))
        return _finish(result, col)
    if not isinstance(payload, dict):
        col.add("load.shape", "top level is a %s, not an object"
                % type(payload).__name__)
        return _finish(result, col)
    result["fields"] = _field_inventory(payload)

    try:
        # The same seam app.py feeds: bytes in, ReportContext out.
        ctx = context.from_bytes(raw_bytes, source_name=name)
    except Exception as exc:   # noqa: BLE001
        col.add("load.context", "%s: %s" % (type(exc).__name__, exc),
                details=tb_lines(exc))
        return _finish(result, col)
    if not any(ctx.rows(k) for k in ("customerInfo", "summary", "score")):
        col.add("load.shape", "no customerInfo, summary or score row -- "
                "app.py would have rejected this response")

    report_date, _basis = ladder(ctx)
    delivered = _delivered_strings(payload)

    # -- payload-level checks (need no page) ---------------------------------
    for fn in PAYLOAD_CHECKS:
        col.guarded(fn.__name__, fn, ctx, report_date, col)

    # -- render ------------------------------------------------------------------
    started = time.perf_counter()
    try:
        raw = render_page(ctx)
    except Exception as exc:   # noqa: BLE001
        raw = None
        col.add("render.page", "%s: %s" % (type(exc).__name__, exc),
                details=tb_lines(exc))
        _localise(ctx, col)
    result["render_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    if raw is not None and result["render_ms"] > slow_seconds * 1000.0:
        col.add("perf.slow", "render took %.1f s" % (result["render_ms"] / 1000.0))

    page = None
    if raw is not None:
        page = col.guarded("page_checks", _page_checks, ctx, raw, report_date,
                           delivered, col)
        if keep_html:
            result["html"] = raw

    # -- coverage profile and baseline facts ----------------------------------
    env = profile.Env(ctx, report_date, raw, page)
    result["features"] = col.guarded("profile", profile.features, env) or []
    result["snapshot"] = col.guarded("snapshot", snapshot.facts, env)
    result["delivered"] = delivered
    return _finish(result, col)


def check_rendered(ctx, raw, payload):
    """The page-level checks alone, on a page supplied by the caller -- the
    self-test uses it to prove each check fires on a deliberately broken page.
    Returns (findings, harness_errors)."""
    col = Collector()
    rd, _basis = ladder(ctx)
    _page_checks(ctx, raw, rd, _delivered_strings(payload), col)
    return col.findings, col.harness_errors


def _finish(result, col):
    result["findings"] = col.findings
    result["harness_errors"] = col.harness_errors
    return result


def _field_inventory(payload):
    """{array: sorted field names} -- for the corpus-level schema drift view."""
    out = {}
    for name, value in payload.items():
        fields = set()
        for row in value if isinstance(value, list) else [value]:
            if isinstance(row, dict):
                fields.update(str(k).strip() for k in row)
        out[str(name)] = sorted(fields)
    return out


def _localise(ctx, col):
    """render_page raised: render each part alone to name the culprit."""
    from aecb.render import js, shell
    parts = [("top bar (render/shell.topbar)", lambda: shell.topbar(ctx)),
             ("page blob (render/js.build_data)", lambda: js.build_data(ctx))]
    for i, mod in enumerate(r_sections.flat_sections(), start=1):
        meta = dict(mod.META)
        meta["sid"], meta["no"] = "s%d" % i, "%02d" % i
        label = "section %02d (render/sections/%s.py)" % (
            i, mod.__name__.rsplit(".", 1)[-1])
        parts.append((label, (lambda m=mod, mt=meta: m.render(ctx, mt))))
    for label, fn in parts:
        try:
            fn()
        except Exception as exc:   # noqa: BLE001
            col.add("render.section", "%s raised %s: %s"
                    % (label, type(exc).__name__, exc), details=tb_lines(exc))


# --- payload-level checks -----------------------------------------------------------

def _vocab_finding(col, check_id, noun, counter, config):
    """One finding per check: every unreadable value, with where and how often."""
    if not counter:
        return
    values = [{"field": f, "value": v, "count": n}
              for (f, v), n in sorted(counter.items(), key=lambda kv: -kv[1])]
    col.add(check_id, "%s not in %s" % (plural(len(values), noun), config),
            details=["%s = %r x%d" % (x["field"], x["value"], x["count"])
                     for x in values],
            data={"values": values})


def check_unknown_arrays(ctx, rd, col):
    unknown = ctx.unknown_arrays
    if unknown:
        col.add("nodrop.unknown_arrays",
                "%s the loader does not know: %s"
                % (plural(len(unknown), "top-level key"), ", ".join(unknown)),
                data={"values": [{"field": "(top level)", "value": u, "count": 1}
                                 for u in unknown]})


def check_contact_types(ctx, rd, col):
    shown = ("mobile number", "phone number", "additional mobile number",
             "e-mail")
    lost = collections.Counter()
    for row in rows(ctx, "contacts"):
        base = d_id.base_type(row.get("ContactType"))
        if base.lower() not in shown and row.get("Contact") is not None:
            lost[("contacts.ContactType", base or "(missing)")] += 1
    if lost:
        n = sum(lost.values())
        col.add("nodrop.contacts_type",
                "%s never reach section 01 (type not shown)"
                % plural(n, "contact row"),
                details=["%s = %r x%d" % (f, v, c) for (f, v), c in lost.items()],
                section="identity",
                data={"values": [{"field": f, "value": v, "count": c}
                                 for (f, v), c in lost.items()]})


def check_summary_rows(ctx, rd, col):
    """Section 06 reads contractsFinancialSummary / contractsSummary by exact
    ContractRole A/C/G and category I/C/N/S; one row per pair."""
    problems = []
    for array, fields in (("contractsFinancialSummary",
                           ("Balance", "CreditLimit", "OverdueAmount",
                            "PaymentAmount")),
                          ("contractsSummary",
                           ("TotalNo", "ActiveNo", "ClosedNo", "DeclinedNo",
                            "RejectedNo", "NotTakenUpNo"))):
        seen = collections.Counter()
        for row in rows(ctx, array):
            role, cat = row.get("ContractRole"), row.get("ContractCategory")
            carries = [f for f in fields if number(row.get(f))]
            if role in ROLES and cat in CATEGORIES:
                seen[(role, cat)] += 1
                if seen[(role, cat)] == 2:
                    problems.append("%s has more than one row for role %s, "
                                    "category %s -- only the last is shown"
                                    % (array, role, cat))
            elif carries:
                problems.append("%s row role=%r category=%r carries %s but "
                                "the page has no place for it"
                                % (array, role, cat, ", ".join(carries)))
    if problems:
        col.add("nodrop.fin_summary_role",
                "%s in section 06's source rows" % plural(len(problems), "problem"),
                details=problems, section="facilities")


def check_history(ctx, rd, col):
    """Orphan, future and colliding contractsHistory rows."""
    contract_ids = set()
    loose_ids = set()
    for c in rows(ctx, "contracts"):
        cid = c.get("CBContractId")
        try:
            contract_ids.add(cid)
        except TypeError:
            pass
        loose_ids.add(str(cid).strip())

    orphans = collections.Counter()
    type_mismatch = collections.Counter()
    future = collections.Counter()
    months = collections.defaultdict(list)
    for row in rows(ctx, "contractsHistory"):
        cid = row.get("CBContractId")
        try:
            joined = cid in contract_ids
        except TypeError:
            joined = False
        if not joined:
            if str(cid).strip() in loose_ids:
                type_mismatch[repr(cid)] += 1
            else:
                orphans[repr(cid)] += 1
            continue
        if rd is None:
            continue
        idx = d_fac.month_index(rd, row.get("ReferenceDate"))
        if idx is None:
            continue
        if idx < 0:
            future[repr(cid)] += 1
        elif idx < d_fac.WINDOW_MONTHS:
            months[(repr(cid), idx)].append(row)

    if orphans or type_mismatch:
        details = ["CBContractId %s: %s" % (k, plural(n, "row"))
                   for k, n in orphans.most_common()]
        details += ["CBContractId %s: %s -- matches a contract only as text "
                    "(type differs), so the join misses it" % (k, plural(n, "row"))
                    for k, n in type_mismatch.most_common()]
        col.add("nodrop.history_orphan",
                "%s match no contract and are never drawn"
                % plural(sum(orphans.values()) + sum(type_mismatch.values()),
                         "history row"),
                details=details, section="detail")
    if future:
        col.add("nodrop.history_future",
                "%s dated after the report month (%s) are dropped"
                % (plural(sum(future.values()), "history row"),
                   dates.fmt_month_year(rd)),
                details=["CBContractId %s: %s" % (k, plural(n, "row"))
                         for k, n in future.most_common()],
                section="detail")

    sig_fields = ("ContractStatus", "DaysPaymentDelay", "Balance",
                  "OverdueAmount", "UtilizationRate")
    clashes = []
    for (cid, idx), group in sorted(months.items()):
        if len(group) < 2:
            continue
        differing = [f for f in sig_fields
                     if len(set(str(r.get(f)) for r in group)) > 1]
        if differing:
            clashes.append("CBContractId %s, %s: %d rows differing in %s" % (
                cid, dates.fmt_month_year(dates.add_months(rd, -idx)),
                len(group), "; ".join(
                    "%s %s" % (f, " vs ".join(repr(r.get(f)) for r in group[:3]))
                    for f in differing)))
    if clashes:
        col.add("nodrop.history_duplicate_month",
                "%s carry different history rows for the same month; the "
                "heatmap keeps only the last" % plural(len(clashes), "contract-month"),
                details=clashes, section="detail")


def check_application_dates(ctx, rd, col):
    apps = rows(ctx, "applications")
    undated = [r for r in apps if applied_on(r) is None]
    if undated and len(undated) < len(apps):
        col.add("nodrop.applications_undated",
                "%s of %d have no usable LastUpdateDate / DateOfLastUpdate and "
                "are not on the timeline" % (plural(len(undated), "application row"),
                                             len(apps)),
                details=["CBApplicationId %s: LastUpdateDate=%r DateOfLastUpdate=%r"
                         % (r.get("CBApplicationId"), r.get("LastUpdateDate"),
                            r.get("DateOfLastUpdate")) for r in undated],
                section="applications")


def check_vocabulary(ctx, rd, col):
    status = collections.Counter()
    for array, field in (("contractsHistory", "ContractStatus"),
                         ("contracts", "Current_ContractStatus"),
                         ("contracts", "WorstStatus"),
                         ("contractsTotalSummary", "WorstStatus24M"),
                         ("summary", "WorstStatus24M")):
        for row in rows(ctx, array):
            value = row.get(field)
            if value is not None and str(value).strip() \
                    and ctx.status(value)["rank"] is None:
                status[("%s.%s" % (array, field), str(value))] += 1
    _vocab_finding(col, "vocab.status", "status value",
                   status, "config/status_codes.json codes")

    role_map = ctx.status_codes.get("role_labels") or {}
    roles = collections.Counter()
    for array in ("contracts", "applications"):
        for row in rows(ctx, array):
            text = str(row.get("Role") or "").strip()
            if text and text not in role_map:
                roles[("%s.Role" % array, text)] += 1
    _vocab_finding(col, "vocab.role", "role", roles,
                   "config/status_codes.json role_labels")

    longs = set(str(m.get("long", "")).strip().lower()
                for k, m in (ctx.status_codes.get("frequency") or {}).items()
                if not k.startswith("_") and isinstance(m, dict))
    freq = collections.Counter()
    for row in rows(ctx, "contracts"):
        text = str(row.get("PaymentFrequency") or "").strip()
        if text and text.lower() not in longs:
            freq[("contracts.PaymentFrequency", text)] += 1
    _vocab_finding(col, "vocab.frequency", "payment frequency", freq,
                   "config/status_codes.json frequency")

    phases = collections.Counter()
    for row in rows(ctx, "applications"):
        value = row.get("Phase")
        if value is not None and str(value).strip() \
                and ctx.phase(value)["code"] is None:
            phases[("applications.Phase", str(value))] += 1
    _vocab_finding(col, "vocab.phase", "application phase", phases,
                   "config/status_codes.json application_phases")

    cats = collections.Counter()
    for array in ("contracts", "contractsHistory", "contractsSummary",
                  "contractsFinancialSummary"):
        for row in rows(ctx, array):
            value = row.get("ContractCategory")
            if value not in CATEGORIES:
                cats[("%s.ContractCategory" % array,
                      "(missing)" if value is None else str(value))] += 1
    _vocab_finding(col, "vocab.category", "contract category", cats,
                   "I / C / N / S (aecb/loader.py CATEGORY_CANON)")

    flags = collections.Counter()
    for row in rows(ctx, "contracts"):
        value = row.get("ActiveFlag")
        if str(value or "").strip().lower() not in ("active", "closed"):
            flags[("contracts.ActiveFlag",
                   "(missing)" if value is None else str(value))] += 1
    _vocab_finding(col, "vocab.active_flag", "ActiveFlag value", flags,
                   "Active / Closed -- read as open")

    cfg = ctx.returns_cfg or {}
    labels = set(str(v).strip().lower() for v in (cfg.get("types") or {}).values())
    tones = set(str(k).strip().lower() for k in (cfg.get("severity_tones") or {}))
    ret = collections.Counter()
    for row in rows(ctx, "paymentOrder"):
        kind = str(row.get("Type") or "").strip().lower()
        if kind and kind not in labels and "cheque" not in kind \
                and "check" not in kind and "direct debit" not in kind:
            ret[("paymentOrder.Type", str(row.get("Type")))] += 1
        sev = str(row.get("Severity") or "").strip()
        if sev and sev.lower() not in tones:
            ret[("paymentOrder.Severity", sev)] += 1
    _vocab_finding(col, "vocab.returns", "returns value", ret,
                   "config/returns.json")

    band = collections.Counter()
    fh_codes = set(b.get("code") for b in ctx.bands.get("fh_bands") or [])
    for field in ("FHScoreBand", "FHScoreBand1"):
        value = ctx.score.get(field)
        if value and value not in fh_codes:
            band[("score.%s" % field, str(value))] += 1
    ranges = ctx.bands.get("aecb_ranges") or {}
    letter = ctx.score.get("DataRange")
    if letter and (letter not in ranges or str(letter).startswith("_")):
        band[("score.DataRange", str(letter))] += 1
    _vocab_finding(col, "vocab.score_band", "score band", band,
                   "config/bands.json")

    raw_flag = ctx.customer.get("ResidentFlag")
    if raw_flag is not None and not isinstance(raw_flag, bool) and \
            str(raw_flag).strip().lower() not in ("true", "y", "yes", "1",
                                                  "false", "n", "no", "0"):
        _vocab_finding(col, "vocab.resident", "ResidentFlag value",
                       collections.Counter({("customerInfo.ResidentFlag",
                                             str(raw_flag)): 1}),
                       "the recognised spellings")

    infos = collections.Counter()
    for row in rows(ctx, "identification"):
        base = d_id.base_type(row.get("InfoType"))
        if base.lower() not in ("emiratesid", "passport"):
            infos[("identification.InfoType", base or "(missing)")] += 1
    _vocab_finding(col, "vocab.info_type", "identification type", infos,
                   "the section 01 tiles (EmiratesId, Passport)")

    known = (ctx.providers.get("providers") or {})
    prov = collections.Counter()
    for array, value in _all_values(ctx, ("ProviderNo", "ProviderNO")):
        text = str(value).strip()
        if text and text not in known:
            prov[("%s.ProviderNo" % array, text)] += 1
    _vocab_finding(col, "vocab.provider", "provider code", prov,
                   "config/providers.json")


def _all_values(ctx, fields):
    for array in ctx.data:
        if array.startswith("_"):
            continue
        for row in rows(ctx, array):
            for field in fields:
                if row.get(field) is not None:
                    yield array, row.get(field)


# Event dates checked against the report date. The lifetime-worst dates are
# month-end "as at" stamps (the synthetic fixture dates them 31 Jul for a
# 28 Jul enquiry, like the bureau's own reference dates), so those compare by
# calendar month; everything else by day.
_MONTHLY_FIELDS = ("WorstStatusDate", "MaxDaysPaymentDelayDate",
                   "MaxOverdueAmountDate")
_FUTURE_FIELDS = (
    ("contracts", "OpenDate"), ("contracts", "WorstStatusDate"),
    ("contracts", "MaxDaysPaymentDelayDate"), ("contracts", "MaxOverdueAmountDate"),
    ("applications", "LastUpdateDate"), ("applications", "DateOfLastUpdate"),
    ("paymentOrder", "ReturnDate"), ("employment", "DateOfEmployment"),
    ("employment", "DateOfLastUpdate"), ("incomes", "DateOfLastUpdate"),
    ("customerInfo", "DOB"), ("identification", "DateOfLastUpdate"),
    ("contacts", "DateOfLastUpdate"), ("addresses", "DateOfLastUpdate"),
)


def check_dates(ctx, rd, col):
    if rd is None:
        col.add("dates.no_report_date",
                "neither a parseable sectionStatus 'Last EnquiryDate' nor "
                "score.DataPullDate: validity, windows, heatmap months and the "
                "applications timeline are all unanchored",
                details=["sectionStatus Last EnquiryDate values: %r" % [
                    r.get("Last EnquiryDate") for r in rows(ctx, "sectionStatus")],
                    "score.DataPullDate: %r" % ctx.score.get("DataPullDate")])

    read = code_fields()
    bad = collections.Counter()
    samples = {}
    for array in ctx.data:
        if array.startswith("_"):
            continue
        for row in rows(ctx, array):
            for field, value in row.items():
                if value is None or ("Date" not in field and field != "DOB"):
                    continue
                if field not in read:
                    continue
                if dates.parse_any(value) is None:
                    key = ("%s.%s" % (array, field), None)
                    bad[key] += 1
                    samples.setdefault(key, [])
                    if len(samples[key]) < 3 and value not in samples[key]:
                        samples[key].append(value)
    if bad:
        values = [{"field": f, "value": ", ".join(repr(s) for s in samples[(f, v)]),
                   "count": n} for (f, v), n in bad.most_common()]
        col.add("dates.unparseable",
                "%s hold values dates.parse_any() cannot read -- they read as absent"
                % plural(len(values), "date field"),
                details=["%s x%d, e.g. %s" % (x["field"], x["count"], x["value"])
                         for x in values],
                data={"values": values})

    if rd is None:
        return
    late = collections.Counter()
    for array, field in _FUTURE_FIELDS:
        monthly = field in _MONTHLY_FIELDS
        for row in rows(ctx, array):
            parsed = dates.parse_any(row.get(field))
            if not parsed:
                continue
            after = ((parsed.year, parsed.month) > (rd.year, rd.month)
                     if monthly else parsed > rd)
            if after:
                late[("%s.%s" % (array, field), parsed.isoformat())] += 1
    for row in rows(ctx, "contracts"):
        parsed = dates.parse_any(row.get("ClosedDate"))
        if is_closed(row) and parsed and parsed > rd:
            late[("contracts.ClosedDate (closed)", parsed.isoformat())] += 1
    if late:
        by_field = collections.Counter()
        latest = {}
        for (field, when), n in late.items():
            by_field[field] += n
            latest[field] = max(latest.get(field, when), when)
        col.add("dates.future",
                "%s dated after the report date %s"
                % (plural(sum(by_field.values()), "value"), rd.isoformat()),
                details=["%s x%d (latest %s)" % (f, n, latest[f])
                         for f, n in by_field.most_common()])


PAYLOAD_CHECKS = (check_unknown_arrays, check_contact_types, check_summary_rows,
                  check_history, check_application_dates, check_vocabulary,
                  check_dates)


# --- page-level checks ----------------------------------------------------------

class Page(object):
    """The rendered page, read once and shared by every page check."""

    def __init__(self, raw):
        self.raw = raw
        self.secs, self.structure = pagetext.sections(raw)
        self.reader = pagetext.read(raw)
        self.blob = None
        self.blob_error = None
        try:
            self.blob = pagetext.blob(raw)
        except pagetext.BlobError as exc:
            self.blob_error = str(exc)

    def sec(self, name):
        return self.secs.get(name) or ""

    def aside_text(self, name):
        return pagetext.text(pagetext.aside(self.sec(name)))


def _page_checks(ctx, raw, rd, delivered, col):
    page = Page(raw)

    try:
        problems = check_report.check_page(ctx, raw)
    except Exception as exc:   # noqa: BLE001
        col.harness_errors.append("check_report.check_page raised %s: %s\n%s"
                                  % (type(exc).__name__, exc,
                                     "\n".join(tb_lines(exc))))
        problems = []
    for problem in problems:
        col.add("gate.check_report", problem)

    for problem in page.structure:
        col.add("hygiene.structure", problem)

    for fn in PAGE_CHECKS:
        col.guarded(fn.__name__, fn, ctx, page, rd, delivered, col)
    return page


# hygiene -----------------------------------------------------------------------

_TOKENS = (
    ("None", re.compile(r"\bNone\b"), True),
    ("NaN", re.compile(r"\bNaN\b"), True),
    ("nan", re.compile(r"\bnan\b"), True),
    ("undefined", re.compile(r"\bundefined\b"), True),
    ("Infinity", re.compile(r"\bInfinity\b"), True),
    ("[object Object]", re.compile(r"\[object Object\]"), True),
    ("Invalid Date", re.compile(r"Invalid Date"), True),
    ("Python repr", re.compile(r"datetime\.date(?:time)?\(|Decimal\(|object at "
                               r"0x|Traceback \(most recent"), True),
    ("format code", re.compile(r"(?<![\w%])%[sdrf](?![A-Za-z])|%\([a-z_]+\)[sd]"
                               r"|\{[a-z_0-9]*\}"), True),
    # Hovers legitimately name null fields ("AECB left DateOfLastUpdate null").
    ("null", re.compile(r"\bnull\b"), False),
)
_NEGATIVE = re.compile(r"(?<![\w.\-−])-\d[\d,]*(?:\.\d+)?\s?"
                       r"(?:days?|months?|mo|yrs?|years?)\b")
_SCI = re.compile(r"(?<![\w.])\d+(?:\.\d+)?[eE][+-]\d+\b")
_EMPTY = (
    (re.compile(r'<span class="v[^"]*">\s*</span>'), "an empty value span"),
    (re.compile(r"<b(?: [^>]*)?>\s*</b>"), "an empty <b>"),
    (re.compile(r'<span class="tag[^"]*"(?: [^>]*)?>\s*</span>'), "an empty pill"),
    (re.compile(r'<div class="es-msg">\s*</div>'), "an empty empty-state message"),
)


def _snippet(text, start, end, pad=45):
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    return ("..." if left else "") + text[left:right].replace("\n", " ") + \
        ("..." if right < len(text) else "")


def check_hygiene(ctx, page, rd, delivered, col):
    names = pagetext.section_names_by_id()
    hits = collections.defaultdict(list)
    negative, sci = [], []
    sources = [(sid, "text", t) for sid, t in page.reader.texts] + \
              [(sid, "hover", v) for sid, _k, v in page.reader.attrs]
    for sid, kind, value in sources:
        where = names.get(sid, sid)
        for label, pattern, in_hovers in _TOKENS:
            if kind == "hover" and not in_hovers:
                continue
            for m in pattern.finditer(value):
                if delivered_in(m.group(0), value, delivered):
                    continue
                hits[label].append("[%s %s] %s" % (where, kind,
                                                   _snippet(value, m.start(), m.end())))
        for m in _NEGATIVE.finditer(value):
            negative.append("[%s %s] %s" % (where, kind,
                                            _snippet(value, m.start(), m.end())))
        for m in _SCI.finditer(value):
            if not delivered_in(m.group(0), value, delivered):
                sci.append("[%s %s] %s" % (where, kind,
                                           _snippet(value, m.start(), m.end())))
    for label, found in hits.items():
        col.add("hygiene.token", "%r appears %s on the page"
                % (label, plural(len(found), "time")), details=found)
    if negative:
        col.add("hygiene.negative", "%s on the page"
                % plural(len(negative), "negative duration"), details=negative)
    if sci:
        col.add("hygiene.sci_notation", "%s in scientific notation"
                % plural(len(sci), "number"), details=sci)

    spans = [(m.start(), m.end(), names.get(m.group(2), m.group(2)))
             for m in pagetext.SECTION_RE.finditer(page.raw)]
    empties = []
    for pattern, label in _EMPTY:
        for m in pattern.finditer(page.raw):
            where = next((n for a, b, n in spans if a <= m.start() < b), "page")
            empties.append("[%s] %s: %s" % (where, label,
                                            _snippet(page.raw, m.start(), m.end(), 60)))
    if empties:
        col.add("hygiene.empty_value", "%s rendered empty"
                % plural(len(empties), "value slot"), details=empties)

    markup = list(page.reader.nesting)
    dupes = sorted(k for k, n in page.reader.ids.items() if n > 1)
    if dupes:
        markup.append("duplicate element id(s): %s" % ", ".join(dupes))
    if markup:
        col.add("hygiene.markup", markup[0] if len(markup) == 1 else
                "%s in the page markup" % plural(len(markup), "problem"),
                details=markup if len(markup) > 1 else None)


def check_blob(ctx, page, rd, delivered, col):
    if page.blob_error:
        col.add("hygiene.blob", page.blob_error)
        return
    leaks = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, "%s.%s" % (path, k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, "%s[%d]" % (path, i))
        elif isinstance(node, str) and node.strip() in (
                "None", "nan", "NaN", "undefined", "null", "Infinity") \
                and not delivered_in(node.strip(), node, delivered):
            leaks.append("%s = %r" % (path, node))
    walk(page.blob, "__AECB")
    if leaks:
        col.add("hygiene.blob", "%s carry a Python/JS placeholder string"
                % plural(len(leaks), "blob value"), details=leaks)


# recompute ---------------------------------------------------------------------

_VALIDITY = {"valid": "Report valid", "expired": "Report expired",
             "future": "Future-dated", "unknown": "Validity unknown"}
_PILL_RE = re.compile(r'<span class="tb-valid(?: [a-z]+)?" data-info="[^"]*">'
                      r'<span class="pd"></span>([^<]*)</span>')


def check_validity(ctx, page, rd, delivered, col):
    window = ctx.bands["validity_days"]
    if rd is None:
        state, age = "unknown", None
    else:
        age = (datetime.date.today() - rd).days
        state = "future" if age < 0 else ("valid" if age <= window else "expired")
    m = _PILL_RE.search(page.raw)
    if not m:
        col.add("recompute.validity", "the top-bar validity pill is missing")
        return
    got = m.group(1).strip()
    if got != _VALIDITY[state]:
        col.add("recompute.validity", "pill reads %r, expected %r"
                % (got, _VALIDITY[state]),
                details=["report date %s, age %s days, window %d days"
                         % (rd, age, window)])


def check_identity(ctx, page, rd, delivered, col):
    sec = page.sec("identity")
    cust = ctx.customer
    if not sec or not cust:
        return
    txt = pagetext.text(sec)

    dob_raw = cust.get("DOB")
    dob = dates.parse_any(dob_raw)
    if not dob_raw:
        want = "DOB not reported"
    elif dob is None:
        want = "unreadable date"
    elif rd is None:
        want = "age unknown — no report date"
    else:
        months = dates.months_between(dob, rd)
        want = "%d yrs (%s)" % (months // 12, dates.fmt_short(dob))
    if want not in txt:
        col.add("recompute.age", "expected %r in section 01" % want,
                details=["DOB %r, report date %s" % (dob_raw, rd)],
                section="identity")

    flag = cust.get("ResidentFlag")
    if isinstance(flag, bool):
        want = "Resident" if flag else "Non-resident"
    elif flag is None:
        want = "Residency not reported"
    else:
        low = str(flag).strip().lower()
        want = ("Resident" if low in ("true", "y", "yes", "1") else
                "Non-resident" if low in ("false", "n", "no", "0") else
                "Residency: %s" % str(flag).strip())
    pills = [pagetext.text(p) for p in re.findall(
        r'<span class="tag[^"]*"[^>]*>.*?</span>', pagetext.aside(sec), re.S)]
    if want not in pills:
        col.add("recompute.residency", "residency pill reads %r, expected %r"
                % (pills, want), details=["ResidentFlag %r" % (flag,)],
                section="identity")


def _score_value(ctx):
    value = ctx.score.get("DataIndex")
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    n = number(value)
    return int(n) if n is not None and n.is_integer() else None


def check_score(ctx, page, rd, delivered, col):
    sec = page.sec("score")
    if not sec:
        return
    problems = []
    score = ctx.score
    value = _score_value(ctx)
    if value is not None:
        if not re.search(r'<text class="sp-val"[^>]*>%d</text>' % value, sec):
            problems.append("dial does not show the delivered score %d" % value)
    else:
        if "Score not reported" not in sec:
            problems.append("no usable score (DataIndex=%r) but the dial does "
                            "not say 'Score not reported'" % score.get("DataIndex"))
        reason = score.get("ErrorDescription")
        if reason and esc(reason) not in sec:
            problems.append("ErrorDescription %r not shown under the dial" % reason)
        if not reason and not score.get("ErrorNumber") and \
                "No score and no error reason delivered" not in sec:
            problems.append("no score and no error delivered, but the dial "
                            "does not say so")

    fh = score.get("FHScoreBand") or score.get("FHScoreBand1")
    if fh and not re.search(r'>%s(?: · [^<]*)?(?: <span class="attn"[^>]*>!</span>)?'
                            r'<em>FH</em>' % re.escape(esc(fh)), sec):
        problems.append("FH chip does not show the delivered band %r" % fh)
    letter = score.get("DataRange")
    if letter and not re.search(r'>%s(?: · [^<]*)?<em>AECB</em>'
                                % re.escape(esc(letter)), sec):
        problems.append("AECB chip does not show the delivered letter %r" % letter)
    if not fh and not letter and "Band not reported" not in sec:
        problems.append("neither band delivered but no 'Band not reported'")

    configured = None
    if value is not None:
        for band in ctx.bands.get("fh_bands") or []:
            if value >= band.get("from", 0):
                configured = band.get("code")
    want_mark = bool(value is not None and fh and configured and configured != fh)
    has_mark = 'class="attn sp-attn"' in sec
    if want_mark != has_mark:
        problems.append("band-mismatch '!' %s: configured cut-offs put %s in "
                        "%s, delivered band %s" % (
                            "missing" if want_mark else "shown wrongly", value,
                            configured, fh))
    b1, b2 = score.get("FHScoreBand"), score.get("FHScoreBand1")
    want_conflict = bool(b1 and b2 and str(b1).strip() != str(b2).strip())
    if want_conflict != ("score.FHScoreBand is " in sec):
        problems.append("FHScoreBand/FHScoreBand1 conflict '!' %s (%r vs %r)"
                        % ("missing" if want_conflict else "shown wrongly", b1, b2))
    if problems:
        col.add("recompute.score", problems[0] if len(problems) == 1 else
                "%s in section 02" % plural(len(problems), "problem"),
                details=problems if len(problems) > 1 else None, section="score")

    oldest = ctx.totals.get("OldestContractOpenDate")
    months = dates.months_between(oldest, rd) if (oldest and rd) else None
    code = None
    if months is not None:
        for band in (ctx.bands.get("vintage_bands") or {}).get("bands") or []:
            hi = band.get("to_months")
            if months >= band.get("from_months", 0) and (hi is None or months <= hi):
                code = band.get("code")
                break
    shown = re.search(r'<span class="ss-vint-k">Vintage</span><span>([^<]*)</span>',
                      sec)
    got = shown.group(1) if shown else None
    if got != code:
        col.add("recompute.vintage", "vintage shows %r, expected %r" % (got, code),
                details=["OldestContractOpenDate %r, report date %s, %s months"
                         % (oldest, rd, months)], section="score")


def _panels(sec):
    out = []
    for chunk in sec.split('<div class="wsx-panel">')[1:]:
        m = re.search(r'<div class="wsx-worst(?: (red|amber|green))?">(.*?)</div>',
                      chunk, re.S)
        if not m:
            out.append({"state": "absent", "tone": None, "headline": None,
                        "chunk": chunk})
            continue
        tone = m.group(1)
        head = pagetext.text(re.sub(r'<span class="attn".*?</span>', "",
                                    m.group(2), flags=re.S))
        out.append({"state": {"red": "severe", "amber": "adverse",
                              "green": "clean"}.get(tone, "unknown"),
                    "tone": tone, "headline": head, "chunk": chunk})
    return out


def check_worst(ctx, page, rd, delivered, col):
    sec = page.sec("worst_status")
    if not sec:
        return
    panels = _panels(sec)
    if len(panels) != 3:
        col.add("recompute.worst_panels", "expected 3 panels, found %d"
                % len(panels), section="worst_status")
        return
    p24, p36, plife = panels
    problems = []

    v24 = ctx.totals.get("WorstStatus24M")
    st24 = strict_status(ctx, v24) if v24 is not None and str(v24).strip() else None
    if v24 is None or not str(v24).strip():
        if p24["state"] != "absent":
            problems.append("24-month panel shows %r but WorstStatus24M is not "
                            "delivered" % p24["headline"])
    else:
        tone, _state = grade(st24)
        if p24["tone"] != tone:
            problems.append("24-month panel %r is coloured %s, rank says %s"
                            % (v24, p24["tone"], tone))

    life = ctx.summary.get("Worststatus")
    if life is None:
        want_tone = "absent"
    else:
        try:
            want_tone = "amber" if int(life) else "green"
        except (TypeError, ValueError):
            want_tone = None
    got_tone = "absent" if plife["state"] == "absent" else plife["tone"]
    if got_tone != want_tone:
        problems.append("life-time count panel is %s, expected %s for "
                        "Worststatus=%r" % (got_tone, want_tone, life))

    states = [p["state"] for p in panels]
    want = ("Severe status on file" if "severe" in states else
            "Adverse history" if "adverse" in states else
            "Partly reported" if ("absent" in states or "unknown" in states) else
            "No adverse status on file")
    pill = page.aside_text("worst_status")
    if want not in pill:
        problems.append("header pill reads %r, the panels (%s) call for %r"
                        % (pill, "/".join(states), want))
    if problems:
        col.add("recompute.worst_panels", problems[0] if len(problems) == 1 else
                "%s in section 03" % plural(len(problems), "problem"),
                details=problems if len(problems) > 1 else None,
                section="worst_status")

    floor = []
    if st24 is not None and st24.get("rank") is not None:
        st36 = strict_status(ctx, p36["headline"]) if p36["headline"] else None
        if p36["state"] == "absent" or st36 is None:
            floor.append("36-month panel shows %r although AECB delivered %r "
                         "for 24 months" % (p36["headline"] or "Not derivable", v24))
        elif st36.get("rank", 100) > st24["rank"]:
            floor.append("36-month panel shows %r (rank %s), milder than the "
                         "delivered 24-month %r (rank %s)"
                         % (p36["headline"], st36.get("rank"), v24, st24["rank"]))
    try:
        d24 = int(ctx.totals.get("MaxPaymentDelay24M"))
    except (TypeError, ValueError):
        d24 = None
    if d24 is not None:
        m = re.search(r"Max payment delay &middot; 36m</span>(.*?)</div>",
                      p36["chunk"], re.S)
        shown = pagetext.text(m.group(1)) if m else ""
        days = re.match(r"([\d,]+) days", shown)
        if not days or int(days.group(1).replace(",", "")) < d24:
            floor.append("36-month delay reads %r, below the delivered 24-month "
                         "%d days" % (shown or "(missing)", d24))
    if floor:
        col.add("recompute.worst_floor", floor[0],
                details=floor[1:] or None, section="worst_status")


def check_income(ctx, page, rd, delivered, col):
    sec = page.sec("income")
    n = sec.count('<span class="emp-cur">Current</span>')
    if n > 1:
        col.add("recompute.income_current", "%d employers wear 'Current'" % n,
                section="income")


def check_returns(ctx, page, rd, delivered, col):
    sec = page.sec("returns")
    if not sec:
        return
    records = rows(ctx, "paymentOrder")
    count = len(ctx.rows("paymentOrder"))
    window = (ctx.returns_cfg or {})["window_months"]
    if count:
        if rd is None:
            want = "%s on file" % plural(count, "return")
        else:
            start = dates.add_months(rd, -window)
            recent = sum(1 for r in records
                         if dates.parse_any(r.get("ReturnDate")) and
                         dates.parse_any(r.get("ReturnDate")) >= start)
            want = ("%s · last %dm" % (plural(recent, "return"), window) if recent
                    else "%d on file · none in %dm" % (count, window))
    else:
        ss = rows(ctx, "sectionStatus")
        if not ctx.rows("sectionStatus"):
            want = "Unverified"
        elif any("bounced cheque" in str(r.get("ReportType") or "").lower()
                 for r in ss):
            want = "Checked · none reported"
        else:
            want = "Section not requested"
    pill = page.aside_text("returns")
    problems = []
    if want not in pill:
        problems.append("pill reads %r, expected %r" % (pill, want))

    flag = ctx.score.get("PaymentOrderFlag")
    if not isinstance(flag, bool) and flag is not None:
        low = str(flag).strip().lower()
        flag = True if low in ("true", "y", "yes", "1") else \
            False if low in ("false", "n", "no", "0") else None
    want_attn = flag is not None and flag != bool(count)
    has_attn = 'class="attn"' in pagetext.aside(sec)
    if want_attn != has_attn:
        problems.append("PaymentOrderFlag contradiction '!' %s (flag %r, %s)"
                        % ("missing" if want_attn else "shown wrongly",
                           ctx.score.get("PaymentOrderFlag"),
                           plural(count, "paymentOrder row")))
    if problems:
        col.add("recompute.returns_pill", problems[0],
                details=problems[1:] or None, section="returns")


def check_facilities(ctx, page, rd, delivered, col):
    sec = page.sec("facilities")
    if not sec:
        return
    totals = ctx.totals
    chips = page.aside_text("facilities")
    problems = []

    exposure = totals.get("TotalExposure")
    if exposure is None:
        if "Total exposure not reported" not in chips:
            problems.append("TotalExposure missing but the chip does not say so")
    else:
        shown = fmt0(exposure) or str(exposure)
        if not re.search(r"Total exposure\s*(?:AED\s*)?%s" % re.escape(shown), chips):
            problems.append("Total exposure chip does not show %s (chips: %r)"
                            % (shown, chips))

    for field, label in (("TotalBalanceGuaranteed", r"Guaranteed(?! overdue)"),
                         ("TotalOverdueGuaranteed", r"Guaranteed overdue")):
        n = number(totals.get(field))
        present = re.search(r"%s\s*AED" % label, chips)
        if n:
            if not re.search(r"%s\s*AED\s*%s" % (label, re.escape(fmt0(n))), chips):
                problems.append("%s %s delivered but its chip is missing or "
                                "wrong (chips: %r)" % (field, fmt0(n), chips))
        elif n == 0 and present:
            problems.append("%s is zero but a chip is shown -- chips appear only "
                            "when non-zero" % field)

    newest = totals.get("NewestContractOpenDate")
    parsed = dates.parse_any(newest)
    if parsed and ("Newest facility %s" % dates.fmt_short(parsed)) not in chips:
        problems.append("Newest facility chip does not show %s"
                        % dates.fmt_short(parsed))
    elif newest is not None and not parsed and "unreadable date" not in chips:
        problems.append("NewestContractOpenDate %r is unreadable but the chip "
                        "does not say so" % newest)
    if problems:
        col.add("recompute.facility_chips", problems[0],
                details=problems[1:] or None, section="facilities")

    cards = {}
    for card in re.split(r'(?=<div class="fac(?: empty)?"><div class="fac-h">)',
                         sec)[1:]:
        m = re.search(r'<span class="fac-cat">([^<]*)</span>', card)
        if m:
            cards[m.group(1)] = card
    fin = rows(ctx, "contractsFinancialSummary")
    counts = rows(ctx, "contractsSummary")
    live = collections.Counter(c.get("ContractCategory")
                               for c in rows(ctx, "contracts") if not is_closed(c))
    card_problems = []
    for cat in CATEGORIES:
        card = cards.get(cat)
        if card is None:
            card_problems.append("category card %s is missing" % cat)
            continue
        main = None
        for r in fin:
            if r.get("ContractRole") == "A" and r.get("ContractCategory") == cat:
                main = r
        has_figure = any(number(r.get(f)) for r in fin
                         if r.get("ContractCategory") == cat
                         and r.get("ContractRole") in ROLES
                         for f in ("Balance", "CreditLimit", "OverdueAmount",
                                   "PaymentAmount"))
        has_count = any(number(r.get(f)) for r in counts
                        if r.get("ContractCategory") == cat
                        and r.get("ContractRole") in ROLES
                        for f in ("TotalNo", "DeclinedNo", "RejectedNo",
                                  "NotTakenUpNo"))
        if card.startswith('<div class="fac empty">'):
            if live[cat] or has_figure or has_count:
                card_problems.append(
                    "card %s says 'No facilities' but the payload has %s"
                    % (cat, ", ".join(x for x, on in (
                        ("%d open contract(s)" % live[cat], live[cat]),
                        ("non-zero summary figures", has_figure),
                        ("contract / outcome counts", has_count)) if on)))
            continue
        i = card.find('<span class="fac-big')
        head = pagetext.text(pagetext.balanced(card, i, "span")) if i >= 0 else ""
        balance = (main or {}).get("Balance")
        want = "Not reported" if balance is None else (fmt0(balance) or str(balance))
        if want not in head:
            card_problems.append("card %s main-holder headline reads %r, expected "
                                 "%r (contractsFinancialSummary role A Balance)"
                                 % (cat, head, want))
    if card_problems:
        col.add("recompute.facility_cards", card_problems[0],
                details=card_problems[1:] or None, section="facilities")


def _in_arrears(ctx, c):
    for field in ("Current_OverdueAmount", "Current_DaysPaymentDelay"):
        value = c.get(field)
        n = number(value)
        if value and (n is None or n != 0):
            return True
    status = c.get("Current_ContractStatus")
    if not status:
        return False
    rank = ctx.status(status)["rank"]
    return rank is None or rank < 100


def _expected_block(ctx, c, rd):
    if is_closed(c):
        closed_on = dates.parse_any(c.get("ClosedDate"))
        if closed_on and rd and closed_on >= dates.add_months(
                rd, -ctx.bands["closed_window_months"]):
            return "facClosed6"
        return "facClosedOld"
    if c.get("ContractCategory") == "S" and not _in_arrears(ctx, c):
        return "facSvcOk"
    return "facActive"


def _key(value):
    return json.dumps(value, sort_keys=True)


def check_heatmap(ctx, page, rd, delivered, col):
    contracts = rows(ctx, "contracts")
    sec = page.sec("detail")
    if sec:
        if not contracts:
            if "No contracts reported" not in pagetext.text(sec):
                col.add("recompute.contract_counts", "contracts is empty but "
                        "section 07 does not say 'No contracts reported'",
                        section="detail")
        else:
            closed = sum(1 for c in contracts if is_closed(c))
            want = "%d Active · %d Closed" % (len(contracts) - closed, closed)
            got = page.aside_text("detail")
            if want not in got:
                col.add("recompute.contract_counts", "pill reads %r, expected %r"
                        % (got, want), section="detail")
    if page.blob is None:
        return

    drawn = pagetext.heatmap_rows(page.blob)
    want = collections.Counter(_key(c.get("CBContractId")) for c in contracts)
    got = collections.Counter(_key(r.get("id")) for _b, _c, r in drawn)
    missing, extra = want - got, got - want
    if missing or extra or len(drawn) != len(contracts):
        details = []
        for c in contracts:
            if missing.get(_key(c.get("CBContractId"))):
                details.append("missing %s: ContractCategory=%r ActiveFlag=%r "
                               "ContractType=%r" % (
                                   c.get("CBContractId"), c.get("ContractCategory"),
                                   c.get("ActiveFlag"), c.get("ContractType")))
        details += ["extra/duplicate %s x%d" % (k, n) for k, n in extra.items()]
        col.add("nodrop.heatmap_contracts",
                "the heatmap blob holds %d row(s) for %s"
                % (len(drawn), plural(len(contracts), "contract")),
                details=details, section="detail")

    placed = dict((_key(r.get("id")), block) for block, _cat, r in drawn)
    wrong = []
    for c in contracts:
        k = _key(c.get("CBContractId"))
        if want[k] != 1 or got[k] != 1:
            continue
        expected = _expected_block(ctx, c, rd)
        if placed[k] != expected:
            wrong.append("%s is in %s, expected %s (ActiveFlag=%r ClosedDate=%r "
                         "category=%r)" % (c.get("CBContractId"), placed[k],
                                           expected, c.get("ActiveFlag"),
                                           c.get("ClosedDate"),
                                           c.get("ContractCategory")))
    if wrong:
        col.add("recompute.heatmap_bucket", wrong[0], details=wrong[1:] or None,
                section="detail")


def check_applications(ctx, page, rd, delivered, col):
    sec = page.sec("applications")
    apps = rows(ctx, "applications")
    if page.blob is not None and rd is not None:
        dated = sum(1 for r in apps if applied_on(r) is not None)
        timeline = page.blob.get("applications") or {}
        events = len(timeline.get("events") or [])
        if events != dated:
            col.add("nodrop.applications_events",
                    "%s on the timeline for %s"
                    % (plural(events, "event"), plural(dated, "datable row")),
                    section="applications")
    if not sec:
        return

    try:
        delivered_90d = int(ctx.totals.get("Applications90D"))
    except (TypeError, ValueError):
        delivered_90d = None
    counted = 0
    if rd is not None:
        for r in apps:
            when = applied_on(r)
            if when and 0 <= (rd - when).days < 90:
                counted += 1
    aside = pagetext.aside(sec)
    pill = pagetext.text(aside)
    problems = []
    if delivered_90d is None:
        want = "No applications on file" if not ctx.rows("applications") \
            else "%d in 90 days" % counted
        if want not in pill:
            problems.append("pill reads %r, expected %r" % (pill, want))
    else:
        red = ctx.bands["applications_90d_red"]
        amber = ctx.bands["applications_90d_amber"]
        tone = "bad" if delivered_90d >= red else (
            "warn" if delivered_90d >= amber else "good")
        if not re.search(r'<span class="tag %s">%d in 90 days' % (tone, delivered_90d),
                         aside):
            problems.append("pill should read '%d in 90 days' graded %s (pill: %r)"
                            % (delivered_90d, tone, pill))
        want_tag = "%d row%s in window" % (counted, "" if counted == 1 else "s")
        if counted != delivered_90d and want_tag not in pill:
            problems.append("AECB says %d, the rows give %d, but the %r tag is "
                            "missing" % (delivered_90d, counted, want_tag))
        if counted == delivered_90d and "in window" in pill:
            problems.append("a 'rows in window' tag is shown although rows and "
                            "Applications90D agree (%d)" % counted)
    if problems:
        col.add("recompute.applications_pill", problems[0],
                details=problems[1:] or None, section="applications")


PAGE_CHECKS = (check_hygiene, check_blob, check_validity, check_identity,
               check_score, check_worst, check_income, check_returns,
               check_facilities, check_heatmap, check_applications)
