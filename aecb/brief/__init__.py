"""The AI Analysis -- an LLM's reading of the bureau payload in four blocks.

    new_analysis(ctx, provider)                 facts, packets, provenance; every block pending
    generate_block(ctx, provider, analysis, name)   one block: model pass(es) + validation
    next_missing(analysis)                      which block the host should build next

Blocks (aecb/brief/blocks/, in page order): lens (fresh reading as a
hypothesis -> verification loop), risk (non-obvious risk), checklist (the
team's ten steps), memo (credit memo and suggested outcome). Each is generated separately so the host
can show finished blocks while the next one runs, and each is validated before
it is stored: the model never touches HTML and the renderer never touches the
model. Provenance (provider, model tag, prompt version, generation time, a
generation id) travels with the analysis because output that cannot say what
produced it cannot be filed.

The provider is chosen by environment (providers.py): the local Ollama model
in dev, Core42 in UAT and production. Callers pass it explicitly -- nothing
here reads the environment. Whatever the provider, it receives the fact
digest and the step packets, never raw payload JSON or the subject id.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re

from ..coerce import flag
from ..derive import brief_facts
from ..derive.brief_facts import steps as steps_mod
from ..render.analysis import BLOCKS, TITLES  # noqa: F401 -- page order, owned by the renderer
from . import blocks
from .errors import BriefUnavailable  # noqa: F401 -- the package API
from .prompts import PROMPT_VERSION  # noqa: F401
from .providers import for_environment  # noqa: F401

# A block that reads another block's validated output cannot run before it.
_REQUIRES = {"memo": ("checklist",)}


def payload_hash(ctx) -> str:
    """Stable digest of the normalised payload -- the analysis's cache identity.

    Canonical JSON of ctx.data, so byte-identical payloads share an analysis
    and any edit invalidates it. default=str covers nothing today (the loader
    keeps values as JSON scalars) but keeps an exotic payload from crashing
    the hasher instead of the renderer.
    """
    canonical = json.dumps(ctx.data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_key(ctx, provider) -> str:
    """One analysis per (payload, provider, model, prompt version) -- change
    any of them and the cached analysis no longer describes what would be
    generated."""
    return "%s:%s:%s:%s" % (payload_hash(ctx), provider.NAME, provider.model(),
                            PROMPT_VERSION)


def _generation_id(hash_: str, provider, started: datetime.datetime) -> str:
    """Distinguishes two generations of the same cache key (a regeneration):
    audit and feedback lines carry it, the cache key stays deterministic."""
    seed = "%s|%s|%s|%s|%s" % (hash_, provider.NAME, provider.model(),
                               PROMPT_VERSION, started.isoformat())
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _prohibited_content(ctx, facts, *messages) -> str:
    """'' when the digest and every message honour PROHIBITED_FIELDS;
    otherwise what leaked.

    Checked at runtime on every analysis, not only in tests: no prohibited
    field may be cited, named, or have its delivered value (when it is more
    than a one-letter code) appear in any text the model receives.
    """
    for fact in facts:
        for banned in brief_facts.PROHIBITED_FIELDS:
            if any(banned in field for field in fact["fields"]):
                return "fact %s cites %s" % (fact["id"], banned)
    for message in messages:
        leaked = _prohibited_text(ctx, message)
        if leaked:
            return leaked
    return ""


def _prohibited_text(ctx, message: str) -> str:
    lowered = message.lower()
    for banned in brief_facts.PROHIBITED_FIELDS:
        if re.search(r"\b%s\b" % banned.lower(), lowered):
            return "the prompt names %s" % banned
        raw = ctx.customer.get(banned)
        value = str(raw or "").strip().lower()
        # A yes/no flag's text ('true', 'Y') identifies nothing by itself and
        # occurs in ordinary prose ("the true exposure"); only a value that
        # carries the attribute -- a nationality, a gender word -- is grepped.
        if flag(raw) is not None or len(value) < 2:
            continue
        if re.search(r"\b%s\b" % re.escape(value), lowered):
            return "the prompt carries the delivered %s value" % banned
    return ""


def new_analysis(ctx, provider) -> dict:
    """The analysis shell: facts and provenance, every block pending.

    Raises BriefUnavailable for every failure -- nothing to analyse, a
    prohibited-field breach (no model pass can ever run on it), or a payload
    or optional-config problem inside the digest -- so the caller has one
    exception to degrade on. The original error is chained for the log.
    """
    try:
        return _new_analysis(ctx, provider)
    except BriefUnavailable:
        raise
    except Exception as exc:  # any failure is converted; the caller logs it
        raise BriefUnavailable("analysis could not start: %s: %s"
                               % (type(exc).__name__, exc)) from exc


def _new_analysis(ctx, provider) -> dict:
    facts = brief_facts.build(ctx)
    if not facts:
        # An empty digest means an empty payload; there is nothing to read.
        raise BriefUnavailable("the payload yielded no facts to analyse")
    packets, facts = steps_mod.build_packets(ctx, facts)
    facts_by_id = brief_facts.by_id(facts)
    leaked = _prohibited_content(ctx, facts, brief_facts.digest(facts),
                                 steps_mod.packets_text(packets, facts_by_id))
    if leaked:
        raise BriefUnavailable("prohibited-field policy breached (%s); no "
                               "analysis generated" % leaked)
    started = datetime.datetime.now()
    hash_ = payload_hash(ctx)

    def check_prohibited(message: str) -> None:
        """Blocks call this on the exact user turn they are about to send."""
        found = _prohibited_content(ctx, facts, message)
        if found:
            raise BriefUnavailable("prohibited-field policy breached (%s); "
                                   "block not generated" % found)

    return {
        "generation_id": _generation_id(hash_, provider, started),
        "payload_hash": hash_[:12],
        "provider": provider.NAME,
        "model": provider.model(),
        "prompt_version": PROMPT_VERSION,
        "started_at": started.strftime("%d %b %Y %H:%M"),
        "facts": facts,
        "facts_by_id": facts_by_id,
        "packets": packets,
        "check_prohibited": check_prohibited,
        "blocks": {name: {"status": "pending", "error": ""} for name in BLOCKS},
    }


def _buildable(analysis, name) -> bool:
    if name not in blocks.MODULES:
        return False
    if analysis["blocks"][name]["status"] != "pending":
        return False
    return all(analysis["blocks"][req]["status"] == "ok"
               for req in _REQUIRES.get(name, ()))


def next_missing(analysis) -> "str | None":
    """The first block, in page order, that can be generated now."""
    for name in BLOCKS:
        if _buildable(analysis, name):
            return name
    return None


def generate_block(ctx, provider, analysis, name: str) -> dict:
    """Generate one block into analysis["blocks"][name]; return it.

    Raises BriefUnavailable for every failure -- the model service, but also
    a payload or optional-config problem -- so the caller has one exception
    to degrade on and no traceback reaches the browser. The block stays
    pending with the error recorded, so the next attempt retries it.
    """
    if not _buildable(analysis, name):
        raise BriefUnavailable("block %r cannot be generated now" % (name,))
    started = datetime.datetime.now()
    try:
        block = dict(blocks.MODULES[name].generate(ctx, analysis, provider))
        _absorb_facts(analysis, block.pop("new_facts", []))
    except BriefUnavailable as exc:
        analysis["blocks"][name]["error"] = str(exc)
        raise BriefUnavailable("block %r: %s" % (name, exc)) from exc
    except Exception as exc:  # any failure is converted; the caller logs it
        analysis["blocks"][name]["error"] = "%s: %s" % (type(exc).__name__, exc)
        raise BriefUnavailable("block %r failed: %s: %s"
                               % (name, type(exc).__name__, exc)) from exc
    block.update({
        "status": "ok",
        "error": "",
        "generated_at": datetime.datetime.now().strftime("%d %b %Y %H:%M"),
        "elapsed_s": round((datetime.datetime.now() - started).total_seconds()),
    })
    analysis["blocks"][name] = block
    return block


def _absorb_facts(analysis, new_facts) -> None:
    """Facts a block derived (the lens's verified hypotheses) join the
    analysis, so cite chips, later blocks and the harness resolve them by
    id. Ids must continue the digest's sequence; a clash is a defect."""
    for fact in new_facts:
        if fact["id"] in analysis["facts_by_id"]:
            raise BriefUnavailable("fact id %s already exists" % fact["id"])
        analysis["facts"].append(fact)
        analysis["facts_by_id"][fact["id"]] = fact


def describe(analysis) -> str:
    """One line on the analysis so far, for the host's sidebar."""
    parts = []
    for name in BLOCKS:
        block = analysis["blocks"][name]
        if block["status"] == "ok":
            parts.append("%s ok (%s)" % (name, blocks.MODULES[name].summary(block)))
        else:
            parts.append("%s pending" % name)
    return " · ".join(parts)


def finished(analysis) -> bool:
    """True once every buildable block is ok (nothing left to generate)."""
    return next_missing(analysis) is None
