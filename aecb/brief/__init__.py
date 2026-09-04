"""The AI underwriting brief -- an LLM's second-lens reading of the payload.

generate_brief(ctx) is the whole pipeline:

    derive/brief_facts.build(ctx)      deterministic fact digest
        -> client.chat(...)            one schema-constrained local-model pass
        -> validate.validate(...)      citation + verbatim-figure guards

The result is a plain dict the render layer draws from; the model never
touches HTML and the renderer never touches the model. Provenance (model tag,
prompt version, generation time) travels with the findings because a brief
that cannot say what produced it cannot be filed.

The model call goes to Ollama on localhost only (see client.py) and receives
the fact digest, never raw payload JSON.
"""

from __future__ import annotations

import datetime
import hashlib
import json

from ..derive import brief_facts
from . import client, prompt, validate
from .client import MODEL, BriefUnavailable  # noqa: F401 -- the package API
from .prompt import PROMPT_VERSION  # noqa: F401


def payload_hash(ctx) -> str:
    """Stable digest of the normalised payload -- the brief's cache identity.

    Canonical JSON of ctx.data, so byte-identical payloads share a brief and
    any edit invalidates it. default=str covers nothing today (the loader
    keeps values as JSON scalars) but keeps an exotic payload from crashing
    the hasher instead of the renderer.
    """
    canonical = json.dumps(ctx.data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_key(ctx) -> str:
    """One brief per (payload, model, prompt version) -- change any of the
    three and the cached brief no longer describes what would be generated."""
    return "%s:%s:%s" % (payload_hash(ctx), client.MODEL, prompt.PROMPT_VERSION)


def probe() -> str:
    """'' when the model can serve; otherwise a short reason for the sidebar."""
    return client.probe()


def _synthesis(findings) -> str:
    """The two-sentence lead, or '' -- the brief is complete without it.

    A second model pass over the VALIDATED findings only: it can compress
    what survived the guards but cannot reach the payload, and its output is
    re-validated against the findings' own text. Every failure mode -- the
    service dying between passes, an unvouched figure or name -- degrades to
    an empty string rather than an error, because losing a lead sentence is
    not worth losing the brief.
    """
    if len(findings) < 2:
        return ""
    listed = "\n".join("- [%s] %s" % (f["severity"], f["claim"])
                       for f in findings)
    try:
        raw = client.chat(prompt.SYNTHESIS_SYSTEM,
                          "FINDINGS:\n%s\n\nWrite the synthesis." % listed,
                          prompt.SYNTHESIS_SCHEMA)
    except BriefUnavailable:
        return ""
    return validate.validate_synthesis(raw.get("synthesis"), findings)


def generate_brief(ctx) -> dict:
    """The validated brief for one payload. Raises BriefUnavailable when the
    model service cannot produce one -- the caller decides how to degrade."""
    facts = brief_facts.build(ctx)
    if not facts:
        # An empty digest means an empty payload; there is nothing to read.
        raise BriefUnavailable("the payload yielded no facts to analyse")

    raw = client.chat(
        prompt.SYSTEM,
        prompt.user_message(ctx, brief_facts.digest(facts)),
        prompt.FINDINGS_SCHEMA,
    )
    findings, background, unknowns, dropped = validate.validate(raw, facts)

    return {
        "findings": findings,
        "background": background,
        "unknowns": unknowns,
        "synthesis": _synthesis(findings),
        "dropped": dropped,
        "fact_count": len(facts),
        "facts_by_id": brief_facts.by_id(facts),
        "model": client.MODEL,
        "prompt_version": prompt.PROMPT_VERSION,
        "generated_at": datetime.datetime.now().strftime("%d %b %Y %H:%M"),
        "payload_hash": payload_hash(ctx)[:12],
    }
