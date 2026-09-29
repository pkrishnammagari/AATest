"""aecb.api against a local NTLMv2-checking HTTP server.

The stub behaves like the IIS endpoint: the first request on a connection is
answered 401 with an NTLM challenge; the second, on the SAME connection, must
carry an AUTHENTICATE message whose NTLMv2 proof verifies against the known
password -- only then does it return the payload.
"""

from __future__ import annotations

import base64
import hmac
import http.server
import json
import logging
import os
import socket
import struct
import threading

import pytest

from aecb import api, ntlm

USER, DOMAIN, SECRET = "svc_aecb", "CORP", "S3cret!"
PAYLOAD = json.dumps({"customerInfo": [{"CBSubjectId": "X1"}]}).encode("utf-8")
_CHALLENGE = bytes.fromhex("0123456789abcdef")


def _challenge_message() -> bytes:
    target_info = struct.pack("<HH", 0, 0)            # MsvAvEOL only
    return (b"NTLMSSP\x00" + struct.pack("<I", 2)
            + struct.pack("<HHI", 0, 0, 48)             # target name
            + struct.pack("<I", 0x00088207)              # flags
            + _CHALLENGE + b"\x00" * 8                   # challenge, reserved
            + struct.pack("<HHI", len(target_info), len(target_info), 48)
            + target_info)


def _field(message, offset):
    length, _max, start = struct.unpack("<HHI", message[offset:offset + 8])
    return message[start:start + length]


def _proof_ok(message: bytes) -> bool:
    nt_response = _field(message, 20)
    domain = _field(message, 28).decode("utf-16-le")
    user = _field(message, 36).decode("utf-16-le")
    key = ntlm._response_key_nt(user, domain, SECRET)
    expected = hmac.new(key, _CHALLENGE + nt_response[16:], "md5").digest()
    return hmac.compare_digest(expected, nt_response[:16])


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive: NTLM is per connection
    mode = "ok"                            # set per test on the class

    def log_message(self, *args):          # keep the test output quiet
        pass

    def _send(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.mode == "error500":
            self._send(500, b"<html><body>Internal detail 10.1.2.3</body></html>")
            return
        auth = self.headers.get("Authorization", "")
        token = base64.b64decode(auth.split(None, 1)[1]) if " " in auth else b""
        if token[8:12] == struct.pack("<I", 1):
            challenge = base64.b64encode(_challenge_message()).decode("ascii")
            self._send(401, headers=[("WWW-Authenticate", "NTLM " + challenge)])
        elif token[8:12] == struct.pack("<I", 3) and _proof_ok(token):
            self._send(200, PAYLOAD if self.mode == "ok" else b"x" * 4096)
        else:
            self._send(401, b"denied", [("WWW-Authenticate", "NTLM")])


@pytest.fixture
def server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/historyapi/api/bureau-report" % httpd.server_port
    httpd.shutdown()
    _Handler.mode = "ok"


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv(api.ENV_USERNAME, USER)
    monkeypatch.setenv(api.ENV_DOMAIN, DOMAIN)
    monkeypatch.setenv(api.ENV_SECRET, SECRET)


@pytest.mark.usefixtures("credentials")
def test_ntlm_handshake_returns_the_payload(server):
    assert api.fetch_report("X1", {"base_url": server}) == PAYLOAD


def test_domain_backslash_form_is_accepted(server, monkeypatch):
    monkeypatch.setenv(api.ENV_USERNAME, "%s\\%s" % (DOMAIN, USER))
    monkeypatch.delenv(api.ENV_DOMAIN, raising=False)
    monkeypatch.setenv(api.ENV_SECRET, SECRET)
    assert api.fetch_report("X1", {"base_url": server}) == PAYLOAD


@pytest.mark.usefixtures("credentials")
def test_wrong_password_is_reported_without_internals(server, monkeypatch):
    monkeypatch.setenv(api.ENV_SECRET, "wrong")
    with pytest.raises(api.ApiError) as err:
        api.fetch_report("X1", {"base_url": server})
    message = str(err.value)
    assert "credentials were rejected" in message
    assert "127.0.0.1" not in message and "denied" not in message


@pytest.mark.usefixtures("credentials")
def test_http_error_body_goes_to_the_log_not_the_screen(server, caplog):
    _Handler.mode = "error500"
    with caplog.at_level(logging.WARNING, logger="aecb.api"):
        with pytest.raises(api.ApiError) as err:
            api.fetch_report("X1", {"base_url": server})
    assert "HTTP 500" in str(err.value)
    assert "10.1.2.3" not in str(err.value)
    assert "10.1.2.3" in caplog.text


@pytest.mark.usefixtures("credentials")
def test_unreachable_endpoint_hides_the_address():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]          # closed once the block exits
    with pytest.raises(api.ApiError) as err:
        api.fetch_report("X1", {"base_url": "http://127.0.0.1:%d/x" % port,
                                "timeout_seconds": 2})
    assert "not reachable" in str(err.value)
    assert "127.0.0.1" not in str(err.value)


@pytest.mark.usefixtures("credentials")
def test_oversized_response_is_refused(server, monkeypatch):
    _Handler.mode = "big"
    monkeypatch.setattr(api, "_MAX_RESPONSE_BYTES", 1024)
    with pytest.raises(api.ApiError, match="oversized"):
        api.fetch_report("X1", {"base_url": server})


def test_missing_credentials_are_a_clear_error(monkeypatch):
    monkeypatch.delenv(api.ENV_USERNAME, raising=False)
    with pytest.raises(api.ApiError, match="AECB_API_USERNAME"):
        api.fetch_report("X1", {"base_url": "http://127.0.0.1:1/x"})


def test_config_file_with_credentials_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "api.json"
    path.write_text(json.dumps({"base_url": "http://h/x",
                                "auth": {"username": "u"}}), encoding="utf-8")
    monkeypatch.setattr(api, "CONFIG_PATH", str(path))
    with pytest.raises(api.ApiError, match="must not carry credentials"):
        api.load_config()


def test_committed_config_carries_no_credentials():
    cfg = api.load_config()
    settings = {k: v for k, v in cfg.items() if not k.startswith("_")}
    assert settings["base_url"] and "auth" not in settings
    assert "password" not in json.dumps(settings).lower()


def test_malformed_config_is_a_clear_error(tmp_path, monkeypatch):
    path = tmp_path / "api.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(api, "CONFIG_PATH", str(path))
    with pytest.raises(api.ApiError, match="not valid JSON"):
        api.load_config()
    monkeypatch.setattr(api, "CONFIG_PATH", os.path.join(str(tmp_path), "none"))
    with pytest.raises(api.ApiError, match="missing"):
        api.load_config()
