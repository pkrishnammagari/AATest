"""Run every archived API payload through the report and check what it shows.

check_report.py gates the two committed fixtures. This runs the same gate --
and a good deal more -- over every real response app_api.py has archived to
ReferenceJSON/api_responses/, because a code path the fixtures never take is
a code path nothing has tested.

    python3 scripts/check_corpus.py                    # ReferenceJSON/api_responses/
    python3 scripts/check_corpus.py --only 20260915    # files whose name contains it
    python3 scripts/check_corpus.py --approve          # accept today's output as baseline
    python3 scripts/check_corpus.py --browser off      # skip the headless-Chrome pass
    python3 scripts/check_corpus.py --dir ReferenceJSON    # the committed fixtures
    python3 scripts/check_corpus.py --selftest         # prove every check can fire
    python3 scripts/check_corpus.py --list-checks

Writes corpus_report/summary.md (read this, or hand it to Claude Code with
scripts/corpus/TRIAGE.md), corpus_report/results.json, and the rendered page
of every payload with a finding under corpus_report/pages/. corpus_report/ is
gitignored: it is derived from bureau payloads.

Exit 0 when no payload has an ERROR or FAIL (--strict: or a WARN), 1 when one
does, 2 on a usage problem (nothing to check, Chrome demanded but missing).

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import glob
import json
import os
import re
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO)
sys.path.insert(0, SCRIPTS)

from aecb.render import branding                      # noqa: E402
from corpus import (browser, checks, pagetext, registry, report,   # noqa: E402
                    snapshot)

DEFAULT_DIR = os.path.join(REPO, "ReferenceJSON", "api_responses")
DEFAULT_OUT = os.path.join(REPO, "corpus_report")


def _args(argv):
    p = argparse.ArgumentParser(
        description="Check every archived AECB payload against the rendered report.")
    p.add_argument("--dir", default=DEFAULT_DIR,
                   help="folder of *.json payloads (default: %(default)s)")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help="report folder (default: %(default)s)")
    p.add_argument("--only", default="",
                   help="comma-separated substrings; check only matching files")
    p.add_argument("--browser", choices=("auto", "on", "off"), default="auto",
                   help="headless-Chrome pass for client-drawn sections "
                        "(auto: when Chrome is found)")
    p.add_argument("--jobs", type=int, default=4,
                   help="parallel Chrome pages in the browser pass")
    p.add_argument("--save-html", choices=("problems", "all", "none"),
                   default="problems",
                   help="write rendered pages to <out>/pages/ (default: only "
                        "payloads with an ERROR, FAIL or WARN)")
    p.add_argument("--baseline", default="",
                   help="baseline file (default: <out>/baseline_<dir name>.json)")
    p.add_argument("--approve", action="store_true",
                   help="record the current facts as the approved baseline")
    p.add_argument("--no-baseline", action="store_true",
                   help="skip the baseline comparison")
    p.add_argument("--slow", type=float, default=5.0,
                   help="seconds before a render counts as slow")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 on WARN findings too")
    p.add_argument("--selftest", action="store_true",
                   help="mutate the committed fixtures and prove each check fires")
    p.add_argument("--list-checks", action="store_true",
                   help="print the check catalogue and exit")
    return p.parse_args(argv)


def _resolve_dir(path):
    if os.path.isabs(path) or os.path.isdir(path):
        return os.path.abspath(path)
    in_repo = os.path.join(REPO, path)
    return in_repo if os.path.isdir(in_repo) else os.path.abspath(path)


def _git():
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--",
                                     "aecb", "config", "scripts"], cwd=REPO,
                                    capture_output=True, text=True).stdout.strip())
        return sha or "unknown", dirty
    except Exception:   # noqa: BLE001 -- no git on the box is not a failure
        return "unknown", False


def discover(directory, only):
    files = sorted(glob.glob(os.path.join(directory, "*.json")))
    needles = [n.strip().lower() for n in only.split(",") if n.strip()]
    if needles:
        files = [f for f in files
                 if any(n in os.path.basename(f).lower() for n in needles)]
    return files


def _finding(check_id, message, details=None):
    chk = registry.get(check_id)
    return {"check": check_id, "severity": chk.severity, "layer": chk.layer,
            "message": message, "details": list(details or [])[:40],
            "section": None, "data": None}


# --- corpus-level views ---------------------------------------------------------

def schema_drift(results):
    """Fields no committed fixture carries and no string in aecb/ names."""
    known = collections.defaultdict(set)
    for path in glob.glob(os.path.join(REPO, "ReferenceJSON", "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:   # noqa: BLE001
            continue
        for array, rows in data.items():
            for row in rows if isinstance(rows, list) else [rows]:
                if isinstance(row, dict):
                    known[array].update(k.strip() for k in row)
    code = checks.code_fields()
    seen, example = collections.defaultdict(set), {}
    for r in results:
        for array, fields in (r.get("fields") or {}).items():
            for field in fields:
                if field in known.get(array, ()) or field in code:
                    continue
                key = "%s.%s" % (array, field)
                seen[key].add(r["file"])
                example.setdefault(key, r["file"])
    return sorted(({"field": k, "payloads": len(v), "example": example[k]}
                   for k, v in seen.items()),
                  key=lambda d: (-d["payloads"], d["field"]))


def baseline(args, results, directory, filtered):
    path = args.baseline or os.path.join(
        args.out, "baseline_%s.json" % re.sub(r"[^A-Za-z0-9_-]", "_",
                                             os.path.basename(os.path.normpath(
                                                 directory))))
    info = {"path": path, "gone": []}
    if args.no_baseline:
        info.update(summary="skipped (--no-baseline)", path=None)
        return info

    stored = {"payloads": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
    known = stored.get("payloads") or {}

    if args.approve:
        sha, _dirty = _git()
        for r in results:
            if r.get("snapshot") is not None:
                known[r["file"]] = r["snapshot"]
        stored.update(payloads=known, approved=datetime.datetime.now().isoformat(
            timespec="seconds"), git=sha)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(stored, fh, indent=1, ensure_ascii=False, sort_keys=True)
        info["summary"] = ("approved %d payload(s) just now; later runs diff "
                           "against them" % sum(1 for r in results
                                                if r.get("snapshot") is not None))
        return info

    compared = changed = new = 0
    for r in results:
        snap = r.get("snapshot")
        if snap is None:
            continue
        old = known.get(r["file"])
        if old is None:
            new += 1
            r["findings"].append(_finding("baseline.new", "no approved baseline "
                                          "for this payload yet"))
            continue
        compared += 1
        delta = snapshot.diff(old, snap)
        if delta:
            changed += 1
            r["findings"].append(_finding(
                "baseline.changed", "%d fact(s) differ from the baseline "
                "approved %s" % (len(delta), stored.get("approved", "earlier")),
                details=delta))
    if not filtered:
        present = set(r["file"] for r in results)
        info["gone"] = sorted(f for f in known if f not in present)
    if not known:
        info["summary"] = ("none yet — review the pages, then run with "
                           "--approve to record one")
    else:
        info["summary"] = ("compared %d payload(s) against the baseline approved "
                           "%s: %d changed, %d with no baseline"
                           % (compared, stored.get("approved", "?"), changed, new))
    return info


# --- main -------------------------------------------------------------------------

def main(argv=None):
    args = _args(argv if argv is not None else sys.argv[1:])
    if args.list_checks:
        print(registry.listing())
        return 0
    if args.selftest:
        from corpus import selftest
        return selftest.main()

    directory = _resolve_dir(args.dir)
    args.out = os.path.abspath(args.out)
    files = discover(directory, args.only)
    if not files:
        print("no payloads found: %s/*.json%s" % (
            directory, (" matching %r" % args.only) if args.only else ""))
        return 2

    chrome = None
    browser_info = {"status": "off", "reason": "--browser off"}
    if args.browser != "off":
        chrome = browser.find_chrome()
        if chrome:
            browser_info = {"status": "on", "chrome": chrome}
        elif args.browser == "on":
            print("--browser on, but no Chrome/Chromium was found. Set AECB_CHROME "
                  "to its executable.")
            return 2
        else:
            browser_info = {"status": "off",
                            "reason": "no Chrome found; set AECB_CHROME to enable"}

    pages_dir = os.path.join(args.out, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    for old in glob.glob(os.path.join(pages_dir, "*.html")):
        os.remove(old)

    sha, dirty = _git()
    started = datetime.datetime.now()
    print("Checking %d payload(s) from %s" % (len(files), directory))
    keep_html = bool(chrome) or args.save_html != "none"
    results = []
    width = len(str(len(files)))
    for i, path in enumerate(files, start=1):
        result = checks.run_payload(path, keep_html=keep_html,
                                    slow_seconds=args.slow)
        results.append(result)
        sev = collections.Counter(f["severity"] for f in result["findings"])
        status = report.status_of(result)
        print("[%*d/%d] %-5s %s%s" % (
            width, i, len(files), "ok" if status == "ok" else status,
            result["file"],
            ("  " + " · ".join("%d %s" % (sev[s], s) for s in registry.SEVERITIES
                               if sev[s] and s != registry.INFO))
            if status != "ok" else ""))

    if chrome:
        work = []
        for r in results:
            if r.get("html"):
                blob = None
                try:
                    blob = pagetext.blob(r["html"])
                except pagetext.BlobError:   # hygiene.blob already says so
                    pass
                rows = len(pagetext.heatmap_rows(blob)) if blob is not None else None
                events = len(((blob or {}).get("applications") or {})
                             .get("events") or []) if blob is not None else None
                work.append((r, r["html"], (rows, events)))
        print("Browser pass: %d page(s), %d at a time ..." % (len(work), args.jobs))
        browser_info["failures"] = browser.run(chrome, args.jobs, work)

    run = {
        "meta": {"app": branding.APP_NAME, "dir": directory, "only": args.only,
                 "started": started.strftime("%Y-%m-%d %H:%M"), "git": sha,
                 "dirty": dirty,
                 "seconds": round((datetime.datetime.now() - started)
                                  .total_seconds(), 1)},
        "results": results,
        "browser": browser_info,
        "schema_drift": schema_drift(results),
    }
    run["baseline"] = baseline(args, results, directory, bool(args.only))

    for r in results:
        status = report.status_of(r)
        if r.get("html") and (args.save_html == "all" or (
                args.save_html == "problems" and status != "ok")):
            target = os.path.join(pages_dir, os.path.splitext(r["file"])[0] + ".html")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(r["html"])
            r["page_file"] = target

    summary = report.write(run, args.out, REPO)
    counts = collections.Counter(r["status"] for r in results)
    print("")
    print("%d ERROR · %d FAIL · %d WARN · %d clean   (%.0f s)" % (
        counts["ERROR"], counts["FAIL"], counts["WARN"], counts["ok"],
        run["meta"]["seconds"]))
    print("Report: %s" % summary)
    harness = sum(len(r.get("harness_errors") or []) for r in results)
    if harness:
        print("Note: %d check(s) raised inside the harness -- see section 7 of "
              "the report." % harness)
    failing = counts["ERROR"] or counts["FAIL"] or (args.strict and counts["WARN"])
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
