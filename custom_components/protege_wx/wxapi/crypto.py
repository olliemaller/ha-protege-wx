"""Crypto primitives for the Protege WX web-programming protocol.

Derived from protege-wx-cli by Mitchell Johnson (MIT licence), which ports the
controller's own JavaScript (encrypt.js / secure.js) byte for byte:

* login is a SHA-1 challenge/response; the password itself never leaves this
  machine, only SHA-1 digests mixed with server-issued seeds;
* the session key ("WXKey") is the first 16 hex characters of a further SHA-1,
  used as an AES-128 key;
* commands and replies are HEX( IV(16) || AES-128-CBC( PKCS7(text) ) ).
"""
from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BLOCK = 16


def sha1_hex(text: str, *, upper: bool = False) -> str:
    """SHA-1 of a string as jsSHA(text, "TEXT") computes it (low byte per char)."""
    digest = hashlib.sha1(bytes((ord(ch) & 0xFF) for ch in text)).hexdigest()
    return digest.upper() if upper else digest


def xor_with_seed(text: str, seed: int) -> str:
    """Port of the web UI's ``xor(text, seed)``.

    Each UTF-8 byte of ``text`` is XORed with successive bytes of the 32-bit
    binary form of ``seed``, least significant byte first, cycling every four
    bytes. Returns upper-case hex.
    """
    bits = bin(int(seed) & 0xFFFFFFFF)[2:].zfill(32)
    pos = len(bits)
    out = []
    for byte in text.encode("utf-8"):
        pos = (len(bits) - 8) if pos == 0 else (pos - 8)
        out.append(f"{byte ^ int(bits[pos:pos + 8], 2):02X}")
    return "".join(out)


def login_hashes(username: str, password_sha1: str, seed0: int) -> tuple[str, str]:
    """Return the (Name, Password) values for CheckPassword."""
    name_hash = sha1_hex(xor_with_seed(username.lower(), seed0 + 1), upper=True)
    password_hash = sha1_hex(xor_with_seed(password_sha1, seed0), upper=True)
    return name_hash, password_hash


def session_key(password_sha1: str, seed1: int) -> str:
    """Derive the 16-character AES-128 session key from CheckPassword's reply."""
    return sha1_hex(xor_with_seed(password_sha1, seed1), upper=True)[:16]


def _pad(data: bytes) -> bytes:
    count = BLOCK - (len(data) % BLOCK) or BLOCK
    return data + bytes([count]) * count


def _unpad(data: bytes) -> bytes:
    if data and 0 < data[-1] <= BLOCK:
        return data[: -data[-1]]
    return data


def _random_iv() -> bytes:
    # The web UI picks 16 random characters in the ASCII range 48..122.
    return bytes((byte % 75) + 48 for byte in os.urandom(BLOCK))


def encrypt(text: str, key: str, *, iv: bytes | None = None) -> str:
    """Encrypt a command for the wire: HEX(IV || AES-128-CBC(PKCS7(text)))."""
    iv = iv or _random_iv()
    encryptor = Cipher(algorithms.AES(key.encode("ascii")), modes.CBC(iv)).encryptor()
    body = encryptor.update(_pad(text.encode("utf-8"))) + encryptor.finalize()
    return (iv + body).hex().upper()


def decrypt(hex_text: str, key: str) -> str:
    """Decrypt a reply from the wire. Raises ValueError on malformed input."""
    raw = bytes.fromhex(hex_text.strip())
    if len(raw) < 2 * BLOCK or len(raw) % BLOCK:
        raise ValueError("ciphertext has an invalid length")
    iv, body = raw[:BLOCK], raw[BLOCK:]
    decryptor = Cipher(algorithms.AES(key.encode("ascii")), modes.CBC(iv)).decryptor()
    plain = decryptor.update(body) + decryptor.finalize()
    return _unpad(plain.rstrip(b"\x00")).decode("utf-8", errors="replace")
