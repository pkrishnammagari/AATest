"""The report in a real browser: its script runs under its own CSP.

Loads the unmodified page in headless Chrome and reads back the DOM after
report.js has run. A script the Content-Security-Policy blocked would leave
the heatmap and the application timeline empty.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from aecb import context, runtime
from aecb.render.page import render_page
from conftest import SYNTHETIC, find_chrome

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def chrome():
    path = find_chrome()
    if not path:
        pytest.skip("no Chrome/Chromium found (set AECB_CHROME)")
    return path


def _dom(chrome, html, tmp_path):
    page = tmp_path / "page.html"
    page.write_text(html, encoding="utf-8")
    done = subprocess.run([chrome, "--headless", "--disable-gpu",
                           "--virtual-time-budget=5000", "--dump-dom",
                           page.as_uri()],
                          capture_output=True, text=True, timeout=120)
    # Drop the script source: it contains the markup strings it would draw.
    return re.sub(r"<script>.*?</script>", "", done.stdout, flags=re.S)


def test_report_script_runs_under_the_csp(chrome, tmp_path):
    # The page a server ships by default: AI panel "coming soon".
    html = render_page(context.from_file(SYNTHETIC), ai_mode=runtime.AI_SOON)
    dom = _dom(chrome, html, tmp_path)
    assert dom.count('class="hm-row') > 1       # heatmap rows drawn by report.js
    assert 'class="tl-event' in dom             # application markers drawn
    assert 'class="bb-soon"' in dom             # the coming-soon badge


def test_a_tampered_script_is_blocked(chrome, tmp_path):
    html = render_page(context.from_file(SYNTHETIC))
    tampered = html.replace("window.__AECB = ", "window.__AECB =  ", 1)
    dom = _dom(chrome, tampered, tmp_path)
    assert 'class="tl-event' not in dom
