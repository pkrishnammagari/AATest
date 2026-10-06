"""Smoke tests of the Streamlit entry point app.py (streamlit.testing AppTest)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from aecb import api, feedback, settings, ui
from aecb.brief import ollama
from conftest import ARCHIVE, ROOT

pytestmark = pytest.mark.filterwarnings("ignore")

_DEV_ONLY_BUTTONS = ("Open sample", "Reload CSS / JS", "Generate AI analysis")


@pytest.fixture
def api_payload(monkeypatch, tmp_path):
    with open(ARCHIVE, "rb") as fh:
        raw = fh.read()
    monkeypatch.setattr(api, "fetch_report", lambda *_args, **_kwargs: raw)
    monkeypatch.setenv("AECB_ARCHIVE_DIR", str(tmp_path / "archive"))
    return tmp_path / "archive"


def _app():
    return AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)


@pytest.fixture
def pages(monkeypatch):
    """What the app hosted on screen and offered as the download."""
    seen = {}
    real_sidebar = ui.report_sidebar

    def report_sidebar(ctx, html, requested=None):
        seen["download"] = html
        real_sidebar(ctx, html, requested=requested)

    def show_report(html):
        seen["screen"] = html
        # Still write an element where the report iframe goes: the AppTest
        # tree keeps a stale element from the previous run at any position the
        # new run leaves unwritten (the real app always writes the iframe).
        st.empty()

    monkeypatch.setattr(ui, "report_sidebar", report_sidebar)
    monkeypatch.setattr(ui, "show_report", show_report)
    return seen


def _fetched(at):
    at.text_input[0].input("G00000001").run()
    at.button[0].click().run()
    assert not at.exception and not at.error
    return at


def _captions(at):
    return " ".join(c.value for c in at.caption)


def _labels(at):
    return [b.label for b in at.button]


# --- uat / prod (the default) -------------------------------------------------

def test_renders_a_fetched_report(api_payload):
    at = _fetched(_app().run())
    # The fetched payload names another subject: the mismatch banner shows.
    assert any("Subject id mismatch" in w.value for w in at.warning)
    assert len(os.listdir(str(api_payload))) == 1       # archived once


@pytest.mark.parametrize("env", [None, "uat", "prod", "staging"])
def test_servers_get_no_development_tools(api_payload, monkeypatch, env):
    if env:
        monkeypatch.setenv("AECB_ENV", env)
    at = _app().run()
    assert not at.exception and not at.error
    assert not at.selectbox                              # no sample picker
    assert not at.get("file_uploader")                   # no uploader, ever
    at = _fetched(at)
    assert not set(_DEV_ONLY_BUTTONS) & set(_labels(at))


def test_rejects_a_malformed_subject_id(api_payload):
    at = _app().run()
    at.text_input[0].input("bad id!").run()
    at.button[0].click().run()
    assert any("up to 40 letters" in e.value for e in at.error)
    assert not os.path.exists(str(api_payload))


def test_shows_ai_coming_soon_by_default(api_payload, pages):
    _fetched(_app().run())
    assert 'class="bb-soon"' in pages["screen"]
    # The filed copy carries no AI control at all.
    assert 'id="briefBtn"' not in pages["download"]
    assert 'id="analysis"' not in pages["download"]


def test_live_on_uat_reports_core42_not_onboarded(api_payload, pages,
                                                  monkeypatch):
    monkeypatch.setenv("AECB_ENV", "uat")
    monkeypatch.setenv("AECB_AI_BRIEF", "live")
    at = _fetched(_app().run())
    assert "Core42 connector is not onboarded" in _captions(at)
    assert "Generate AI analysis" not in _labels(at)
    assert 'class="brief-btn" id="briefBtn"' in pages["screen"]
    assert pages["download"] == pages["screen"]


def test_survives_an_invalid_setting(api_payload, pages, monkeypatch):
    monkeypatch.setenv("AECB_ENV", "staging")
    monkeypatch.setenv("AECB_AI_BRIEF", "live")
    at = _fetched(_app().run())
    assert "restricted mode" in _captions(at)
    assert "staging" not in _captions(at)
    assert "Generate AI analysis" not in _labels(at)
    assert 'class="bb-soon"' in pages["screen"]


def test_does_not_load_the_brief_package():
    """DEP-4: unless the AI panel is live, app.py never imports aecb.brief.
    Checked in a fresh interpreter -- this one already has it -- by importing
    exactly the aecb modules app.py imports at top level."""
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    modules = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.split(".")[0] == "aecb":
            modules += ["%s.%s" % (node.module, a.name) if node.module == "aecb"
                        else node.module for a in node.names]
        elif isinstance(node, ast.Import):
            modules += [a.name for a in node.names if a.name.startswith("aecb")]
    assert "aecb.runtime" in modules and "aecb.ui" in modules
    code = ("import importlib, sys\n"
            "for m in %r: importlib.import_module(m)\n"
            "print(sorted(n for n in sys.modules\n"
            "             if n == 'aecb.brief' or n.startswith('aecb.brief.')))"
            % modules)
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


# --- dev ----------------------------------------------------------------------

@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv("AECB_ENV", "dev")
    monkeypatch.setattr(ollama, "probe", lambda: "")


def _sample(at, label):
    at.selectbox[0].select(label).run()
    next(b for b in at.button if b.label == "Open sample").click().run()
    assert not at.exception and not at.error
    return at


def test_dev_opens_a_sample_without_the_api(dev, api_payload, pages,
                                            monkeypatch):
    def no_api(*_args, **_kwargs):
        raise AssertionError("a sample must not call the API")
    monkeypatch.setattr(api, "fetch_report", no_api)
    at = _app().run()
    assert not at.get("file_uploader")
    assert os.path.basename(ARCHIVE) in at.selectbox[0].options
    at = _sample(at, os.path.basename(ARCHIVE))
    assert set(_DEV_ONLY_BUTTONS) <= set(_labels(at))
    assert "Environment `dev` · AI panel `live`" in _captions(at)
    assert "Development sample" in _captions(at)
    assert not at.warning                                # no mismatch check
    assert 'class="brief-btn" id="briefBtn"' in pages["screen"]
    assert not os.path.exists(str(api_payload))          # samples not archived


def test_dev_lists_archived_responses(dev, api_payload):
    os.makedirs(str(api_payload))
    with open(ARCHIVE, "rb") as src, \
            open(os.path.join(str(api_payload), "S1_20260101_000000.json"),
                 "wb") as dst:
        dst.write(src.read())
    at = _app().run()
    assert "archive/S1_20260101_000000.json" in at.selectbox[0].options


def test_dev_still_queries_the_api(dev, api_payload):
    at = _fetched(_app().run())
    assert "Live bureau report" in _captions(at)
    assert "Generate AI analysis" in _labels(at)


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception and not at.error
    return at


def test_dev_generates_the_analysis_block_by_block_and_records_feedback(
        dev, api_payload, pages, monkeypatch, tmp_path):
    monkeypatch.setattr(ollama, "chat", lambda system, user, schema, effort="":
                        {"findings": [], "unknowns": [], "background": []})
    monkeypatch.setenv(feedback.ENV_FEEDBACK_DIR, str(tmp_path / "fb"))
    at = _fetched(_app().run())
    assert 'class="an-state ready"' not in pages["screen"]
    at = _click(at, "Generate AI analysis")
    assert "lens ok" in _captions(at)
    assert 'class="an-state ready"' in pages["screen"]
    assert '<body class="rail-off analysis-on">' in pages["screen"]
    assert '<body class="rail-off">' in pages["download"]     # filed copy opens on the report
    at = _click(at, "👎 Not useful")
    assert "Thanks — recorded." in _captions(at)
    with open(str(tmp_path / "fb" / feedback.FILE_NAME), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 1 and '"verdict": "down"' in lines[0]
    assert '"subject": "G00000001"' in lines[0]


def test_dev_feedback_is_off_without_a_directory(dev, api_payload, monkeypatch):
    monkeypatch.setattr(ollama, "chat", lambda system, user, schema, effort="":
                        {"findings": [], "unknowns": [], "background": []})
    at = _click(_fetched(_app().run()), "Generate AI analysis")
    assert "Feedback is off" in _captions(at)
    assert "👎 Not useful" not in _labels(at)


def test_dev_can_preview_coming_soon(dev, monkeypatch, pages):
    monkeypatch.setenv("AECB_AI_BRIEF", "coming_soon")
    at = _sample(_app().run(), os.path.basename(ARCHIVE))
    assert "Generate AI analysis" not in _labels(at)
    assert 'class="bb-soon"' in pages["screen"]


# --- the local settings file --------------------------------------------------

def test_reads_the_local_settings_file(api_payload, monkeypatch, tmp_path):
    path = tmp_path / "aecb.env"
    path.write_text("AECB_ENV=dev\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(settings, "LOCAL_FILE", str(path))
    monkeypatch.setattr(ollama, "probe", lambda: "")
    at = _app().run()
    assert at.selectbox                                  # dev sample picker
    monkeypatch.delenv("AECB_ENV")                       # applied by the app


def test_an_unsafe_settings_file_is_not_used(api_payload, monkeypatch,
                                             tmp_path):
    path = tmp_path / "aecb.env"
    path.write_text("AECB_ENV=dev\n", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setattr(settings, "LOCAL_FILE", str(path))
    at = _app().run()
    assert not at.selectbox                              # still prod
    assert any("readable by other users" in w.value for w in at.warning)
