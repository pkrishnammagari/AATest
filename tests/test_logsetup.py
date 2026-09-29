"""aecb.logsetup: configured once, never into the application tree."""

from __future__ import annotations

import logging
import logging.handlers

import pytest

from aecb import logsetup


@pytest.fixture
def clean_logger():
    root = logging.getLogger("aecb")
    saved = (list(root.handlers), root.level, root.propagate,
             getattr(root, logsetup._MARKER, False))
    root.handlers = []
    if hasattr(root, logsetup._MARKER):
        delattr(root, logsetup._MARKER)
    yield root
    for handler in root.handlers:
        handler.close()
    root.handlers, root.level, root.propagate = saved[0], saved[1], saved[2]
    setattr(root, logsetup._MARKER, saved[3])


def test_configure_is_idempotent(clean_logger, monkeypatch):
    monkeypatch.delenv(logsetup.ENV_LOG_DIR, raising=False)
    logsetup.configure()
    logsetup.configure()
    assert len(clean_logger.handlers) == 1           # stderr only


def test_rotating_file_when_a_log_dir_is_set(clean_logger, monkeypatch, tmp_path):
    monkeypatch.setenv(logsetup.ENV_LOG_DIR, str(tmp_path / "logs"))
    logsetup.configure()
    files = [h for h in clean_logger.handlers
             if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(files) == 1
    logging.getLogger("aecb.test").info("hello")
    files[0].flush()
    assert "hello" in (tmp_path / "logs" / logsetup.LOG_FILE).read_text()
