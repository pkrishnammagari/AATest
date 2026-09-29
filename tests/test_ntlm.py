"""aecb.ntlm against the published test vectors (RFC 1320, MS-NLMP 4.2.4)."""

from __future__ import annotations

import base64
import hmac
import struct

import pytest

from aecb import ntlm


@pytest.mark.parametrize("message, digest", [
    (b"", "31d6cfe0d16ae931b73c59d7e0c089c0"),
    (b"a", "bde52cb31de33e46245e05fbdbd6fb24"),
    (b"abc", "a448017aaf21d8525fc10ae87aa6729d"),
    (b"message digest", "d9130a8164549fe818874806e1c7014b"),
    (b"abcdefghijklmnopqrstuvwxyz", "d79e1c308aa5bbcdeea8ed63df412da9"),
    (b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
     "043f8582f241db351ce627e153e7f0e4"),
    (b"1234567890" * 8, "e33b4ddc9c38f2199c3e7b164fcc0536"),
])
def test_md4_rfc1320_vectors(message, digest):
    assert ntlm._md4_pure(message).hex() == digest


# MS-NLMP 4.2.4: User="User", Domain="Domain", Password="Password", server
# challenge 0x0123456789abcdef, client challenge 0xaa*8, time 0, target info
# NbDomain "Domain" + NbComputer "Server" + EOL.
_SERVER_CHALLENGE = bytes.fromhex("0123456789abcdef")
_CLIENT_CHALLENGE = b"\xaa" * 8
_TARGET_INFO = (struct.pack("<HH", 2, 12) + "Domain".encode("utf-16-le")
                + struct.pack("<HH", 1, 12) + "Server".encode("utf-16-le")
                + struct.pack("<HH", 0, 0))
_TEMP = (b"\x01\x01" + b"\x00" * 6 + b"\x00" * 8 + _CLIENT_CHALLENGE
         + b"\x00" * 4 + _TARGET_INFO + b"\x00" * 4)


def test_ntowfv2_vector():
    key = ntlm._response_key_nt("User", "Domain", "Password")
    assert key.hex() == "0c868a403bfd7a93a3001ef22ef02e3f"


def test_ntproofstr_and_lmv2_vectors():
    key = ntlm._response_key_nt("User", "Domain", "Password")
    assert ntlm._nt_proof(key, _SERVER_CHALLENGE, _TEMP).hex() == \
        "68cd0ab851e51c96aabc927bebef6a1c"
    lm = hmac.new(key, _SERVER_CHALLENGE + _CLIENT_CHALLENGE, "md5").digest()
    assert lm.hex() == "86c35097ac9cec102554764a57cccc19"


def test_authenticate_message_carries_the_vector_proof():
    msg = ntlm.authenticate_message("User", "Domain", "Password",
                                    _SERVER_CHALLENGE, _TARGET_INFO,
                                    client_challenge=_CLIENT_CHALLENGE,
                                    timestamp=b"\x00" * 8)
    assert msg[:8] == b"NTLMSSP\x00" and struct.unpack("<I", msg[8:12])[0] == 3
    _len, _max, nt_off = struct.unpack("<HHI", msg[20:28])
    assert msg[nt_off:nt_off + 16].hex() == "68cd0ab851e51c96aabc927bebef6a1c"
    assert b"Password" not in msg and "Password".encode("utf-16-le") not in msg


def test_negotiate_and_challenge_round_trip():
    header = ntlm.negotiate_header()
    assert header.startswith("NTLM ")
    assert base64.b64decode(header[5:])[:8] == b"NTLMSSP\x00"
    with pytest.raises(ValueError):
        ntlm.parse_challenge(b"not a challenge message")


@pytest.mark.parametrize("account, expected", [
    ("CORP\\svc", ("svc", "CORP")), ("svc", ("svc", "")),
    ("svc@corp.example", ("svc@corp.example", "")),
])
def test_split_account(account, expected):
    assert ntlm.split_account(account) == expected
