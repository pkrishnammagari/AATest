"""Bureau-report API client -- the live source app_api.py renders from.

urllib only, like aecb/brief/client.py: the deployment is air-gapped from the
internet and requirements.txt is deliberately one line long. The endpoint is
an internal host configured in config/api.json -- the single source of the
URL, no overrides; the response body is the AECB payload document
itself, which flows into context.from_bytes() -- the seam this integration
was always going to use.

Nothing here touches disk: the payload lives only in the caller's session
memory, the same guarantee the uploader gives.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(_HERE), "config", "api.json")

# How much of an HTTP error body to quote back. Enough to carry an API error
# message, not enough to dump a stack trace into the sidebar.
_BODY_SNIPPET = 300


class ApiError(Exception):
    """The API could not produce a payload. The message is user-safe -- it
    names what failed and where, never a traceback or a payload fragment."""


def load_config() -> dict:
    """config/api.json -- the single source of the endpoint, no overrides.

    The URL is the one from the integration Postman collection; changing
    environments means editing the config file, nothing else. Raises ApiError
    with a plain message when the file is missing or malformed -- an API
    entry that silently pointed nowhere would read as "subject not found"
    and mislead.
    """
    if not os.path.exists(CONFIG_PATH):
        raise ApiError("config/api.json is missing -- the API entry cannot "
                       "run without an endpoint. See the file's _comment for "
                       "what it must carry.")
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except ValueError as exc:
        raise ApiError("config/api.json is not valid JSON: %s" % exc)
    if not cfg.get("base_url"):
        raise ApiError("config/api.json carries no base_url.")
    return cfg


def fetch_report(subject_id: str, cfg: dict = None) -> bytes:
    """POST the subject id, return the response body -- the payload bytes.

    The request mirrors the integration Postman collection exactly:
    {"cbSubjectId": "<id>"} with a JSON content type. Validation of what
    comes back is the caller's job (context.from_bytes plus the same
    is-this-an-AECB-payload test the uploader applies) -- this function only
    moves bytes and turns transport failures into readable ApiErrors.
    """
    if cfg is None:
        cfg = load_config()
    url = cfg["base_url"]
    timeout = cfg.get("timeout_seconds") or 30

    request = urllib.request.Request(
        url,
        data=json.dumps({"cbSubjectId": str(subject_id).strip()}).encode("utf-8"),
        headers={"Content-Type": "application/json", "accept": "*/*"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(_BODY_SNIPPET).decode("utf-8", "replace").strip()
        except Exception:
            body = ""
        detail = (" -- %s" % body) if body else ""
        raise ApiError("The bureau-report API answered HTTP %d for subject "
                       "%r%s" % (exc.code, subject_id, detail))
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ApiError("The bureau-report API is not reachable at %s (%s). "
                       "Check config/api.json and the network." % (url, reason))
