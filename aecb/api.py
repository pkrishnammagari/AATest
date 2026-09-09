"""Bureau-report API client -- the live source app_api.py renders from.

Stdlib only, like aecb/brief/client.py: the deployment is air-gapped from the
internet and requirements.txt is deliberately one line long. The endpoint is
an internal host configured in config/api.json -- the single source of the
URL, no overrides; the response body is the AECB payload document itself,
which flows into context.from_bytes() -- the seam this integration was always
going to use.

The endpoint sits behind IIS Windows authentication (confirmed by the API
team, 9 Sep 2026), so requests authenticate as the configured service account
via NTLMv2 (aecb/ntlm.py -- implemented from MS-NLMP, spec-vector tested).
NTLM authenticates the TCP CONNECTION, not the request: both legs of the
handshake must travel on one socket, which is why this module speaks
http.client directly instead of urllib -- urllib does not guarantee
connection reuse.

Nothing here touches disk: the payload lives only in the caller's session
memory, the same guarantee the uploader gives. Error responses are logged in
full (status, headers, body) to the "aecb.api" logger -- app_api.py routes
that to aecb_api.log; successful payloads are never logged.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
from urllib.parse import urlsplit

from . import ntlm

_LOG = logging.getLogger("aecb.api")

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(_HERE), "config", "api.json")

# How much of an HTTP error body to quote back ON SCREEN. Enough to carry an
# API error message, not enough to dump a stack trace into the sidebar. The
# log gets the full picture (up to _LOG_BODY) -- diagnosis must never depend
# on what fits in an st.error box.
_BODY_SNIPPET = 300
_LOG_BODY = 16000

# An NTLM token, base64-encoded, always opens with this ("NTLMSSP\0").
_NTLM_B64_PREFIX = "TlRMTVNTUA"


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
    {"cbSubjectId": "<id>"} with a JSON content type, authenticated as the
    configured service account over NTLMv2. Validation of what comes back is
    the caller's job (context.from_bytes plus the same is-this-an-AECB-payload
    test the uploader applies) -- this module only moves bytes and turns
    transport failures into readable ApiErrors.
    """
    if cfg is None:
        cfg = load_config()
    auth = cfg.get("auth") or {}
    if not auth.get("username"):
        raise ApiError("config/api.json carries no auth.username -- the "
                       "bureau-report API requires the service account "
                       "(IIS Windows authentication).")

    url = cfg["base_url"]
    timeout = cfg.get("timeout_seconds") or 30
    body = json.dumps({"cbSubjectId": str(subject_id).strip()}).encode("utf-8")
    user, domain = ntlm.split_account(str(auth["username"]))
    password = str(auth.get("password") or "")

    parts = urlsplit(url)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    conn_cls = (http.client.HTTPSConnection if parts.scheme == "https"
                else http.client.HTTPConnection)
    base_headers = {"Content-Type": "application/json", "accept": "*/*",
                    "Connection": "keep-alive"}

    conn = conn_cls(parts.hostname, parts.port, timeout=timeout)
    try:
        # Leg 1: announce NTLM. A 401 with a challenge is the EXPECTED answer;
        # a 200 means the server did not require auth after all.
        headers = dict(base_headers)
        headers["Authorization"] = ntlm.negotiate_header()
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        if response.status == 200:
            return payload
        if response.status != 401:
            _raise_http(subject_id, url, response, payload)

        challenge = _challenge_from(response)
        if challenge is None:
            _raise_http(
                subject_id, url, response, payload,
                extra="The server answered the NTLM negotiation without a "
                      "challenge -- it may not accept the NTLM scheme.")
        if "close" in (response.getheader("Connection") or "").lower():
            raise ApiError("The server closed the connection mid-NTLM "
                           "handshake; NTLM authenticates the connection and "
                           "needs keep-alive. Raise with the API team.")

        # Leg 2: answer the challenge on the SAME connection.
        headers = dict(base_headers)
        headers["Authorization"] = ntlm.authenticate_header(
            user, domain, password, challenge)
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        if response.status == 200:
            return payload
        extra = None
        if response.status == 401:
            extra = ("The service-account credentials were rejected -- "
                     "check auth.username / auth.password in config/api.json "
                     "(username may need the DOMAIN\\account form).")
        _raise_http(subject_id, url, response, payload, extra=extra)
    except ApiError:
        raise
    except (http.client.HTTPException, OSError) as exc:
        raise ApiError("The bureau-report API is not reachable at %s (%s). "
                       "Check config/api.json and the network." % (url, exc))
    finally:
        conn.close()


def _challenge_from(response):
    """The base64 NTLM CHALLENGE from a 401's WWW-Authenticate header(s).

    IIS may answer under the NTLM scheme or wrap the same token under
    Negotiate; an NTLM token is recognisable by its NTLMSSP signature either
    way. Bare scheme names (no token) are the initial advertisement, not a
    challenge.
    """
    for value in response.headers.get_all("WWW-Authenticate") or []:
        parts = value.strip().split(None, 1)
        if len(parts) != 2:
            continue
        scheme, token = parts[0].upper(), parts[1].strip()
        if scheme in ("NTLM", "NEGOTIATE") and token.startswith(_NTLM_B64_PREFIX):
            return token
    return None


def _raise_http(subject_id, url, response, payload, extra=None):
    """Log the full error response, raise the concise on-screen ApiError."""
    raw_body = payload[:_LOG_BODY].decode("utf-8", "replace")
    # The FULL response goes to the log: every header (WWW-Authenticate
    # included) and the untruncated body. Error bodies carry no bureau data --
    # successful payloads are never logged.
    _LOG.warning(
        "Bureau API HTTP %d for subject %r\nURL: %s\n"
        "--- response headers ---\n%s"
        "--- response body (first %d chars) ---\n%s\n"
        "--- end of response ---",
        response.status, subject_id, url, response.headers, _LOG_BODY, raw_body)

    # IIS error bodies are HTML; strip the markup so the human-readable
    # sentence survives on screen instead of a snippet of doctype.
    body = re.sub(r"<[^>]+>", " ", raw_body)
    body = re.sub(r"\s+", " ", body).strip()[:_BODY_SNIPPET]
    detail = (" -- %s" % body) if body else ""
    if extra:
        detail += " [%s]" % extra
    elif response.status == 401:
        scheme = response.getheader("WWW-Authenticate")
        detail += (" [server expects authentication: %s]" % scheme
                   if scheme else
                   " [the response names no WWW-Authenticate scheme]")
    raise ApiError("The bureau-report API answered HTTP %d for subject "
                   "%r%s" % (response.status, subject_id, detail))
