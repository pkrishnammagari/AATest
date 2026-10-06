"""Core42 provider for the AI Analysis -- PLACEHOLDER until Core42 is onboarded.

UAT and production route the analysis here (AECB_ENV=uat|prod, providers.py).
The connector is not built yet: Core42's endpoint, authentication scheme,
model id and structured-output support are not confirmed, and the network
route out of the air-gapped server does not exist. Until they are, probe()
says so and chat() refuses, so no deployment can attempt a call. The page
shows the AI panel as "coming soon" by default (aecb/runtime.py) and does not
load this package at all in that state.

The target model is gpt-oss-120b, the model the development provider
defaults to (ollama.py); Core42's exact model id is pinned here at
onboarding.

The contract the real connector must meet (docs/AI_ANALYSIS_MRM.md, Core42
onboarding checklist):

  * the same interface as ollama.py: NAME, DATA_NOTE, model() -> str (the
    pinned MODEL), probe() -> str ('' when ready, otherwise a short reason)
    and chat(system, user, schema, effort) -> dict, raising BriefUnavailable;
  * `effort` (the pass's reasoning level: "low", "medium" or "high") mapped
    to the API's reasoning control -- for OpenAI-compatible serving of
    gpt-oss, `reasoning_effort`. If Core42 does not expose one, every pass
    runs at the server default and the token budget no longer holds;
  * structured output through `response_format` with a `json_schema`, the
    schema passed unchanged. The pass schemas rely on `type`, `properties`,
    `required`, `items`, `enum`, `pattern`, `minItems`, `maxItems`, integer
    `minimum`/`maximum`, and optional properties with no
    `additionalProperties` (the hypotheses schema has seven optional
    parameters; findings carry an optional `suggested_action`, risk
    findings an optional `inferred_sector`). Strict-mode implementations
    reject some of these: confirm each, never loosen a schema silently;
  * the model's reasoning, if returned, is read from its own field and
    never parsed as the answer (it is probably billed as output tokens);
  * the gpt-oss Harmony chat format is applied by Core42's server: this
    connector sends plain system and user messages and never formats
    Harmony itself;
  * HTTPS only, certificates verified (a CA bundle if the estate re-signs
    TLS), redirects refused, a response-size cap and a timeout;
  * ENDPOINT and MODEL pinned in this file -- where bureau-derived data goes
    is a reviewed code change, never an operator edit (the same reason
    ollama.py pins its URL);
  * the API key read from the environment only (ENV_API_KEY), never from a
    file in the application tree and never logged;
  * a proxy only if one is configured explicitly for this connector;
  * the hosting region, data residency and retention confirmed before the
    first call, and stated in DATA_NOTE;
  * it receives the fact digest the pipeline builds, never raw payload JSON
    or the subject id (enforced upstream in aecb/brief/__init__.py).
"""

from __future__ import annotations

from .errors import BriefUnavailable

NAME = "core42"

# Pinned at onboarding. Empty until then.
ENDPOINT = ""
MODEL = ""

# The environment variable the onboarded connector reads its API key from.
ENV_API_KEY = "AECB_CORE42_API_KEY"

# Where the digest goes, in words the user sees. Written at onboarding, once
# residency and retention terms are agreed.
DATA_NOTE = ""

_NOT_ONBOARDED = "the Core42 connector is not onboarded yet"


def model() -> str:
    """The pinned model id ('' until onboarding)."""
    return MODEL


def probe() -> str:
    """Always the not-onboarded reason until the connector is built."""
    return _NOT_ONBOARDED


def chat(system: str, user: str, schema: dict, effort: str = "") -> dict:  # NOSONAR
    """Refuses: there is no connector to call yet. The parameters are the
    provider interface (see ollama.chat; `effort` is the pass's reasoning
    level, to be mapped to Core42's own control at onboarding) and stay
    unused until then."""
    raise BriefUnavailable(_NOT_ONBOARDED)
