"""Smoke tests of the two Streamlit entry points (streamlit.testing AppTest)."""

from __future__ import annotations

import os

import pytest
from streamlit.testing.v1 import AppTest

from aecb import api
from conftest import ARCHIVE, ROOT

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture
def api_payload(monkeypatch, tmp_path):
    with open(ARCHIVE, "rb") as fh:
        raw = fh.read()
    monkeypatch.setattr(api, "fetch_report", lambda *_args, **_kwargs: raw)
    monkeypatch.setenv("AECB_ARCHIVE_DIR", str(tmp_path / "archive"))
    return tmp_path / "archive"


def _app(name):
    return AppTest.from_file(os.path.join(ROOT, name), default_timeout=120)


def test_production_entry_renders_a_fetched_report(api_payload):
    at = _app("app_api.py").run()
    assert not at.exception and not at.error
    at.text_input[0].input("G00000001").run()
    at.button[0].click().run()
    assert not at.exception and not at.error
    # The fetched payload names another subject: the mismatch banner shows.
    assert any("Subject id mismatch" in w.value for w in at.warning)
    assert len(os.listdir(str(api_payload))) == 1       # archived once
    labels = [b.label for b in at.button]
    assert "Generate AI brief" not in labels and "Reload CSS / JS" not in labels


def test_production_entry_rejects_a_malformed_subject_id(api_payload):
    at = _app("app_api.py").run()
    at.text_input[0].input("bad id!").run()
    at.button[0].click().run()
    assert any("up to 40 letters" in e.value for e in at.error)
    assert not os.path.exists(str(api_payload))


def test_development_harness_renders_a_fixture():
    at = _app("app.py").run()
    assert not at.exception and not at.error
    assert at.selectbox and len(at.selectbox[0].options) >= 2
