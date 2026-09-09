"""Minimal NTLMv2 client authentication (MS-NLMP), stdlib only.

The bureau-report API sits behind IIS Windows authentication (WWW-Authenticate:
Negotiate/NTLM, confirmed by the API team 9 Sep 2026). The deployment server is
air-gapped with a deliberately one-line requirements.txt, so rather than adding
pyspnego + cryptography wheels to the offline bundle, the three-message NTLMv2
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

Correctness is anchored to the official MS-NLMP 4.2.4 NTLMv2 test vectors --
scripts/check_report.py's suite does not cover this module; run
python3 -m aecb.ntlm to execute the self-test.
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
# hence this fallback. Constant-table-free reference implementation.

def _md4_pure(data: bytes) -> bytes:
    def lrot(value, n):
        value &= 0xFFFFFFFF
        return ((value << n) | (value >> (32 - n))) & 0xFFFFFFFF

    message = bytearray(data)
    bit_len = (8 * len(message)) & 0xFFFFFFFFFFFFFFFF
    message.append(0x80)
    while len(message) % 64 != 56:
        message.append(0)
    message += struct.pack("<Q", bit_len)

    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for chunk in range(0, len(message), 64):
        x = struct.unpack("<16I", message[chunk:chunk + 64])
        aa, bb, cc, dd = a, b, c, d

        def f(x_, y_, z_):
            return (x_ & y_) | (~x_ & z_)

        def g(x_, y_, z_):
            return (x_ & y_) | (x_ & z_) | (y_ & z_)

        def h(x_, y_, z_):
            return x_ ^ y_ ^ z_

        # Round 1
        for i, s in zip(range(16), (3, 7, 11, 19) * 4):
            if i % 4 == 0:
                a = lrot(a + f(b, c, d) + x[i], s)
            elif i % 4 == 1:
                d = lrot(d + f(a, b, c) + x[i], s)
            elif i % 4 == 2:
                c = lrot(c + f(d, a, b) + x[i], s)
            else:
                b = lrot(b + f(c, d, a) + x[i], s)
        # Round 2
        order2 = (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15)
        for i, k in enumerate(order2):
            s = (3, 5, 9, 13)[i % 4]
            if i % 4 == 0:
                a = lrot(a + g(b, c, d) + x[k] + 0x5A827999, s)
            elif i % 4 == 1:
                d = lrot(d + g(a, b, c) + x[k] + 0x5A827999, s)
            elif i % 4 == 2:
                c = lrot(c + g(d, a, b) + x[k] + 0x5A827999, s)
            else:
                b = lrot(b + g(c, d, a) + x[k] + 0x5A827999, s)
        # Round 3
        order3 = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)
        for i, k in enumerate(order3):
            s = (3, 9, 11, 15)[i % 4]
            if i % 4 == 0:
                a = lrot(a + h(b, c, d) + x[k] + 0x6ED9EBA1, s)
            elif i % 4 == 1:
                d = lrot(d + h(a, b, c) + x[k] + 0x6ED9EBA1, s)
            elif i % 4 == 2:
                c = lrot(c + h(d, a, b) + x[k] + 0x6ED9EBA1, s)
            else:
                b = lrot(b + h(c, d, a) + x[k] + 0x6ED9EBA1, s)

        a = (a + aa) & 0xFFFFFFFF
        b = (b + bb) & 0xFFFFFFFF
        c = (c + cc) & 0xFFFFFFFF
        d = (d + dd) & 0xFFFFFFFF

    return struct.pack("<4I", a, b, c, d)


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


# --- self-test: the official MS-NLMP 4.2.4 NTLMv2 vectors -------------------

def self_test() -> None:
    # RFC 1320 MD4 vectors, forcing the pure implementation.
    assert _md4_pure(b"").hex() == "31d6cfe0d16ae931b73c59d7e0c089c0"
    assert _md4_pure(b"abc").hex() == "a448017aaf21d8525fc10ae87aa6729d"

    # MS-NLMP 4.2.4: User="User", Domain="Domain", Password="Password",
    # server challenge 0x0123456789abcdef, client challenge 0xaa*8, time 0,
    # target info = NbDomain "Domain" + NbComputer "Server" + EOL.
    key = _response_key_nt("User", "Domain", "Password")
    assert key.hex() == "0c868a403bfd7a93a3001ef22ef02e3f", key.hex()

    server_challenge = bytes.fromhex("0123456789abcdef")
    client_challenge = b"\xaa" * 8
    target_info = (struct.pack("<HH", 2, 12) + "Domain".encode("utf-16-le")
                   + struct.pack("<HH", 1, 12) + "Server".encode("utf-16-le")
                   + struct.pack("<HH", 0, 0))
    temp = (b"\x01\x01" + b"\x00" * 6 + b"\x00" * 8 + client_challenge
            + b"\x00" * 4 + target_info + b"\x00" * 4)
    proof = _nt_proof(key, server_challenge, temp)
    assert proof.hex() == "68cd0ab851e51c96aabc927bebef6a1c", proof.hex()

    lm = hmac.new(key, server_challenge + client_challenge, "md5").digest()
    assert lm.hex() == "86c35097ac9cec102554764a57cccc19", lm.hex()

    # Round-trip: our own challenge parses, and the authenticate message the
    # header helpers build carries the same proof.
    msg = authenticate_message("User", "Domain", "Password", server_challenge,
                               target_info, client_challenge=client_challenge,
                               timestamp=b"\x00" * 8)
    assert msg[:8] == _SIGNATURE and struct.unpack("<I", msg[8:12])[0] == 3
    nt_len, _max, nt_off = struct.unpack("<HHI", msg[20:28])
    assert msg[nt_off:nt_off + 16].hex() == "68cd0ab851e51c96aabc927bebef6a1c"


if __name__ == "__main__":
    self_test()
    print("ok: MD4 (RFC 1320) and NTLMv2 (MS-NLMP 4.2.4) vectors all match")
