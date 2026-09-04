"""Thin Ollama client for the brief -- urllib only, localhost only.

urllib.request rather than a pip dependency: the deployment is air-gapped and
requirements.txt is deliberately one line long. The base URL is pinned to
localhost and is NOT read from config or environment -- a bureau payload digest
must not be routable off this machine by misconfiguration.

The /api/chat endpoint, not /api/generate: gpt-oss:20b returns an EMPTY
response when a JSON format schema is passed to /api/generate (verified against
Ollama 0.33.2 on 2026-09-03), while /api/chat honours the schema. Do not
"simplify" this back to generate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434"
MODEL = "gpt-oss:20b"

# First call pays model load (~7s) plus reasoning tokens at ~40 tok/s on the
# reference machine; a long fact table can legitimately take a couple of
# minutes to reason over. Beyond this, assume the service is wedged.
TIMEOUT_S = 180

# Greedy decoding (temperature 0) with a pinned seed. This does NOT make
# output bit-identical across calls -- GPU kernels are not float-stable, and
# scripts/eval_brief.py measured same-substance/different-phrasing re-runs --
# but it removes sampling as a variance source, and the one-brief-per-payload
# guarantee the underwriter actually needs comes from the app's session cache.
# The evaluation harness asserts substantive stability, not string equality.
#
# num_ctx 16384, not the 8192 it started at: a full five-lens digest plus the
# system prompt plus this model's reasoning tokens overran 8k and the reply
# was truncated mid-JSON ("Unterminated string"). num_predict caps the visible
# reply well below the window so reasoning can never squeeze the answer out.
_OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 16384,
            "num_predict": 4096}


class BriefUnavailable(Exception):
    """The model service could not produce a brief. The reason is for the
    server log and the sidebar -- the rail itself falls back to its empty
    state rather than carrying an error about infrastructure."""


def _post(path: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        OLLAMA_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise BriefUnavailable("Ollama request failed: %s" % exc)


def probe() -> str:
    """'' when the model is ready to serve; otherwise a short reason.

    A GET of /api/tags answers both questions at once -- is the service up,
    and is the model pulled. Kept fast (2s) because the sidebar calls it on
    every rerun; on a deployment with no Ollama it fails on connection
    refused in milliseconds.
    """
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=2) as r:
            tags = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return "model service not reachable on this deployment"
    names = {m.get("name", "") for m in tags.get("models") or []}
    if not any(n == MODEL or n.startswith(MODEL + ":") for n in names):
        return "model %s is not pulled on this machine" % MODEL
    return ""


def chat(system: str, user: str, schema: dict) -> dict:
    """One schema-constrained chat turn; the parsed JSON the model emitted.

    Retries once on empty/unparseable content -- constrained decoding has
    produced an empty message on this model before, and a second identical
    call is cheap next to giving up. Anything after that is the service's
    problem, reported as BriefUnavailable.
    """
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": dict(_OPTIONS),
        "format": schema,
    }
    last_error = "empty response"
    for _ in range(2):
        data = _post("/api/chat", payload, TIMEOUT_S)
        content = (data.get("message") or {}).get("content") or ""
        if content.strip():
            try:
                return json.loads(content)
            except ValueError as exc:
                last_error = "unparseable model output: %s" % exc
        else:
            last_error = "model returned empty content"
    raise BriefUnavailable(last_error)
