"""Run the app and tests against the live bureau-report API from a
development machine, with the same settings file the server uses.

On the server, systemd loads /etc/aecb-analyzer/aecb.env into the app's
environment (deploy/aecb-analyzer.service). This helper does the same job on
a development machine. By default the file mirrors the server layout under
your home folder -- outside the repository, so it cannot be committed, and
no administrator rights are needed:

    ~/etc/aecb-analyzer/aecb.env                 the settings, incl. credentials
    ~/var/lib/aecb-analyzer/api_responses/       archived API responses
    ~/var/log/aecb-analyzer/                     rotating aecb.log

Usage (from the repository root):

    python scripts/local_env.py init             # create the file (then edit it)
    python scripts/local_env.py check            # show what it sets (password hidden)
    python scripts/local_env.py run              # start app_api.py with it
    python scripts/local_env.py exec -- python -m pytest -m live_api
    python scripts/local_env.py exec -- python scripts/check_corpus.py

--env-file PATH (or the AECB_ENV_FILE environment variable) points at a
different file, e.g. the real /etc/aecb-analyzer/aecb.env.

File format: KEY=VALUE lines, # comments, an optional leading "export " and
optional surrounding quotes. Values are taken literally -- no escapes, no
variable expansion. A setting already present in the shell environment wins
over the file, so a one-off override needs no edit.

Development tooling only: never deployed (.gitattributes export-ignore).
Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
DEFAULT_ENV_FILE = os.path.join(HOME, "etc", "aecb-analyzer", "aecb.env")

REQUIRED = ("AECB_API_USERNAME", "AECB_API_PASSWORD")
SECRET_KEYS = ("AECB_API_PASSWORD",)

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TEMPLATE = """\
# FH AECB Analyzer -- LOCAL settings for a development machine.
#
# Mirrors the server's /etc/aecb-analyzer/aecb.env (deploy/aecb.env.example),
# rooted at your home folder. Created by scripts/local_env.py init; loaded by
# `python scripts/local_env.py run | exec`. Keep it private (mode 0600) and
# outside the repository -- never commit it or copy it into the project.

# Bureau-report API service account (IIS Windows authentication, NTLMv2).
# Give the account and its Windows domain separately.
AECB_API_USERNAME=
AECB_API_DOMAIN=
AECB_API_PASSWORD=

# Where app_api.py archives each successful response (real bureau data) --
# the local mirror of /var/lib/aecb-analyzer/api_responses. Must be outside
# the repository. scripts/check_corpus.py reads this folder by default.
AECB_ARCHIVE_DIR={archive}

# Rotating aecb.log -- the local mirror of /var/log/aecb-analyzer.
AECB_LOG_DIR={logs}

# Local testing only: the CB subject id tests/test_api_live.py fetches.
AECB_TEST_SUBJECT_ID=
"""


class EnvFileError(Exception):
    """The settings file is missing, unsafe or malformed."""


def default_env_file() -> str:
    return os.environ.get("AECB_ENV_FILE") or DEFAULT_ENV_FILE


def _inside_repo(path: str) -> bool:
    repo = os.path.realpath(REPO)
    target = os.path.realpath(path)
    return os.path.commonpath([repo, target]) == repo


def _check_private(path: str) -> None:
    """Refuse a credentials file other users can read (POSIX only)."""
    if os.name == "nt":
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise EnvFileError("%s is readable by other users (mode %o). Run: "
                           "chmod 600 %s" % (path, mode, path))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(text: str, source: str = "env file") -> dict:
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
            raise EnvFileError("%s line %d is not KEY=VALUE" % (source, number))
        out[key] = _unquote(value.strip())
    return out


def load(path: str) -> dict:
    """The file's settings. Raises EnvFileError when it cannot be used."""
    if not os.path.isfile(path):
        raise EnvFileError("%s does not exist. Create it with: python "
                           "scripts/local_env.py init" % path)
    if _inside_repo(path):
        raise EnvFileError("%s is inside the repository. Keep credentials "
                           "outside it so they cannot be committed." % path)
    _check_private(path)
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read(), source=path)


def merged_environment(settings: dict):
    """(environment for the child process, keys the shell overrode)."""
    env = dict(os.environ)
    overridden = []
    for key, value in settings.items():
        if key in env and env[key] != value:
            overridden.append(key)
            continue
        env[key] = value
    return env, overridden


def _missing(env: dict) -> list:
    return [key for key in REQUIRED if not (env.get(key) or "").strip()]


def cmd_init(path: str) -> int:
    if _inside_repo(path):
        raise EnvFileError("refusing to create %s inside the repository." % path)
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    content = TEMPLATE.format(
        archive=os.path.join(HOME, "var", "lib", "aecb-analyzer", "api_responses"),
        logs=os.path.join(HOME, "var", "log", "aecb-analyzer"))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("%s already exists -- edit it rather than recreating it." % path)
        return 1
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    print("Created %s (mode 0600).\nFill in AECB_API_USERNAME, AECB_API_DOMAIN "
          "and AECB_API_PASSWORD (and AECB_TEST_SUBJECT_ID for the live "
          "tests), then run:\n    python scripts/local_env.py check" % path)
    return 0


def cmd_check(path: str) -> int:
    settings = load(path)
    env, overridden = merged_environment(settings)
    print("Settings from %s:" % path)
    for key in sorted(settings):
        value = env.get(key, "")
        shown = ("(set, hidden)" if value else "(empty)") if key in SECRET_KEYS \
            else (value or "(empty)")
        note = "   <- from the shell environment" if key in overridden else ""
        print("  %-22s %s%s" % (key, shown, note))
    missing = _missing(env)
    if missing:
        print("\nNot ready: fill in %s." % ", ".join(missing))
        return 1
    print("\nReady.")
    return 0


def _run(command, path: str, require: bool) -> int:
    env, overridden = merged_environment(load(path))
    missing = _missing(env)
    if missing and require:
        raise EnvFileError("%s leaves %s empty." % (path, ", ".join(missing)))
    if missing:
        print("note: %s empty in %s" % (", ".join(missing), path),
              file=sys.stderr)
    if overridden:
        print("note: using the shell's %s instead of the file's"
              % ", ".join(overridden), file=sys.stderr)
    return subprocess.run(command, env=env, cwd=REPO, check=False).returncode


def cmd_run(path: str, extra) -> int:
    command = [sys.executable, "-m", "streamlit", "run",
               os.path.join(REPO, "app_api.py")] + list(extra)
    return _run(command, path, require=True)


def cmd_exec(path: str, command) -> int:
    if not command:
        raise EnvFileError("nothing to run: give a command after --")
    return _run(command, path, require=False)


def _args(argv):
    parser = argparse.ArgumentParser(
        description="Load the local settings file and run the app or a "
                    "command with it.")
    parser.add_argument("--env-file", default=default_env_file(),
                        help="settings file (default: %(default)s)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init", help="create the settings file from the template")
    sub.add_parser("check", help="show the settings (password hidden)")
    run = sub.add_parser("run", help="start app_api.py with the settings")
    run.add_argument("extra", nargs=argparse.REMAINDER,
                     help="extra streamlit arguments, after --")
    ex = sub.add_parser("exec", help="run any command with the settings")
    ex.add_argument("command", nargs=argparse.REMAINDER,
                    help="the command, after --")
    return parser.parse_args(argv)


def _strip_dashes(items):
    items = list(items)
    return items[1:] if items and items[0] == "--" else items


def main(argv=None) -> int:
    args = _args(argv)
    path = os.path.abspath(os.path.expanduser(args.env_file))
    try:
        if args.action == "init":
            return cmd_init(path)
        if args.action == "check":
            return cmd_check(path)
        if args.action == "run":
            return cmd_run(path, _strip_dashes(args.extra))
        return cmd_exec(path, _strip_dashes(args.command))
    except EnvFileError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
