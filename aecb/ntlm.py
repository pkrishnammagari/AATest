"""Minimal NTLMv2 client authentication (MS-NLMP), stdlib only.

The bureau-report API sits behind IIS Windows authentication (WWW-Authenticate:
Negotiate/NTLM). The deployment server is air-gapped with a deliberately
one-line requirements.txt, so rather than adding pyspnego + cryptography
wheels to the offline bundle, the three-message NTLMv2
handshake is implemented here from the MS-NLMP specification:

    type 1  NEGOTIATE     ->  we announce ourselves
    type 2  CHALLENGE     <-  server sends an 8-byte challenge + target info
    type 3  AUTHENTICATE  ->  we prove knowledge of the password via
                              HMAC-MD5 over the challenge (NTLMv2), never
                              sending the password itself

Only NTLMv2 is produced (no LM, no NTLMv1 -- both are broken and IIS defaults
reject them). The NT hash needs MD4, which OpenSSL 3 removed from the default
provider, so a pure-Python MD4 (RFC 1320) is included and used when
hashlib.new("md4") is unavailable.

Correctness is anchored to the published test vectors (RFC 1320 for MD4,
MS-NLMP 4.2.4 for NTLMv2) in tests/test_ntlm.py, and the full handshake is
exercised against a proof-checking local server in tests/test_api.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time

_SIGNATURE = b"NTLMSSP\x00"

# Negotiate flags (MS-NLMP 2.2.2.5): UNICODE, OEM, REQUEST_TARGET, NTLM,
# ALWAYS_SIGN, EXTENDED_SESSIONSECURITY, 128, 56. No VERSION (we send none),
# no KEY_EXCH (we neither sign nor seal -- this is authentication only).
_FLAGS = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000200 \
    | 0x00008000 | 0x00080000 | 0x20000000 | 0x80000000


# --- MD4 (RFC 1320) ----------------------------------------------------------
# OpenSSL 3 moved MD4 to the legacy provider, so hashlib.new("md4") raises on
# most modern builds. NTLM's NT hash is defined over MD4 and nothing newer,
# hence this fallback. MD4 is used here ONLY because the NTLM protocol
# mandates it; it protects nothing on its own (see the module docstring).

_MASK = 0xFFFFFFFF


def _lrot(value, n):
    value &= _MASK
    return ((value << n) | (value >> (32 - n))) & _MASK


def _f(x, y, z):
    return (x & y) | (~x & z)


def _g(x, y, z):
    return (x & y) | (x & z) | (y & z)


def _h(x, y, z):
    return x ^ y ^ z


# (round function, message-word order, shift per step mod 4, additive constant)
_MD4_ROUNDS = (
    (_f, tuple(range(16)), (3, 7, 11, 19), 0),
    (_g, (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15),
     (3, 5, 9, 13), 0x5A827999),
    (_h, (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15),
     (3, 9, 11, 15), 0x6ED9EBA1),
)


def _md4_round(state, words, fn, order, shifts, const):
    """One RFC 1320 round. Each step updates the first register and rotates
    the four, so the register roles (a, d, c, b) cycle exactly as the RFC
    writes them out long-hand."""
    a, b, c, d = state
    for i, k in enumerate(order):
        a = _lrot(a + fn(b, c, d) + words[k] + const, shifts[i % 4])
        a, b, c, d = d, a, b, c
    return a, b, c, d


def _md4_pure(data: bytes) -> bytes:
    message = bytearray(data)
    bit_len = (8 * len(message)) & 0xFFFFFFFFFFFFFFFF
    message.append(0x80)
    while len(message) % 64 != 56:
        message.append(0)
    message += struct.pack("<Q", bit_len)

    state = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476)
    for chunk in range(0, len(message), 64):
        words = struct.unpack("<16I", message[chunk:chunk + 64])
        block = state
        for fn, order, shifts, const in _MD4_ROUNDS:
            block = _md4_round(block, words, fn, order, shifts, const)
        state = tuple((x + y) & _MASK for x, y in zip(state, block))
    return struct.pack("<4I", *state)


def _md4(data: bytes) -> bytes:
    try:
        return hashlib.new("md4", data).digest()
    except ValueError:
        return _md4_pure(data)


# --- NTLMv2 crypto (MS-NLMP 3.3.2) ------------------------------------------

def _nt_hash(password: str) -> bytes:
    return _md4(password.encode("utf-16-le"))


def _response_key_nt(username: str, domain: str, password: str) -> bytes:
    """NTOWFv2: HMAC-MD5 keyed by the NT hash over UPPER(user) + domain."""
    return hmac.new(_nt_hash(password),
                    (username.upper() + domain).encode("utf-16-le"),
                    "md5").digest()


def _nt_proof(key: bytes, server_challenge: bytes, temp: bytes) -> bytes:
    return hmac.new(key, server_challenge + temp, "md5").digest()


def _filetime_now() -> bytes:
    # Windows FILETIME: 100ns intervals since 1601-01-01.
    return struct.pack("<Q", int((time.time() + 11644473600) * 10000000))


# --- messages ----------------------------------------------------------------

def negotiate_message() -> bytes:
    """Type 1: signature, type, flags, empty domain/workstation fields."""
    return (_SIGNATURE + struct.pack("<I", 1) + struct.pack("<I", _FLAGS)
            + struct.pack("<HHI", 0, 0, 32)      # domain: len, maxlen, offset
            + struct.pack("<HHI", 0, 0, 32))     # workstation


def parse_challenge(message: bytes):
    """Type 2 -> (server_challenge 8 bytes, target_info bytes, flags)."""
    if message[:8] != _SIGNATURE or struct.unpack("<I", message[8:12])[0] != 2:
        raise ValueError("not an NTLM CHALLENGE message")
    flags = struct.unpack("<I", message[20:24])[0]
    server_challenge = message[24:32]
    target_info = b""
    if len(message) >= 48:
        ti_len, _max, ti_off = struct.unpack("<HHI", message[40:48])
        target_info = message[ti_off:ti_off + ti_len]
    return server_challenge, target_info, flags


def authenticate_message(username: str, domain: str, password: str,
                         server_challenge: bytes, target_info: bytes,
                         client_challenge: bytes = None,
                         timestamp: bytes = None) -> bytes:
    """Type 3, carrying the NTLMv2 (and LMv2) proofs. No password on the wire.

    client_challenge/timestamp are injectable so the MS-NLMP test vectors can
    drive them; production callers leave both None.
    """
    if client_challenge is None:
        client_challenge = os.urandom(8)
    if timestamp is None:
        timestamp = _filetime_now()

    key = _response_key_nt(username, domain, password)

    # temp (MS-NLMP 3.3.2): versions, zeros, time, client nonce, zeros,
    # the server's target info UNMODIFIED, zeros.
    temp = (b"\x01\x01" + b"\x00" * 6 + timestamp + client_challenge
            + b"\x00" * 4 + target_info + b"\x00" * 4)
    nt_response = _nt_proof(key, server_challenge, temp) + temp
    lm_response = hmac.new(key, server_challenge + client_challenge,
                           "md5").digest() + client_challenge

    domain_b = domain.encode("utf-16-le")
    user_b = username.encode("utf-16-le")
    workstation_b = b""

    # Payload starts after the fixed 64-byte header (no version, no MIC).
    offset = 64
    fields = []
    payload = b""
    for blob in (lm_response, nt_response, domain_b, user_b, workstation_b,
                 b""):                       # b"": no session key (no KEY_EXCH)
        fields.append(struct.pack("<HHI", len(blob), len(blob), offset))
        payload += blob
        offset += len(blob)

    return (_SIGNATURE + struct.pack("<I", 3) + b"".join(fields)
            + struct.pack("<I", _FLAGS) + payload)


def negotiate_header() -> str:
    return "NTLM " + base64.b64encode(negotiate_message()).decode("ascii")


def authenticate_header(username: str, domain: str, password: str,
                        challenge_b64: str) -> str:
    server_challenge, target_info, _flags = parse_challenge(
        base64.b64decode(challenge_b64))
    message = authenticate_message(username, domain, password,
                                   server_challenge, target_info)
    return "NTLM " + base64.b64encode(message).decode("ascii")


def split_account(username: str):
    """'DOMAIN\\user' -> (user, DOMAIN); plain or UPN names pass through."""
    if "\\" in username:
        domain, user = username.split("\\", 1)
        return user, domain
    return username, ""
