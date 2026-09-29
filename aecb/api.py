"""Bureau-report API client -- the live source app_api.py renders from.

Stdlib only: the deployment is air-gapped and requirements.txt is
deliberately one line long. The endpoint is an internal host configured in
config/api.json; the response body is the AECB payload document itself, which
flows into context.from_bytes().

The endpoint sits behind IIS Windows authentication, so requests authenticate
as a service account via NTLMv2 (aecb/ntlm.py, implemented from MS-NLMP and
tested against its published vectors). NTLM authenticates the TCP CONNECTION,
not the request: both legs of the handshake must travel on one socket, which
is why this module speaks http.client directly -- urllib does not guarantee
connection reuse.

Credentials never live in a file in the application tree. They are read from
the environment of the server process:

    AECB_API_USERNAME   the account, as DOMAIN\\account or a bare name
    AECB_API_DOMAIN     optional: the Windows domain, for a bare account name
                        (avoids backslash escaping in service env files)
    AECB_API_PASSWORD   the account's password

Nothing in this module touches disk. Error responses are logged in full
(status, headers, body) to the "aecb.api" logger; on screen the user sees a
short message with no internal addresses, bodies or tracebacks (CWE-209).
Successful payloads are never logged.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
from urllib.parse import urlsplit

from . import ntlm

_LOG = logging.getLogger("aecb.api")

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(_HERE), "config", "api.json")

ENV_USERNAME = "AECB_API_USERNAME"
ENV_DOMAIN = "AECB_API_DOMAIN"
ENV_SECRET = "AECB_API_PASSWORD"

# How much of an error response body the log keeps.
_LOG_BODY = 16000

# An NTLM token, base64-encoded, always opens with this ("NTLMSSP\0").
_NTLM_B64_PREFIX = "TlRMTVNTUA"

_DEFAULT_TIMEOUT_S = 30


class ApiError(Exception):
    """The API could not produce a payload. The message is user-safe -- it
    says what failed, never an internal address, a response body, a
    traceback or a payload fragment. Detail goes to the log."""


def load_config() -> dict:
    """config/api.json -- the endpoint and timeout.

    Raises ApiError when the file is missing or malformed: an API entry that
    silently pointed nowhere would read as "subject not found" and mislead.
    A file that still carries credentials is refused outright -- they belong
    in the environment (see the module docstring), and a password left in a
    file inside the application tree must not keep working unnoticed.
    """
    if not os.path.exists(CONFIG_PATH):
        raise ApiError("config/api.json is missing -- the API entry cannot "
                       "run without an endpoint.")
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except ValueError as exc:
        _LOG.error("config/api.json is not valid JSON: %s", exc)
        raise ApiError("config/api.json is not valid JSON.") from None
    if not isinstance(cfg, dict) or not cfg.get("base_url"):
        raise ApiError("config/api.json carries no base_url.")
    if "auth" in cfg:
        raise ApiError("config/api.json must not carry credentials. Remove "
                       "its \"auth\" block and set %s and %s in the server's "
                       "environment instead." % (ENV_USERNAME, ENV_SECRET))
    return cfg


def credentials() -> tuple:
    """(user, domain, password) from the environment. Raises ApiError."""
    username = (os.environ.get(ENV_USERNAME) or "").strip()
    if not username:
        raise ApiError("The bureau-report API service account is not "
                       "configured: set %s (and %s) in the server's "
                       "environment." % (ENV_USERNAME, ENV_SECRET))
    user, domain = ntlm.split_account(username)
    if not domain:
        domain = (os.environ.get(ENV_DOMAIN) or "").strip()
    return user, domain, os.environ.get(ENV_SECRET) or ""


def fetch_report(subject_id: str, cfg: dict = None) -> bytes:
    """POST the subject id, return the response body -- the payload bytes.

    The request mirrors the integration Postman collection exactly:
    {"cbSubjectId": "<id>"} with a JSON content type, authenticated as the
    service account over NTLMv2. Validation of what comes back is the
    caller's job (context.from_bytes plus context.require_aecb_payload) --
    this module only moves bytes and turns transport failures into readable
    ApiErrors.
    """
    if cfg is None:
        cfg = load_config()
    user, domain, password = credentials()

    url = cfg["base_url"]
    timeout = cfg.get("timeout_seconds") or _DEFAULT_TIMEOUT_S
    body = json.dumps({"cbSubjectId": str(subject_id).strip()}).encode("utf-8")

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
        payload = _read(response)
        if response.status == 200:
            return payload
        if response.status != 401:
            _raise_http(subject_id, url, response, payload)

        challenge = _challenge_from(response)
        if challenge is None:
            _raise_http(subject_id, url, response, payload,
                        hint="The server did not offer an NTLM challenge.")
        if "close" in (response.getheader("Connection") or "").lower():
            _LOG.warning("Bureau API closed the connection mid-NTLM handshake "
                         "(%s); NTLM needs keep-alive.", url)
            raise ApiError("The bureau-report API closed the connection during "
                           "authentication. Raise it with the API team.")

        # Leg 2: answer the challenge on the SAME connection.
        headers = dict(base_headers)
        headers["Authorization"] = ntlm.authenticate_header(
            user, domain, password, challenge)
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        payload = _read(response)
        if response.status == 200:
            return payload
        hint = None
        if response.status == 401:
            hint = ("The service-account credentials were rejected -- check "
                    "%s / %s (the username may need the DOMAIN\\account "
                    "form)." % (ENV_USERNAME, ENV_SECRET))
        _raise_http(subject_id, url, response, payload, hint=hint)
    except ApiError:
        raise
    except (http.client.HTTPException, OSError) as exc:
        _LOG.warning("Bureau API not reachable at %s: %s", url, exc)
        raise ApiError("The bureau-report API is not reachable. Details are "
                       "in the server log.") from None
    finally:
        conn.close()


# A bureau payload is a few hundred KB. Anything this large is not one, and
# reading it unbounded would let a misbehaving endpoint exhaust memory.
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024


def _read(response) -> bytes:
    data = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(data) > _MAX_RESPONSE_BYTES:
        _LOG.warning("Bureau API response exceeded %d bytes; discarded.",
                     _MAX_RESPONSE_BYTES)
        raise ApiError("The bureau-report API returned an oversized response. "
                       "Details are in the server log.")
    return data


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


def _raise_http(subject_id, url, response, payload, hint=None):
    """Log the full error response; raise a short, user-safe ApiError.

    The log gets every header (WWW-Authenticate included) and the body up to
    _LOG_BODY characters -- diagnosis must never depend on what fits in an
    error box. The screen gets the status and, where one applies, a hint
    naming what to check; never the body, which can carry server internals.
    """
    raw_body = payload[:_LOG_BODY].decode("utf-8", "replace")
    _LOG.warning(
        "Bureau API HTTP %d for subject %r\nURL: %s\n"
        "--- response headers ---\n%s"
        "--- response body (first %d chars) ---\n%s\n"
        "--- end of response ---",
        response.status, subject_id, url, response.headers, _LOG_BODY, raw_body)
    message = ("The bureau-report API answered HTTP %d for subject %r."
               % (response.status, subject_id))
    if hint:
        message += " " + hint
    raise ApiError(message + " Details are in the server log.")
