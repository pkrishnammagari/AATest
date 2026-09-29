"""Save a reference copy of each successful API response.

Used only by app_api.py -- the development harness (app.py) never imports this
module. Responses are real bureau data, so they are written OUTSIDE the
application tree, to the directory named by the AECB_ARCHIVE_DIR environment
variable:

  * one file per fetch, <subject>_<YYYYMMDD_HHMMSS>.json, claimed with O_EXCL
    so two sessions archiving the same subject in the same second cannot
    overwrite each other;
  * the directory is created 0700 and each file 0600 -- readable by the
    service account only;
  * the bytes are written verbatim: a reference copy must preserve exactly
    what the API sent, not a re-serialization.

When AECB_ARCHIVE_DIR is unset, or points inside the application tree,
archiving is OFF: nothing is written and status() says why, so the host can
show it. A save failure never breaks the user's fetch -- save_response logs
and returns None. Payload contents are never logged, only subject id, path
and byte count. Retention (purging old files) is an operations task; see
docs/OPERATIONS.md.
"""

from __future__ import annotations

import datetime
import logging
import os
import re

_LOG = logging.getLogger("aecb.archive")

ENV_ARCHIVE_DIR = "AECB_ARCHIVE_DIR"

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# How many same-second collisions to tolerate before giving up. Reached only
# if one subject is fetched 100+ times within a single second.
_MAX_SUFFIX = 100

_DIR_MODE = 0o700
_FILE_MODE = 0o600


def _inside_app_tree(path: str) -> bool:
    root = os.path.realpath(_APP_ROOT)
    target = os.path.realpath(path)
    return os.path.commonpath([root, target]) == root


def configured_dir() -> "str | None":
    """The archive directory from the environment, or None if unusable."""
    value = (os.environ.get(ENV_ARCHIVE_DIR) or "").strip()
    if not value or _inside_app_tree(value):
        return None
    return value


def status() -> "str | None":
    """None when archiving is on; otherwise a one-line reason it is off."""
    value = (os.environ.get(ENV_ARCHIVE_DIR) or "").strip()
    if not value:
        return ("Response archiving is off: %s is not set."
                % ENV_ARCHIVE_DIR)
    if _inside_app_tree(value):
        return ("Response archiving is off: %s points inside the application "
                "folder; it must be outside it." % ENV_ARCHIVE_DIR)
    return None


def _safe_name(subject_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", subject_id.strip())[:40] or "report"


def _write_exclusive(directory: str, safe: str, stamp: str, raw: bytes) -> str:
    """Write raw to the first free <safe>_<stamp>[_n].json; return its path."""
    for suffix in range(_MAX_SUFFIX):
        name = ("%s_%s.json" % (safe, stamp) if suffix == 0
                else "%s_%s_%d.json" % (safe, stamp, suffix))
        path = os.path.join(directory, name)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        return path
    raise OSError("no free filename after %d attempts for %s_%s"
                  % (_MAX_SUFFIX, safe, stamp))


def save_response(raw: bytes, subject_id: str, directory: str = None,
                  now: datetime.datetime = None) -> "str | None":
    """Write raw response bytes to a timestamped file; return the path.

    directory and now exist for tests; production callers pass neither and
    the directory comes from AECB_ARCHIVE_DIR. Returns None when archiving is
    off or the write fails -- the caller's fetch already succeeded, so an
    archive problem is a log entry, not a user-facing error.
    """
    directory = directory or configured_dir()
    if directory is None:
        _LOG.warning("API response for %r not archived: %s",
                     subject_id, status())
        return None
    try:
        os.makedirs(directory, mode=_DIR_MODE, exist_ok=True)
        stamp = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
        path = _write_exclusive(directory, _safe_name(subject_id), stamp, raw)
    except OSError as exc:
        _LOG.warning("Could not archive API response for %r: %s",
                     subject_id, exc)
        return None
    _LOG.info("Archived API response for %r to %s (%d bytes)",
              subject_id, path, len(raw))
    return path
