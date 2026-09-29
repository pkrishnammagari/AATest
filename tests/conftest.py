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
FIXTURES = (SYNTHETIC, ARCHIVE)


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


@pytest.fixture(params=FIXTURES, ids=("synthetic", "archive"))
def fixture_path(request):
    return request.param


@pytest.fixture
def synthetic_payload():
    return fixture_payload(SYNTHETIC)


@pytest.fixture
def archive_payload():
    return fixture_payload(ARCHIVE)


def find_chrome():
    """Chrome's path or None -- the measure tools' finder, without exiting."""
    import paths  # scripts/measure/paths.py
    try:
        return paths.chrome()
    except SystemExit:
        return None
