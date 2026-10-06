"""Which environment this process serves, and what the AI panel does in it.

Two settings, both read from the process environment (the systemd
EnvironmentFile on a server, ~/etc/aecb-analyzer/aecb.env on a developer
machine -- aecb/settings.py):

    AECB_ENV        dev | uat | prod
                    Picks the model provider for the AI Analysis (dev -> the
                    local Ollama model, uat/prod -> Core42; see
                    aecb/brief/providers.py) and whether app.py offers its
                    development tools. Unset: app.py assumes prod; the AI
                    Analysis scripts, which never run on a server, assume dev.

    AECB_AI_BRIEF   live | coming_soon | off
                    What the AI panel shows. Unset: dev -> live, uat/prod ->
                    coming_soon. Setting live on uat/prod is the deliberate
                    switch-on step and a model change under docs/AI_ANALYSIS_MRM.md
                    -- it never happens because a credential appeared.

Values are case-insensitive and a blank value counts as unset (systemd turns
`AECB_ENV=` into an empty string). Nothing is cached: the environment is read
on every call, so a test that sets a variable sees it immediately.

This module imports nothing from aecb -- app.py reads it before deciding
whether the aecb.brief package is loaded at all.
"""

from __future__ import annotations

import logging
import os

_LOG = logging.getLogger("aecb.runtime")

ENV_ENVIRONMENT = "AECB_ENV"
ENV_AI_BRIEF = "AECB_AI_BRIEF"

DEV, UAT, PROD = "dev", "uat", "prod"
ENVIRONMENTS = (DEV, UAT, PROD)

AI_LIVE, AI_SOON, AI_OFF = "live", "coming_soon", "off"
AI_MODES = (AI_LIVE, AI_SOON, AI_OFF)

# The panel each environment shows when AECB_AI_BRIEF is unset. Governed:
# changing a default here changes what a deployed page offers, which is a
# model change (docs/AI_ANALYSIS_MRM.md, Change control).
_DEFAULT_MODE = {DEV: AI_LIVE, UAT: AI_SOON, PROD: AI_SOON}

# Problems already logged, so a misconfigured server logs each one once per
# process rather than on every Streamlit rerun.
_LOGGED = set()


def _read(name: str, allowed: tuple, default: str) -> str:
    value = (os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    if value not in allowed:
        raise ValueError("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def environment(default: str) -> str:
    """AECB_ENV, or `default` when it is unset. Raises ValueError."""
    if default not in ENVIRONMENTS:
        raise ValueError("unknown default environment %r" % (default,))
    return _read(ENV_ENVIRONMENT, ENVIRONMENTS, default)


def ai_mode(env: str) -> str:
    """AECB_AI_BRIEF, or the environment's default. Raises ValueError."""
    if env not in ENVIRONMENTS:
        raise ValueError("unknown environment %r" % (env,))
    return _read(ENV_AI_BRIEF, AI_MODES, _DEFAULT_MODE[env])


def resolve(default_env: str) -> tuple:
    """(environment, AI mode, problem) for an entry point. Never raises.

    `problem` is '' when both settings read cleanly. Otherwise it is a short,
    user-safe sentence for the sidebar (it never echoes the bad value), the
    detail goes to the log, and the result is the most restrictive state:
    production with the AI panel showing "coming soon". An invalid setting
    can never switch the analysis on.
    """
    try:
        env = environment(default_env)
        return env, ai_mode(env), ""
    except ValueError as exc:
        if str(exc) not in _LOGGED:
            _LOGGED.add(str(exc))
            _LOG.error("Invalid environment setting (%s); running as %s with "
                       "the AI panel %s.", exc, PROD, AI_SOON)
        return (PROD, AI_SOON,
                "An environment setting (%s or %s) is invalid; running in "
                "the restricted mode. Details are in the server log."
                % (ENV_ENVIRONMENT, ENV_AI_BRIEF))
