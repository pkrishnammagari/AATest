"""Load a developer machine's settings file into the process environment.

On a server, systemd loads /etc/aecb-analyzer/aecb.env into the app's
environment (deploy/aecb-analyzer.service) and this module finds nothing to
do. On a developer machine there is no systemd, so the app reads the same
kind of file itself, from a fixed place in your home folder:

    ~/etc/aecb-analyzer/aecb.env

Create it once from deploy/aecb.env.example (mode 0600; see README.md) and
set AECB_ENV=dev in it. The same file serves the app, the live-API tests and
scripts/check_corpus.py.

Rules, kept from the server's own: the file must not be readable by other
users and must not sit inside the repository (so credentials cannot be
committed); KEY=VALUE lines, # comments, an optional leading "export " and
optional surrounding quotes; values are taken literally. A variable already
set in the process environment wins over the file, so a one-off override
needs no edit. Changes take effect when the app restarts.
"""

from __future__ import annotations

import logging
import os
import re
import stat

_LOG = logging.getLogger("aecb.settings")

LOCAL_FILE = os.path.join(os.path.expanduser("~"), "etc", "aecb-analyzer",
                          "aecb.env")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEY = re.compile(r"^[A-Za-z_]\w*$", re.ASCII)


class SettingsError(Exception):
    """The settings file exists but cannot be used. The message is safe to
    show: it names the file and the rule, never a value."""


def _inside_repo(path: str) -> bool:
    repo = os.path.realpath(_REPO)
    return os.path.commonpath([repo, os.path.realpath(path)]) == repo


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(text: str, source: str = "settings file") -> dict:
    """KEY=VALUE pairs from the file's text (see the module docstring)."""
    out = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[len("export "):].lstrip()
        key, sep, value = entry.partition("=")
        key = key.strip()
        if not sep or not _KEY.match(key):
            raise SettingsError("%s line %d is not KEY=VALUE" % (source, number))
        out[key] = _unquote(value.strip())
    return out


def read(path: str) -> dict:
    """The file's settings, {} when it does not exist. Raises SettingsError
    when it exists but breaks a rule."""
    if not os.path.isfile(path):
        return {}
    if _inside_repo(path):
        raise SettingsError("%s is inside the repository; keep it outside so "
                            "credentials cannot be committed" % path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if os.name != "nt" and mode & 0o077:
        raise SettingsError("%s is readable by other users (mode %o); run "
                            "chmod 600 on it" % (path, mode))
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read(), source=path)


# Problems already logged, so Streamlit's rerun-per-interaction logs each one
# once per process rather than on every click.
_LOGGED = set()


def log_once(problem: str) -> None:
    """Log a load_local() problem once per process (after logging is set)."""
    if problem and problem not in _LOGGED:
        _LOGGED.add(problem)
        _LOG.error("%s", problem)


def load_local(path: str = None) -> str:
    """Apply the local settings file to os.environ; '' or a problem.

    Variables already set are left alone. A missing file is normal (every
    server) and returns ''. A file that breaks a rule is not applied at all;
    the reason is returned for the host to show and logged by the caller once
    logging is configured.
    """
    path = path or LOCAL_FILE
    try:
        values = read(path)
    except (SettingsError, OSError, UnicodeDecodeError) as exc:
        return "Local settings file not used: %s." % exc
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return ""
