"""The optional browser pass: what report.js draws from the blob.

Sections 07 (heatmap) and 08 (applications timeline) are built client-side,
so the Python checks only ever see an empty container and the data blob. A
blob key that is missing or of the wrong type becomes 'undefined' or 'NaN' in
the browser and nowhere else. This pass loads each page in headless Chrome,
records any script error, and reads back what was actually drawn.

It reuses scripts/measure/paths.chrome() to find the browser (or
AECB_CHROME). Pages are probed in parallel; headless Chrome gives each
instance its own temporary profile.

Python 3.9 compatible.
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile

_MEASURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "measure")

# First thing in <head>: collect errors raised by report.js further down.
_ERRCAP = ("<script>window.__corpusErr=[];window.addEventListener('error',"
           "function(e){window.__corpusErr.push(String(e.message)+"
           "(e.lineno?' (line '+e.lineno+')':''));});</script>")

# Last thing in <body>: read back what was drawn, into document.title.
_PROBE = r"""<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    function q(s) { return [].slice.call(document.querySelectorAll(s)); }
    var out = {errors: window.__corpusErr || [],
               hmRows: q('#heatmap .hm-row').length,
               tlEvents: q('#enqTimeline .tl-event').length,
               bits: []};
    ['#heatmap', '#enqTimeline', '#stlHead', '#stlGrid'].forEach(function (sel) {
      var n = document.querySelector(sel);
      if (!n) return;
      out.bits.push([sel, 'text', n.textContent]);
      q(sel + ' [data-info]').forEach(function (e) {
        out.bits.push([sel, 'hover', e.getAttribute('data-info')]);
      });
    });
    var d = document.documentElement;
    out.overflowX = d.scrollWidth > d.clientWidth + 1;
    out.scrollW = d.scrollWidth;
    out.clientW = d.clientWidth;
    document.title = 'Q<<' + btoa(unescape(encodeURIComponent(
      JSON.stringify(out)))) + '>>Q';
  }, 300);
});
</script>"""

_TOKENS = (("undefined", re.compile(r"\bundefined\b")),
           ("NaN", re.compile(r"\bNaN\b")),
           ("null", re.compile(r"\bnull\b")),
           ("[object Object]", re.compile(r"\[object Object\]")),
           ("Invalid Date", re.compile(r"Invalid Date")))

WIDTH = 1560   # the design viewport (scripts/measure/paths.py)


def _measure_paths():
    """scripts/measure/paths.py -- the shared Chrome finder and CSP helper."""
    if _MEASURE not in sys.path:
        sys.path.insert(0, _MEASURE)
    import paths
    return paths


def find_chrome():
    """Chrome's path, or None. Honours AECB_CHROME like the measure tools."""
    try:
        return _measure_paths().chrome()
    except SystemExit:
        return None
    except Exception:   # noqa: BLE001
        return None


def _instrument(html):
    # The page's CSP admits only its own script; the probes need it removed.
    html = _measure_paths().without_csp(html)
    head = html.find("<head>")
    if head >= 0:
        html = html[:head + 6] + _ERRCAP + html[head + 6:]
    end = html.rfind("</body>")
    if end >= 0:
        html = html[:end] + _PROBE + html[end:]
    return html


def probe(chrome, html, timeout=90):
    """Load one page; return the probe dict or raise RuntimeError."""
    with tempfile.TemporaryDirectory(prefix="aecb-corpus-") as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(_instrument(html))
        # No --user-data-dir: headless Chrome already gives every instance a
        # throwaway profile, and an explicit one hangs it on macOS (measured
        # 28 Sep 2026: 0.6 s without, a 40 s timeout with). Parallel
        # instances were verified not to collide.
        cmd = [chrome, "--headless", "--disable-gpu", "--no-sandbox",
               "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
               "--window-size=%d,1200" % WIDTH, "--virtual-time-budget=6000",
               "--dump-dom", "file://" + page]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Chrome timed out after %ds" % timeout)
    if done.returncode != 0:
        raise RuntimeError("Chrome exited %d: %s" % (
            done.returncode, (done.stderr or "").strip()[-300:]))
    m = re.search(r"Q(?:&lt;&lt;|<<)([A-Za-z0-9+/=]+)(?:&gt;&gt;|>>)Q", done.stdout)
    if not m:
        raise RuntimeError("the page never reported back (the probe did not run "
                           "-- a script error before load, or a hung page)")
    return json.loads(base64.b64decode(m.group(1)).decode("utf-8"))


def findings_for(result, data, blob_counts):
    """Turn one probe into finding dicts (same shape as checks.Collector)."""
    from .registry import get
    out = []

    def add(check_id, message, details=None):
        chk = get(check_id)
        out.append({"check": check_id, "severity": chk.severity,
                    "layer": chk.layer, "message": message,
                    "details": list(details or [])[:12], "section": None,
                    "data": None})

    if data.get("errors"):
        add("browser.js_error", "%d script error(s) while drawing the page"
            % len(data["errors"]), details=data["errors"])

    from .checks import delivered_in
    delivered = result.get("delivered") or ""
    hits = []
    for sel, kind, value in data.get("bits") or []:
        for label, pattern in _TOKENS:
            for m in pattern.finditer(value or ""):
                if delivered_in(m.group(0), value, delivered):
                    continue
                a, b = max(0, m.start() - 45), min(len(value), m.end() + 45)
                hits.append("[%s %s] %r in ...%s..." % (sel, kind, label,
                                                        value[a:b]))
    if hits:
        add("browser.token", "%d leaked token(s) in client-drawn content"
            % len(hits), details=hits)

    rows_want, events_want = blob_counts
    problems = []
    if rows_want is not None and data.get("hmRows") != rows_want:
        problems.append("heatmap drew %s row(s); the blob holds %d"
                        % (data.get("hmRows"), rows_want))
    if events_want is not None and data.get("tlEvents") != events_want:
        problems.append("timeline drew %s marker(s); the blob holds %d"
                        % (data.get("tlEvents"), events_want))
    if problems:
        add("browser.counts", problems[0], details=problems[1:])

    if data.get("overflowX"):
        add("browser.overflow", "page is %spx wide in a %spx window"
            % (data.get("scrollW"), data.get("clientW")))
    return out


def run(chrome, jobs, work):
    """work: [(result, html, (rows, events))]. Adds findings to each result.

    Returns the number of pages the browser could not probe; each one also
    gets a harness error on its result, so it is never silently unchecked.
    """
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = dict((pool.submit(probe, chrome, html), (result, counts))
                       for result, html, counts in work)
        for fut in concurrent.futures.as_completed(futures):
            result, counts = futures[fut]
            try:
                data = fut.result()
            except Exception as exc:   # noqa: BLE001
                failures += 1
                result["harness_errors"].append("browser pass: %s" % exc)
                result["browser"] = {"error": str(exc)}
                continue
            result["findings"].extend(findings_for(result, data, counts))
            result["browser"] = {"hmRows": data.get("hmRows"),
                                 "tlEvents": data.get("tlEvents"),
                                 "errors": len(data.get("errors") or [])}
    return failures
