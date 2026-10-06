"""Underwriter feedback on an AI analysis: one line per vote, kept outside
the app, privately.

A thumbs up or down (and an optional comment) on a generated analysis is the
raw material for reviewing the support's quality over time, so it is written
to an append-only JSONL file in the directory named by AECB_FEEDBACK_DIR:

  * one JSON object per line: timestamp, user (when the host knows one),
    subject id, the analysis's generation id and provenance, the verdict,
    the comment;
  * the directory is created 0700 and the file 0600 -- readable by the
    service account only, like the response archive;
  * the file is opened O_APPEND; nothing is ever rewritten.

When AECB_FEEDBACK_DIR is unset, or points inside the application tree,
feedback is OFF: nothing is written and status() says why, so the host can
show it. A write failure is logged and never breaks the page. The comment is
free text from the user: control characters are stripped and it is capped,
and it is never logged -- only the verdict is.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re

from .archive import inside_app_tree

_LOG = logging.getLogger("aecb.feedback")

ENV_FEEDBACK_DIR = "AECB_FEEDBACK_DIR"
FILE_NAME = "feedback.jsonl"

VERDICTS = ("up", "down")
_MAX_COMMENT = 1000
_DIR_MODE = 0o700
_FILE_MODE = 0o600
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def configured_dir() -> "str | None":
    """The feedback directory from the environment, or None if unusable."""
    value = (os.environ.get(ENV_FEEDBACK_DIR) or "").strip()
    if not value or inside_app_tree(value):
        return None
    return value


def status() -> "str | None":
    """None when feedback is on; otherwise a one-line reason it is off."""
    value = (os.environ.get(ENV_FEEDBACK_DIR) or "").strip()
    if not value:
        return "Feedback is off: %s is not set." % ENV_FEEDBACK_DIR
    if inside_app_tree(value):
        return ("Feedback is off: %s points inside the application folder; "
                "it must be outside it." % ENV_FEEDBACK_DIR)
    return None


def clean_comment(comment) -> str:
    text = _CONTROL_RE.sub("", str(comment or "")).replace("\n", " ")
    return text.strip()[:_MAX_COMMENT]


def entry(analysis: dict, verdict: str, subject, user, comment="",
          now: datetime.datetime = None) -> dict:
    """The line to record for one vote. Raises ValueError on a bad verdict."""
    if verdict not in VERDICTS:
        raise ValueError("verdict must be one of %s" % ", ".join(VERDICTS))
    return {
        "ts": (now or datetime.datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
        "user": user or "-",
        "subject": subject or "-",
        "generation_id": analysis["generation_id"],
        "verdict": verdict,
        "comment": clean_comment(comment),
        "prompt_version": analysis["prompt_version"],
        "provider": analysis["provider"],
        "model": analysis["model"],
        "payload_hash": analysis["payload_hash"],
    }


def record(line: dict) -> "str | None":
    """Append one entry to AECB_FEEDBACK_DIR; return the file path, or None
    when off or failed."""
    directory = configured_dir()
    if directory is None:
        _LOG.warning("Feedback not recorded: %s", status())
        return None
    path = os.path.join(directory, FILE_NAME)
    try:
        os.makedirs(directory, mode=_DIR_MODE, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, _FILE_MODE)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:
        _LOG.warning("Could not record feedback: %s", exc)
        return None
    _LOG.info("Recorded feedback %s for generation %s", line["verdict"],
              line["generation_id"])
    return path
