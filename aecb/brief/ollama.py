"""Thin Ollama client for the AI Analysis -- urllib only, loopback only.

The development provider: AECB_ENV=dev routes the analysis here (see
providers.py); UAT and production route to core42.py instead.

urllib.request rather than a pip dependency: the deployment is air-gapped and
requirements.txt is deliberately one line long. The base URL is pinned to the
loopback address and is NOT read from config or environment -- a bureau
payload digest must not be routable off this machine by misconfiguration. For
the same reason the opener ignores proxy environment variables (urllib would
otherwise send even a localhost request to an http_proxy) and refuses
redirects.

The /api/chat endpoint, not /api/generate: gpt-oss returns an EMPTY response
when a JSON format schema is passed to /api/generate, while /api/chat honours
the schema (verified on gpt-oss:20b). Do not "simplify" this to generate.

The model is chosen from a closed list (MODELS) and read when used, not at
import: a developer machine's settings file is loaded after this package
may already be imported (aecb/settings.py).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .errors import BriefUnavailable

NAME = "ollama"
OLLAMA_URL = "http://127.0.0.1:11434"

# The models this client may serve -- a closed list, so every model a
# developer can select has been reviewed (docs/AI_ANALYSIS_MRM.md section 7);
# adding one is a model change. The first is the target and the default:
# gpt-oss-120b, the model UAT and production will reach through Core42.
# gpt-oss:20b is for a machine that cannot hold 120b's ~65 GB of weights
# (a 24 GB development Mac); the development evidence was measured on it.
MODELS = ("gpt-oss:120b", "gpt-oss:20b")

# The developer-machine setting that picks one of MODELS
# (~/etc/aecb-analyzer/aecb.env; servers run no Ollama). Only the model is
# read from the environment, never the endpoint.
ENV_MODEL = "AECB_OLLAMA_MODEL"

# What the user is told about where the digest goes. True only because the
# URL above is pinned to loopback.
DATA_NOTE = "Runs on this machine; nothing leaves it."

# Per model, the longest a single request may take before the service is
# assumed wedged. A timeout is not retried (_post raises), and a request
# abandoned on timeout keeps running server-side and delays the next one.
#   gpt-oss:20b   300: at a reply budget of 8192 the findings pass over the
#                 archive fixture has run past 180 s; ~40 tok/s on a 24 GB
#                 M4 Pro.
#   gpt-oss:120b  600, an ESTIMATE (MRM section 9): the worst legitimate call
#                 on a laptop that holds the model on its GPU -- loading
#                 ~65 GB on the first call (20-60 s), a 6.5k-token prompt and
#                 a reply at the 8192 cap at ~25 tok/s (a 96 GB Max-class
#                 laptop) -- is about 450-500 s.
TIMEOUT_S = {"gpt-oss:120b": 600, "gpt-oss:20b": 300}

# Greedy decoding (temperature 0) with a pinned seed. This does NOT make
# output bit-identical across calls -- GPU kernels are not float-stable, and
# scripts/eval_brief.py measured same-substance/different-phrasing re-runs --
# but it removes sampling as a variance source, and the one-brief-per-payload
# guarantee the underwriter actually needs comes from the app's session cache.
# The evaluation harness asserts substantive stability, not string equality.
#
# num_predict and num_ctx are sized to the measured prompts. gpt-oss reasons
# before it answers, and when the reasoning tokens use the whole reply budget
# the reply comes back EMPTY (smaller budgets did, three times in a row) or
# truncated mid-JSON. num_predict 8192 leaves the answer room after the
# reasoning. num_ctx 24576 holds the largest prompt (the findings pass, ~6.5k
# tokens by Ollama's own count -- tables of raw numbers tokenise at about
# 1.6x the chars/4 estimate) plus the 8192 reply, with headroom for larger
# books.
#
# The reasoning level is not here: it is per pass (prompts EFFORT) and goes
# in the request's top-level "think" field, which Ollama 0.34.2 accepts for
# gpt-oss as "low" | "medium" | "high" (no field = the model default,
# "medium").
#
# The same options serve both models: the prompts are the same tokens (one
# tokenizer and chat template for the family), the reply cap does not depend
# on the model, and 120b's KV cache at 24576 is ~1-2 GB, small beside its
# weights (MRM section 9).
_OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 24576,
            "num_predict": 8192}

# Ollama's own token counts for the last successful chat call: prompt tokens,
# reply tokens (reasoning included) and the attempts it took (more than one
# = an empty or unparseable reply was retried). Read by the evaluation
# harness so the sizes it records are measured, not estimated; never used by
# the app.
LAST_USAGE = {"prompt_tokens": None, "reply_tokens": None, "attempts": None}

# Identical calls made before an empty or unparseable reply is given up on.
_ATTEMPTS = 3


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code,
                                     "redirects are refused", headers, fp)


# No ProxyHandler entries: proxy environment variables are ignored.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                      _NoRedirect())

# A chat reply is a few KB of JSON. Anything far larger is not one.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _read_json(response):
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("response larger than %d bytes" % _MAX_RESPONSE_BYTES)
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def _post(path: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        OLLAMA_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return _read_json(response)
    # OSError covers urllib.error.URLError and HTTPError (its subclasses).
    except (OSError, ValueError) as exc:
        raise BriefUnavailable("Ollama request failed: %s" % exc) from exc


def model() -> str:
    """The model tag this process serves: AECB_OLLAMA_MODEL when it names
    one of MODELS (case and surrounding spaces ignored), MODELS[0] when it
    is unset or blank, '' when it names anything else.

    '' never falls back to another model: probe() reports the setting and
    chat() refuses, so a mistyped value leaves the analysis unavailable
    rather than running a model nobody chose (as aecb/runtime.py does for
    an invalid environment).
    """
    value = (os.environ.get(ENV_MODEL) or "").strip().lower()
    if not value:
        return MODELS[0]
    return value if value in MODELS else ""


_NOT_REVIEWED = "%s is not one of the reviewed models (%s)" % (
    ENV_MODEL, ", ".join(MODELS))


def _pulled(tag: str, names) -> bool:
    return any(n == tag or n.startswith(tag + ":") for n in names)


def probe() -> str:
    """'' when the model is ready to serve; otherwise a short reason.

    A GET of /api/tags answers both questions at once -- is the service up,
    and is the model pulled. Kept fast (2s) because the sidebar calls it on
    every rerun; on a deployment with no Ollama it fails on connection
    refused in milliseconds. An unrecognised AECB_OLLAMA_MODEL is reported
    before any request, without echoing the value.
    """
    tag = model()
    if not tag:
        return _NOT_REVIEWED
    try:
        with _OPENER.open(OLLAMA_URL + "/api/tags", timeout=2) as response:
            tags = _read_json(response)
    except (OSError, ValueError):
        return "model service not reachable on this deployment"
    names = {m.get("name", "") for m in tags.get("models") or []}
    if not _pulled(tag, names):
        others = [m for m in MODELS if m != tag and _pulled(m, names)]
        hint = ("; %s=%s selects the one that is" % (ENV_MODEL, others[0])
                if others else "")
        return "model %s is not pulled on this machine%s" % (tag, hint)
    return ""


def chat(system: str, user: str, schema: dict, effort: str = "") -> dict:
    """One schema-constrained chat turn; the parsed JSON the model emitted.

    `effort` is the pass's reasoning level ("low", "medium", "high"; each
    prompt module declares its EFFORT), sent as gpt-oss's "think" level.
    Without it Ollama applies the model's default, which is "medium".

    Retries on empty/unparseable content -- constrained decoding has
    produced an empty message on gpt-oss:20b, and reproduced it on an
    identical re-request, so each retry moves the seed by one. Kept for 120b
    until its evaluation shows otherwise (MRM section 9).
    Anything after _ATTEMPTS is the service's problem, reported as
    BriefUnavailable.
    """
    tag = model()
    if not tag:
        raise BriefUnavailable(_NOT_REVIEWED)
    payload = {
        "model": tag,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": dict(_OPTIONS),
        "format": schema,
    }
    if effort:
        payload["think"] = effort
    last_error = "empty response"
    for attempt in range(_ATTEMPTS):
        # An empty reply has reproduced on an identical re-request (the
        # cached prompt takes the same path), so a retry moves the seed by
        # one: the first attempt is the pinned decode, a retry is a decode
        # that was not possible at all.
        payload["options"]["seed"] = _OPTIONS["seed"] + attempt
        data = _post("/api/chat", payload, TIMEOUT_S[tag])
        message = data.get("message")
        content = (message.get("content") if isinstance(message, dict)
                   else None) or ""
        if content.strip():
            try:
                parsed = json.loads(content)
            except ValueError as exc:
                last_error = "unparseable model output: %s" % exc
                continue
            LAST_USAGE["prompt_tokens"] = data.get("prompt_eval_count")
            LAST_USAGE["reply_tokens"] = data.get("eval_count")
            LAST_USAGE["attempts"] = attempt + 1
            return parsed
        else:
            last_error = "model returned empty content"
    raise BriefUnavailable(last_error)
