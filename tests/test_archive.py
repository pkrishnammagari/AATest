"""aecb.archive: real bureau responses are kept outside the app, privately."""

from __future__ import annotations

import datetime
import os
import stat

from aecb import archive
from conftest import ROOT

_NOW = datetime.datetime(2026, 9, 29, 10, 0, 0)


def test_archiving_is_off_when_unset(monkeypatch):
    monkeypatch.delenv(archive.ENV_ARCHIVE_DIR, raising=False)
    assert "not set" in archive.status()
    assert archive.save_response(b"{}", "S1") is None


def test_a_directory_inside_the_app_is_refused(monkeypatch):
    inside = os.path.join(ROOT, "ReferenceJSON", "api_responses_test")
    monkeypatch.setenv(archive.ENV_ARCHIVE_DIR, inside)
    assert "inside the application folder" in archive.status()
    assert archive.save_response(b"{}", "S1") is None
    assert not os.path.exists(inside)


def test_saved_verbatim_and_private(tmp_path, monkeypatch):
    target = tmp_path / "archive"
    monkeypatch.setenv(archive.ENV_ARCHIVE_DIR, str(target))
    assert archive.status() is None
    path = archive.save_response(b'{"a": 1}', "G123", now=_NOW)
    assert os.path.basename(path) == "G123_20260929_100000.json"
    with open(path, "rb") as fh:
        assert fh.read() == b'{"a": 1}'
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(str(target)).st_mode) == 0o700


def test_same_second_saves_never_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv(archive.ENV_ARCHIVE_DIR, str(tmp_path))
    first = archive.save_response(b"1", "G1", now=_NOW)
    second = archive.save_response(b"2", "G1", now=_NOW)
    assert first != second and second.endswith("_1.json")


def test_subject_ids_are_reduced_to_safe_file_names(tmp_path, monkeypatch):
    monkeypatch.setenv(archive.ENV_ARCHIVE_DIR, str(tmp_path))
    path = archive.save_response(b"1", "../../etc/passwd", now=_NOW)
    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path).startswith("______etc_passwd_")
