"""Shared locations and helpers for the measurement tools.

Everything here is derived or overridable, never hard-coded, because these
scripts have to run from a checkout at any path AND against a second
checkout of an older revision -- capturing the "before" baseline from the old
code is how a before/after comparison stays honest (see
scripts/measure/README.md).

Python 3.9 compatible, like the rest of the repo.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

# The report's Content-Security-Policy allows exactly one inline script, by
# hash. A probe script injected by these tools would be blocked, so every
# injection goes through without_csp(). That the unmodified page runs under
# its own policy is asserted separately by the test suite (tests/).
_CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n?')


def without_csp(html: str) -> str:
    """The page minus its CSP <meta>, so an injected probe script can run."""
    return _CSP_META.sub("", html, count=1)

# scripts/measure/paths.py -> the repo root is two directories up.
ROOT = os.environ.get("AECB_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Scratch space for rendered HTML, captures and screenshots.
#
# NEVER inside ROOT: app.py's dev sample picker scans ReferenceJSON/ and would
# offer stray copies in the sidebar, and repository-wide checks (tests, the
# Python 3.9 syntax test) would pick up generated files.
WORK = os.environ.get("AECB_WORK") or os.path.join(
    tempfile.gettempdir(), "aecb-measure")

PAYLOAD = os.environ.get("AECB_PAYLOAD") or os.path.join(
    ROOT, "ReferenceJSON", "aecb_payload_archive_170623.json")

# The widths that matter, and why each one is here. A shorter list steps over a
# boundary: 1572 is where --f first reaches 1; 1560 is the design viewport;
# 1510/1509 straddles the density step; 1181/1180 straddles the report
# column's media-query step at 1180px; 820 is where the spine disappears.
WIDTHS = [1572, 1560, 1510, 1509, 1400, 1181, 1180, 1100, 820, 760]

# The layout states to capture: one, the report, with body.rail-off (the
# layout-state class the CSS is calibrated to). The AI Analysis view hides the
# report rather than reflowing it, so it has no geometry of its own to track.
STATES = ("report",)

_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
)


def chrome() -> str:
    """Headless Chrome, however this machine spells it."""
    explicit = os.environ.get("AECB_CHROME")
    if explicit:
        return explicit
    for candidate in _CHROME_CANDIDATES:
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    raise SystemExit(
        "No Chrome/Chromium found. Set AECB_CHROME to its executable path.")


def work(*parts) -> str:
    """A path inside the work area, with its directory created."""
    path = os.path.join(WORK, *parts)
    directory = path if not os.path.splitext(path)[1] else os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    return path


def render(payload=None) -> str:
    """The report as one standalone HTML string, rendered from ROOT.

    Note for anyone tempted to render the live tree and a backup tree in the
    SAME process: don't. Python caches the first `aecb` package it imports, so
    the second render would silently come from the first tree. Run them as
    separate processes with AECB_ROOT set -- which is what the harness does.
    """
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    previous = os.getcwd()
    os.chdir(ROOT)
    try:
        from aecb import context
        from aecb.render.page import clear_cache, render_page
        clear_cache()
        return render_page(context.from_file(payload or PAYLOAD))
    finally:
        os.chdir(previous)


def variants(html: str) -> dict:
    """{state: html} -- each layout state as a FILE variant.

    Rendered files rather than clicks, so a capture is reproducible and does
    not depend on script timing. The one state asserts the body class every
    measured geometry is keyed on, so a change to page.py's default cannot
    pass unnoticed.
    """
    if '<body class="rail-off">' not in html:
        raise SystemExit("render() produced no <body class=\"rail-off\">; "
                         "has page.py's default layout state changed?")
    return {"report": html}


def shoot(html: str, width: int, height: int, png: str, scale: int = 1) -> None:
    """Screenshot a string of HTML at a given size."""
    import subprocess
    page = work("_shot.html")
    with open(page, "w") as handle:
        handle.write(html)
    done = subprocess.run(
        [chrome(), "--headless", "--disable-gpu", "--no-sandbox",
         "--hide-scrollbars", "--force-device-scale-factor=%d" % scale,
         "--window-size=%d,%d" % (width, height),
         "--virtual-time-budget=6000", "--screenshot=" + png,
         "file://" + page], capture_output=True, text=True, timeout=180)
    # A Chrome crash otherwise surfaces later as a missing PNG with no clue.
    if done.returncode != 0:
        raise RuntimeError("Chrome exited %d taking the screenshot: %s"
                           % (done.returncode, (done.stderr or "").strip()[-400:]))


def probe(html: str, script: str, width: int, sentinel: str = "M") -> dict:
    """Run `script` against `html` in headless Chrome and return its JSON.

    Headless Chrome here has no devtools driver, so the way to get numbers out
    of it is --dump-dom plus a script that writes its result into
    document.title between two sentinels. The payload is base64 so that quotes,
    ampersands and em dashes survive both JSON and HTML escaping -- btoa alone
    cannot encode a UTF-8 em dash, which is why the JS wraps it.
    """
    import base64
    import json
    import re
    import subprocess

    page = work("_probe.html")
    with open(page, "w") as handle:
        handle.write(without_csp(html).replace("</body>", script + "</body>"))
    done = subprocess.run(
        [chrome(), "--headless", "--disable-gpu", "--no-sandbox",
         "--hide-scrollbars", "--force-device-scale-factor=1",
         "--window-size=%d,1200" % width, "--virtual-time-budget=6000",
         "--dump-dom", "file://" + page],
        capture_output=True, text=True, timeout=180)
    # Fail on the crash, not on the cryptic "no probe payload" it causes.
    if done.returncode != 0:
        raise RuntimeError("Chrome exited %d probing at width %d: %s"
                           % (done.returncode, width,
                              (done.stderr or "").strip()[-400:]))
    match = re.search(
        r"%s(?:&lt;&lt;|<<)([A-Za-z0-9+/=]+)(?:&gt;&gt;|>>)%s" % (sentinel, sentinel),
        done.stdout)
    if not match:
        raise RuntimeError("no probe payload at width %d" % width)
    return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))
