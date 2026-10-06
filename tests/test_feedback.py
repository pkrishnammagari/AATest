"""aecb.feedback: votes on an analysis are kept outside the app, privately."""

from __future__ import annotations

import datetime
import json
import os
import stat

import pytest

from aecb import feedback
from conftest import ROOT

_NOW = datetime.datetime(2026, 10, 1, 14, 21, 7)
_ANALYSIS = {"generation_id": "abc123", "prompt_version": "p1.0",
             "provider": "ollama", "model": "m", "payload_hash": "5f3a"}


def test_feedback_is_off_when_unset(monkeypatch):
    monkeypatch.delenv(feedback.ENV_FEEDBACK_DIR, raising=False)
    assert "not set" in feedback.status()
    assert feedback.record(feedback.entry(_ANALYSIS, "up", "S1", None)) is None


def test_a_directory_inside_the_app_is_refused(monkeypatch):
    inside = os.path.join(ROOT, "ReferenceJSON", "feedback_test")
    monkeypatch.setenv(feedback.ENV_FEEDBACK_DIR, inside)
    assert "inside the application folder" in feedback.status()
    assert feedback.record(feedback.entry(_ANALYSIS, "up", "S1", None)) is None
    assert not os.path.exists(inside)


def test_entries_are_appended_as_private_json_lines(tmp_path, monkeypatch):
    target = tmp_path / "feedback"
    monkeypatch.setenv(feedback.ENV_FEEDBACK_DIR, str(target))
    assert feedback.status() is None
    first = feedback.entry(_ANALYSIS, "up", "G123", "jdoe", "fine", now=_NOW)
    second = feedback.entry(_ANALYSIS, "down", "G123", None, now=_NOW)
    path = feedback.record(first)
    assert feedback.record(second) == path
    with open(path, encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh]
    assert [l["verdict"] for l in lines] == ["up", "down"]
    assert lines[0]["ts"] == "2026-10-01T14:21:07"
    assert lines[0]["user"] == "jdoe" and lines[1]["user"] == "-"
    assert lines[0]["generation_id"] == "abc123"
    assert lines[0]["comment"] == "fine" and lines[1]["comment"] == ""
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(str(target)).st_mode) == 0o700


def test_comments_are_sanitised_and_capped():
    noisy = "line one\nline\x00two\x1b[31m " + "x" * 2000
    cleaned = feedback.clean_comment(noisy)
    assert "\n" not in cleaned and "\x00" not in cleaned and "\x1b" not in cleaned
    assert cleaned.startswith("line one linetwo[31m ")
    assert len(cleaned) == 1000


def test_only_up_or_down_are_verdicts():
    with pytest.raises(ValueError):
        feedback.entry(_ANALYSIS, "meh", "S1", None)
