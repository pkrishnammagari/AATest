"""Proves every check can fire -- on deliberately broken copies of the fixtures.

A check that has never been seen to fail proves nothing when it passes. So
each case here breaks one thing and asserts the matching check reports it:

  payload cases  mutate a committed fixture's JSON and run the whole pipeline;
  page cases     render a fixture, then corrupt the PAGE -- so the check is
                 proven against a broken page even though today's code never
                 renders one;
  crash case     make one section's render() raise, and expect the page and
                 that section to be reported.

The two unmutated fixtures must come back with no ERROR or FAIL, and no check
may raise inside the harness. Run it on any machine before trusting a report:

    python3 scripts/check_corpus.py --selftest

Python 3.9 compatible.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile

from aecb import context
from aecb.render import sections as r_sections
from aecb.render.page import render_page

from . import browser, checks, pagetext, registry, snapshot

REPO = checks.REPO
ARCHIVE = os.path.join(REPO, "ReferenceJSON", "aecb_payload_archive_170623.json")
SYNTH = os.path.join(REPO, "ReferenceJSON",
                     "1_SyntheticJSONPayload_Delinquent_MultiFacility.json")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --- payload mutations -----------------------------------------------------------

def _first(rows, pred=lambda r: True):
    for r in rows:
        if pred(r):
            return r
    raise AssertionError("fixture has no row the mutation needs")


def m_unknown_array(p):
    p["brandNewSection"] = [{"x": 1}]


def m_contact_type(p):
    p["contacts"].append({"ContactType": "Fax Number ", "Contact": "042223333",
                          "ProviderNo": "B01", "DateOfLastUpdate": "2023-01-01"})


def m_fin_role(p):
    p["contractsFinancialSummary"].append({"ContractRole": "X", "ContractCategory": "I",
                                           "Balance": 5000})


def m_history_orphan(p):
    row = dict(p["contractsHistory"][0])
    row["CBContractId"] = "NOPE999"
    p["contractsHistory"].append(row)


def m_history_duplicate(p):
    # The newest row: it is certainly inside the 36-month window.
    row = dict(max(p["contractsHistory"],
                   key=lambda r: str(r.get("ReferenceDate") or "")))
    row["DaysPaymentDelay"] = 77
    row["ContractStatus"] = "Default"
    p["contractsHistory"].append(row)


def m_history_future(p):
    row = dict(p["contractsHistory"][0])
    row["ReferenceDate"] = "2031-01-31T00:00:00"
    p["contractsHistory"].append(row)


def m_app_undated(p):
    app = p["applications"][0]
    app["LastUpdateDate"] = None
    app["DateOfLastUpdate"] = None


def m_status(p):
    p["contractsHistory"][0]["ContractStatus"] = "Zombie Status"


def m_role(p):
    p["contracts"][0]["Role"] = "Silent Partner"


def m_frequency(p):
    _first(p["contracts"], lambda r: r.get("PaymentFrequency"))["PaymentFrequency"] = \
        "every blue moon"


def m_phase(p):
    p["applications"][0]["Phase"] = "Teleported"


def m_category(p):
    p["contracts"][0]["ContractCategory"] = "Z"


def m_active_flag(p):
    p["contracts"][0]["ActiveFlag"] = "Dormant"


def m_returns(p):
    p["paymentOrder"][0]["Type"] = "Carrier Pigeon"
    p["paymentOrder"][0]["Severity"] = "Catastrophic"


def m_score_band(p):
    p["score"][0]["FHScoreBand"] = "ZZZ"


def m_resident(p):
    p["customerInfo"][0]["ResidentFlag"] = "Maybe"


def m_info_type(p):
    p["identification"].append({"InfoType": "DrivingLicence", "Info": "DL-1",
                                "ProviderNO": "B01", "DateOfLastUpdate": "2023-01-01"})


def m_bad_date(p):
    p["contracts"][0]["OpenDate"] = "31/31/2020"


def m_future_date(p):
    p["paymentOrder"][0]["ReturnDate"] = "2031-01-01T00:00:00"


def m_no_report_date(p):
    for row in p["sectionStatus"]:
        row["Last EnquiryDate"] = None
    p["score"][0]["DataPullDate"] = None


def m_not_aecb(p):
    for key in list(p):
        del p[key]
    p["somethingElse"] = []


PAYLOAD_CASES = (
    ("nodrop.unknown_arrays", ARCHIVE, m_unknown_array),
    ("nodrop.contacts_type", ARCHIVE, m_contact_type),
    ("nodrop.fin_summary_role", ARCHIVE, m_fin_role),
    ("nodrop.history_orphan", ARCHIVE, m_history_orphan),
    ("nodrop.history_duplicate_month", ARCHIVE, m_history_duplicate),
    ("nodrop.history_future", ARCHIVE, m_history_future),
    ("nodrop.applications_undated", ARCHIVE, m_app_undated),
    ("vocab.status", ARCHIVE, m_status),
    ("vocab.role", ARCHIVE, m_role),
    ("vocab.frequency", ARCHIVE, m_frequency),
    ("vocab.phase", ARCHIVE, m_phase),
    ("vocab.category", ARCHIVE, m_category),
    ("vocab.active_flag", ARCHIVE, m_active_flag),
    ("vocab.returns", ARCHIVE, m_returns),
    ("vocab.score_band", ARCHIVE, m_score_band),
    ("vocab.resident", ARCHIVE, m_resident),
    ("vocab.info_type", ARCHIVE, m_info_type),
    ("vocab.provider", ARCHIVE, lambda p: None),
    ("dates.unparseable", ARCHIVE, m_bad_date),
    ("dates.future", ARCHIVE, m_future_date),
    ("dates.no_report_date", ARCHIVE, m_no_report_date),
    ("load.shape", ARCHIVE, m_not_aecb),
)


# --- page mutations -----------------------------------------------------------------

def _sub1(pattern, repl, raw):
    out, n = re.subn(pattern, repl, raw, count=1, flags=re.S)
    if not n:
        raise AssertionError("page mutation matched nothing: %s" % pattern)
    return out


def _nth_worst(raw, n, text):
    matches = list(re.finditer(r'(<div class="wsx-worst[^"]*">)(.*?)(</div>)', raw, re.S))
    m = matches[n]
    return raw[:m.start(2)] + text + raw[m.end(2):]


def _blob_edit(fn):
    def mutate(raw):
        data = pagetext.blob(raw)
        fn(data)
        return pagetext.replace_blob(raw, data)
    return mutate


def _drop_heatmap_row(data):
    data["heatmap"]["blocks"][0]["groups"][0]["rows"].pop(0)


def _move_heatmap_row(data):
    blocks = data["heatmap"]["blocks"]
    row = blocks[0]["groups"][0]["rows"].pop(0)
    target = [b for b in blocks if b["key"] != blocks[0]["key"]][0]
    target["groups"][0]["rows"].append(row)


def _drop_event(data):
    data["applications"]["events"].pop(0)


PAGE_CASES = (
    ("gate.check_report", ARCHIVE,
     lambda raw: raw.replace("MUNA MOHAMMAD ESSA HASSAN ALI", "REDACTED")),
    ("hygiene.structure", ARCHIVE,
     lambda raw: _sub1(r'<section class="[^"]*" id="s5">.*?</section>', "", raw)),
    ("hygiene.token", ARCHIVE,
     lambda raw: raw.replace('<div class="wsx">', '<div class="wsx"><b>undefined</b>', 1)),
    ("hygiene.empty_value", ARCHIVE,
     lambda raw: raw.replace('<div class="wsx">', '<div class="wsx"><span class="v"></span>', 1)),
    ("hygiene.negative", ARCHIVE,
     lambda raw: raw.replace('<div class="wsx">', '<div class="wsx"><i>-3 months</i>', 1)),
    ("hygiene.sci_notation", ARCHIVE,
     lambda raw: raw.replace('<div class="wsx">', '<div class="wsx"><i>1.5e+06</i>', 1)),
    ("hygiene.markup", ARCHIVE,
     lambda raw: raw.replace('<div class="wsx">', '<div class="wsx"><i id="heatmap"></i>', 1)),
    ("hygiene.blob", ARCHIVE,
     lambda raw: raw.replace("window.__AECB = {", 'window.__AECB = {"bad": NaN, ', 1)),
    ("recompute.validity", ARCHIVE,
     lambda raw: _sub1(r'(<span class="pd"></span>)Report expired', r"\1Report valid", raw)),
    ("recompute.age", ARCHIVE, lambda raw: _sub1(r"\b32 yrs", "99 yrs", raw)),
    ("recompute.residency", ARCHIVE,
     lambda raw: _sub1(r'(<span class="tag brand">)Resident<', r"\1Non-resident<", raw)),
    ("recompute.score", ARCHIVE,
     lambda raw: _sub1(r'(<text class="sp-val"[^>]*>)732<', r"\g<1>733<", raw)),
    ("recompute.vintage", ARCHIVE,
     lambda raw: _sub1(r'(<span class="ss-vint-k">Vintage</span><span>)B4<',
                       r"\1B2<", raw)),
    ("recompute.worst_panels", ARCHIVE,
     lambda raw: raw.replace('<div class="wsx-worst green">', '<div class="wsx-worst red">', 1)),
    ("recompute.worst_floor", SYNTH,
     lambda raw: _nth_worst(raw, 1, "Active Payments")),
    ("recompute.income_current", ARCHIVE,
     lambda raw: raw.replace('<span class="emp-cur">Current</span>',
                             '<span class="emp-cur">Current</span>' * 2, 1)),
    ("recompute.returns_pill", ARCHIVE,
     lambda raw: _sub1(r"none in 6m", "none in 9m", raw)),
    ("recompute.facility_chips", ARCHIVE,
     lambda raw: _sub1(r"(Total exposure <b><span class=\"aed\">AED</span>)[\d,]+",
                       r"\g<1>1", raw)),
    ("recompute.facility_cards", ARCHIVE,
     lambda raw: _sub1(r'(<span class="fac-big[^"]*"><span class="aed">AED</span>)[\d,]+',
                       r"\g<1>1", raw)),
    ("recompute.contract_counts", ARCHIVE,
     lambda raw: _sub1(r"\d+ Active · ", "99 Active · ", raw)),
    ("recompute.applications_pill", ARCHIVE,
     lambda raw: _sub1(r"rows in window", "rows elsewhere", raw)),
    ("nodrop.heatmap_contracts", ARCHIVE, _blob_edit(_drop_heatmap_row)),
    ("recompute.heatmap_bucket", ARCHIVE, _blob_edit(_move_heatmap_row)),
    ("nodrop.applications_events", ARCHIVE, _blob_edit(_drop_event)),
)


# --- runners ------------------------------------------------------------------------

def _ids(findings):
    return set(f["check"] for f in findings)


def _write(tmp, name, payload):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def run():
    """[(case, ok, note)] for every case."""
    out = []
    tmp = tempfile.mkdtemp(prefix="aecb-selftest-")
    try:
        # Baseline: the unmutated fixtures are clean.
        for path in (ARCHIVE, SYNTH):
            res = checks.run_payload(path)
            bad = [f for f in res["findings"]
                   if f["severity"] in (registry.ERROR, registry.FAIL)]
            ok = not bad and not res["harness_errors"]
            out.append(("clean fixture %s" % os.path.basename(path), ok,
                        "; ".join("%s: %s" % (f["check"], f["message"]) for f in bad)
                        or "; ".join(res["harness_errors"])))

        # load.json: not JSON at all.
        path = os.path.join(tmp, "broken.json")
        with open(path, "wb") as fh:
            fh.write(b"{not json")
        out.append(("load.json", "load.json" in _ids(
            checks.run_payload(path)["findings"]), ""))

        for check_id, base, mutate in PAYLOAD_CASES:
            payload = _load(base)
            mutate(payload)
            res = checks.run_payload(_write(tmp, "case.json", payload))
            got = _ids(res["findings"])
            out.append((check_id, check_id in got,
                        "" if check_id in got else "fired instead: %s"
                        % ", ".join(sorted(got))))

        # perf.slow: any render is slow against a zero threshold.
        res = checks.run_payload(ARCHIVE, slow_seconds=0.0)
        out.append(("perf.slow", "perf.slow" in _ids(res["findings"]), ""))

        # load.context: ReportContext cannot be built (a config fault, say).
        original_from_bytes = checks.context.from_bytes

        def no_context(raw, source_name="upload"):
            raise FileNotFoundError("selftest: config/status_codes.json missing")
        checks.context.from_bytes = no_context
        try:
            got = _ids(checks.run_payload(ARCHIVE)["findings"])
        finally:
            checks.context.from_bytes = original_from_bytes
        out.append(("load.context", "load.context" in got, ""))

        # render.page / render.section: one section raises.
        target = r_sections.flat_sections()[3]
        original = target.render

        def boom(ctx, meta):
            raise RuntimeError("selftest: forced failure")
        target.render = boom
        try:
            got = _ids(checks.run_payload(ARCHIVE)["findings"])
        finally:
            target.render = original
        for cid in ("render.page", "render.section"):
            out.append((cid, cid in got, ""))

        # Page mutations against rendered fixtures.
        rendered = {}
        for check_id, base, mutate in PAGE_CASES:
            if base not in rendered:
                ctx = context.from_file(base)
                rendered[base] = (ctx, render_page(ctx), _load(base))
            ctx, raw, payload = rendered[base]
            try:
                broken = mutate(raw)
            except AssertionError as exc:
                out.append((check_id, False, str(exc)))
                continue
            findings, errors = checks.check_rendered(ctx, broken, payload)
            got = _ids(findings)
            out.append((check_id, check_id in got and not errors,
                        "" if check_id in got else "fired instead: %s"
                        % ", ".join(sorted(got)) + ("; harness: %s" % errors
                                                    if errors else "")))

        # Browser findings from probe data (no Chrome needed) ...
        result = {"delivered": ""}
        fake = {"errors": ["boom"], "bits": [["#heatmap", "text", "OVER LIMIT undefined%"]],
                "hmRows": 3, "tlEvents": 1, "overflowX": True,
                "scrollW": 1900, "clientW": 1560}
        got = _ids(browser.findings_for(result, fake, (4, 1)))
        for cid in ("browser.js_error", "browser.token", "browser.counts",
                    "browser.overflow"):
            out.append((cid + " (probe data)", cid in got, ""))

        # ... and, when Chrome is here, from a real page.
        chrome = browser.find_chrome()
        if chrome:
            ctx, raw, payload = rendered[ARCHIVE]
            data = pagetext.blob(raw)
            row = pagetext.heatmap_rows(data)[0][2]
            row["overLimit"] = True
            row.pop("util", None)
            broken = pagetext.replace_blob(raw, data).replace(
                "</body>", "<script>throw new Error('selftest');</script></body>")
            probe = browser.probe(chrome, broken)
            got = _ids(browser.findings_for({"delivered": ""}, probe, (None, None)))
            for cid in ("browser.js_error", "browser.token"):
                out.append((cid + " (Chrome)", cid in got, ""))
        else:
            out.append(("browser (Chrome)", True, "skipped: no Chrome found"))

        # Baseline: a changed fact is reported.
        env_facts = {"score": 732, "worst36": {"status": "U"}}
        delta = snapshot.diff(env_facts, dict(env_facts, score=701))
        out.append(("baseline.changed (diff)", delta == ["score: 732 -> 701"],
                    str(delta)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    results = run()
    failed = [r for r in results if not r[1]]
    for name, ok, note in results:
        print("%-4s %s%s" % ("ok" if ok else "FAIL", name,
                             ("  -- " + note) if note else ""))
    proven = set(name.split(" ")[0] for name, ok, _n in results if ok)
    unproven = sorted(c for c in registry.CHECKS if c not in proven
                      and c != "baseline.new")
    print("")
    print("%d case(s), %d failed." % (len(results), len(failed)))
    if unproven:
        print("Checks with no self-test case: %s" % ", ".join(unproven))
    return 1 if failed else 0
