"""The developer-machine settings file (aecb/settings.py)."""

from __future__ import annotations

import os

import pytest

from aecb import settings
from conftest import ROOT


def _file(tmp_path, text, mode=0o600):
    path = tmp_path / "aecb.env"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return str(path)


def test_parse_reads_the_documented_format():
    text = ("# comment\n\nexport AECB_ENV=dev\nA='x y'\nB=\"q\"\nC=a=b\n"
            "D=\n")
    assert settings.parse(text) == {"AECB_ENV": "dev", "A": "x y", "B": "q",
                                    "C": "a=b", "D": ""}


@pytest.mark.parametrize("line", ["no equals sign", "1BAD=x", "BAD KEY=x"])
def test_parse_refuses_a_malformed_line(line):
    with pytest.raises(settings.SettingsError, match="line 1"):
        settings.parse(line)


def test_a_missing_file_is_normal(tmp_path):
    assert settings.load_local(str(tmp_path / "absent.env")) == ""


def test_the_file_fills_only_unset_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("AECB_ENV", "uat")
    monkeypatch.delenv("AECB_AI_BRIEF", raising=False)
    path = _file(tmp_path, "AECB_ENV=dev\nAECB_AI_BRIEF=off\n")
    assert settings.load_local(path) == ""
    assert os.environ["AECB_ENV"] == "uat"               # the shell wins
    assert os.environ["AECB_AI_BRIEF"] == "off"
    monkeypatch.delenv("AECB_AI_BRIEF")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_file_others_can_read_is_not_applied(tmp_path, monkeypatch):
    monkeypatch.delenv("AECB_AI_BRIEF", raising=False)
    problem = settings.load_local(_file(tmp_path, "AECB_AI_BRIEF=off\n",
                                       mode=0o644))
    assert "readable by other users" in problem
    assert "AECB_AI_BRIEF" not in os.environ


def test_a_file_inside_the_repository_is_refused():
    path = os.path.join(ROOT, "pytest.ini")              # any in-repo file
    assert "inside the repository" in settings.load_local(path)


def test_a_malformed_file_is_reported_without_its_values(tmp_path):
    problem = settings.load_local(_file(tmp_path, "AECB_API_PASSWORD=s3cr3t\n"
                                                  "garbage line\n"))
    assert "line 2" in problem and "s3cr3t" not in problem
