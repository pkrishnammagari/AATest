"""Which model provider serves the AI Analysis in each environment.

    dev        ollama.py   local open-source model on loopback
    uat, prod  core42.py   Core42 via its API (placeholder until onboarded)

A provider is a module with NAME, DATA_NOTE, model() (the model tag it
serves, read when called), probe() and chat(system, user, schema, effort).
The map holds the modules themselves, so tests can patch a provider's
functions and the router follows. Changing this map changes where
bureau-derived data is sent: a model change under docs/AI_ANALYSIS_MRM.md.
"""

from __future__ import annotations

from .. import runtime
from . import core42, ollama

BY_ENVIRONMENT = {
    runtime.DEV: ollama,
    runtime.UAT: core42,
    runtime.PROD: core42,
}


def for_environment(env: str):
    """The provider module for an environment. Raises ValueError."""
    try:
        return BY_ENVIRONMENT[env]
    except KeyError:
        raise ValueError("no AI brief provider for environment %r"
                         % (env,)) from None
