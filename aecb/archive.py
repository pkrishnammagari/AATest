"""Save a reference copy of each successful API response.

Used only by app_api.py -- the dev harness (app.py) never imports this module,
so fixture browsing can never write to disk. Files land in
ReferenceJSON/api_responses/ (gitignored; real bureau data), one per fetch,
named <subject>_<YYYYMMDD_HHMMSS>.json so repeat fetches for the same subject
never overwrite each other. The bytes are written verbatim: a reference copy
must preserve exactly what the API sent, not a re-serialization.

A save failure must never break the user's fetch: save_response logs and
returns None. Payload contents are never logged -- only subject id, path and
byte count.
"""

from __future__ import annotations

import datetime
import logging
import os
import re

_LOG = logging.getLogger("aecb.archive")

_HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(os.path.dirname(_HERE), "ReferenceJSON", "api_responses")

# How many same-second collisions to tolerate before giving up. Reached only
# if one subject is fetched 100+ times within a single second.
_MAX_SUFFIX = 100


def save_response(raw: bytes, subject_id: str, directory: str = None,
                  now: datetime.datetime = None) -> "str | None":
    """Write raw response bytes to a timestamped file; return the path.

    directory and now exist for tests; production callers pass neither.
    Returns None on any failure -- the caller's fetch already succeeded, so
    an archive problem is a log entry, not a user-facing error.
    """
    try:
        directory = directory or ARCHIVE_DIR
        stamp = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", subject_id.strip())[:40] or "report"
        os.makedirs(directory, exist_ok=True)
        for suffix in range(_MAX_SUFFIX):
            name = ("%s_%s.json" % (safe, stamp) if suffix == 0
                    else "%s_%s_%d.json" % (safe, stamp, suffix))
            path = os.path.join(directory, name)
            try:
                # O_EXCL claims the filename atomically, so two sessions
                # archiving the same subject in the same second cannot
                # overwrite each other.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            _LOG.info("Archived API response for %r to %s (%d bytes)",
                      subject_id, path, len(raw))
            return path
        raise OSError("no free filename after %d attempts for %s_%s"
                      % (_MAX_SUFFIX, safe, stamp))
    except Exception as exc:
        _LOG.warning("Could not archive API response for %r: %s",
                     subject_id, exc)
        return None
