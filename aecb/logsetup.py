"""Logging for the Streamlit app -- configured once per process.

Every "aecb.*" logger (API client error dumps, archive, render failures,
audit lines) goes to:

  * stderr, always -- picked up by the service manager (systemd/journald);
  * a size-rotated file, aecb.log, in the directory named by AECB_LOG_DIR,
    when that variable is set. Never inside the application tree.

Streamlit re-executes the entry script on every interaction, so configure()
is idempotent: handlers are attached only on the first call.

Logs carry CB subject ids (they are the audit trail of who was queried) but
never payload contents.
"""

from __future__ import annotations

import logging
import logging.handlers
import os

ENV_LOG_DIR = "AECB_LOG_DIR"
LOG_FILE = "aecb.log"

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUPS = 10
_MARKER = "_aecb_configured"


def configure() -> None:
    """Attach the aecb handlers once. Safe to call on every rerun."""
    root = logging.getLogger("aecb")
    if getattr(root, _MARKER, False):
        return
    formatter = logging.Formatter(_FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    log_dir = (os.environ.get(ENV_LOG_DIR) or "").strip()
    if log_dir:
        try:
            os.makedirs(log_dir, mode=0o750, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(log_dir, LOG_FILE), maxBytes=_MAX_BYTES,
                backupCount=_BACKUPS, encoding="utf-8")
            handler.setFormatter(formatter)
            root.addHandler(handler)
        except OSError as exc:
            root.warning("Cannot write logs to %s=%s (%s); logging to stderr "
                         "only.", ENV_LOG_DIR, log_dir, exc)

    root.setLevel(logging.INFO)
    root.propagate = False
    setattr(root, _MARKER, True)
