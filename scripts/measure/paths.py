"""Shared locations and helpers for the measurement tools.

Everything here is derived or overridable, never hard-coded, because these
scripts have to run from a checkout at any path AND against a backup tree as
well as the live one -- capturing the "before" baseline from a backup is how a
before/after comparison stays honest (see scripts/measure/README.md).

Python 3.9 compatible, like the rest of the repo.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

# scripts/measure/paths.py -> the repo root is two directories up.
ROOT = os.environ.get("AECB_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Scratch space for rendered HTML, captures and screenshots.
#
# NEVER inside ROOT. app.py's list_payloads() scans ReferenceJSON/ and would
# offer stray copies in the sidebar; the py39 sweep in HANDOFF walks every
# *.py under the tree; and check_no_mock.py reads rendered output. Keeping
# the work area outside the repo keeps all three honest.
WORK = os.environ.get("AECB_WORK") or os.path.join(
    tempfile.gettempdir(), "aecb-measure")

PAYLOAD = os.environ.get("AECB_PAYLOAD") or os.path.join(
    ROOT, "ReferenceJSON", "aecb_payload_archive_170623.json")

# The widths that matter, and why each one is here. A shorter list steps over a
# boundary: 1572 is .wrap's cap and the only width where --f reaches 1; 1560 is
# the design viewport; 1510/1509 straddles the density step; 1181/1180
# straddles the point where the brief rail stops being a grid track and the
# report column jumps 683->1074; 820 is where the spine disappears.
WIDTHS = [1572, 1560, 1510, 1509, 1400, 1181, 1180, 1100, 820, 760]

# Both rail states, always. The layout has two axes and the rail axis is the
# one that gets forgotten.
STATES = ("railoff", "railon")

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


def rail_variants(html: str) -> dict:
    """{'railoff': html, 'railon': html} -- the rail state as a FILE variant.

    Two rendered files rather than a click, so a capture is reproducible and
    does not depend on script timing.
    """
    on = html.replace('<body class="rail-off">', "<body>", 1)
    if on == html:
        raise SystemExit("render() produced no <body class=\"rail-off\"> to strip; "
                         "has page.py's default rail state changed?")
    return {"railoff": html, "railon": on}


def shoot(html: str, width: int, height: int, png: str, scale: int = 1) -> None:
    """Screenshot a string of HTML at a given size."""
    import subprocess
    page = work("_shot.html")
    with open(page, "w") as handle:
        handle.write(html)
    subprocess.run(
        [chrome(), "--headless", "--disable-gpu", "--no-sandbox",
         "--hide-scrollbars", "--force-device-scale-factor=%d" % scale,
         "--window-size=%d,%d" % (width, height),
         "--virtual-time-budget=6000", "--screenshot=" + png,
         "file://" + page], capture_output=True)


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
        handle.write(html.replace("</body>", script + "</body>"))
    dom = subprocess.run(
        [chrome(), "--headless", "--disable-gpu", "--no-sandbox",
         "--hide-scrollbars", "--force-device-scale-factor=1",
         "--window-size=%d,1200" % width, "--virtual-time-budget=6000",
         "--dump-dom", "file://" + page],
        capture_output=True, text=True).stdout
    match = re.search(
        r"%s(?:&lt;&lt;|<<)([A-Za-z0-9+/=]+)(?:&gt;&gt;|>>)%s" % (sentinel, sentinel),
        dom)
    if not match:
        raise RuntimeError("no probe payload at width %d" % width)
    return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))
