"""Shared fixtures for the FH AECB Analyzer test suite.

Run from the repository root:

    python -m pytest                              # everything available
    python -m pytest --cov --cov-report=xml       # plus coverage.xml for Sonar

Tests marked `browser` need a local Chrome/Chromium and `model` the local
Ollama service; both skip cleanly when absent.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
# The repository root (the aecb package), scripts/ (check_report, check_brief,
# the corpus harness) and scripts/measure/ (the Chrome finder).
for path in (ROOT, SCRIPTS, os.path.join(SCRIPTS, "measure")):
    if path not in sys.path:
        sys.path.insert(0, path)

FIXTURE_DIR = os.path.join(ROOT, "ReferenceJSON")
SYNTHETIC = os.path.join(FIXTURE_DIR,
                         "1_SyntheticJSONPayload_Delinquent_MultiFacility.json")
ARCHIVE = os.path.join(FIXTURE_DIR, "aecb_payload_archive_170623.json")
PATTERNS = os.path.join(FIXTURE_DIR, "2_SyntheticJSONPayload_Patterns.json")
FIXTURES = (SYNTHETIC, ARCHIVE, PATTERNS)
FIXTURE_IDS = ("synthetic", "archive", "patterns")


def load_fixture(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


_CACHE = {}


def fixture_payload(path) -> dict:
    """A fresh deep copy of a committed fixture (safe to mutate)."""
    if path not in _CACHE:
        _CACHE[path] = load_fixture(path)
    return copy.deepcopy(_CACHE[path])


def context_of(payload, name="test.json"):
    from aecb import context
    return context.from_bytes(json.dumps(payload).encode("utf-8"),
                              source_name=name)


# Settings that change what the app and the AI panel do. A developer's shell
# -- or ~/etc/aecb-analyzer/aecb.env, which app.py loads at start-up and
# which says AECB_ENV=dev on a developer machine (and AECB_OLLAMA_MODEL on a
# machine too small for the default model) -- must not decide test outcomes;
# a test that needs one sets it with monkeypatch.
_RUNTIME_SETTINGS = ("AECB_ENV", "AECB_AI_BRIEF", "AECB_CORE42_API_KEY",
                     "AECB_OLLAMA_MODEL")


@pytest.fixture(autouse=True)
def _clean_runtime_settings(monkeypatch, tmp_path):
    from aecb import settings
    for name in _RUNTIME_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "LOCAL_FILE", str(tmp_path / "absent.env"))


@pytest.fixture(params=FIXTURES, ids=FIXTURE_IDS)
def fixture_path(request):
    return request.param


@pytest.fixture
def synthetic_payload():
    return fixture_payload(SYNTHETIC)


@pytest.fixture
def archive_payload():
    return fixture_payload(ARCHIVE)


@pytest.fixture
def patterns_payload():
    return fixture_payload(PATTERNS)


class FakeProvider(types.SimpleNamespace):
    """A provider double: records each chat call and its reasoning level, and
    answers with `reply` -- a dict, or a function of (system, user, schema)
    that returns one."""

    def __init__(self, reply=None, name="fake", model="fake-model"):
        super().__init__(NAME=name, MODEL=model, DATA_NOTE="", reply=reply,
                         calls=[], efforts=[])

    def model(self):
        return self.MODEL

    def probe(self):
        return ""

    def chat(self, system, user, schema, effort=""):
        self.calls.append((system, user, schema))
        self.efforts.append(effort)
        if callable(self.reply):
            return self.reply(system, user, schema)
        return self.reply


def find_chrome():
    """Chrome's path or None -- the measure tools' finder, without exiting."""
    import paths  # scripts/measure/paths.py
    try:
        return paths.chrome()
    except SystemExit:
        return None
