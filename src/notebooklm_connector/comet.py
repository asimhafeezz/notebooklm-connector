"""Read Google session cookies from Comet (Perplexity's Chromium browser).

rookiepy has no built-in reader for Comet, so we do the standard
Chromium-on-macOS cookie decryption ourselves and return rookiepy-shaped
dicts that plug into the same login pipeline as every other browser.

macOS only (Comet is macOS/Windows; this covers the macOS cookie store).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Chromium data dir for Comet on macOS; {profile} is usually "Default".
_COOKIES_PATH = "~/Library/Application Support/Comet/{profile}/Cookies"
_KEYCHAIN_SERVICE = "Comet Safe Storage"
_CHROMIUM_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def cookies_db_path(profile: str = "Default") -> Path:
    return Path(os.path.expanduser(_COOKIES_PATH.format(profile=profile)))


def is_available(profile: str = "Default") -> bool:
    return cookies_db_path(profile).exists()


def _keychain_password() -> str:
    """Read Comet's cookie-encryption key from the macOS Keychain."""
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"Could not read the '{_KEYCHAIN_SERVICE}' key from the macOS Keychain. "
            "Approve the Keychain prompt if one appears, and make sure Comet is "
            "installed and you have signed in to Google in it."
        )
    return proc.stdout.strip()


def _derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1003, dklen=16)


def _decrypt_value(encrypted: bytes, key: bytes, host: str) -> str:
    """Decrypt a Chromium 'v10'/'v11' AES-128-CBC cookie value (macOS)."""
    if not encrypted or encrypted[:3] not in (b"v10", b"v11"):
        return ""
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
    dec = cipher.decryptor()
    data = dec.update(encrypted[3:]) + dec.finalize()
    if data:  # strip PKCS7 padding
        pad = data[-1]
        if 1 <= pad <= 16:
            data = data[:-pad]
    # Chromium ≥130 prepends SHA256(host_key) (32 bytes) to the plaintext.
    # Strip it only when it actually matches — deterministic, unlike a utf-8 guess.
    if len(data) >= 32 and data[:32] == hashlib.sha256(host.encode("utf-8")).digest():
        data = data[32:]
    return data.decode("utf-8", errors="replace")


def read_comet_cookies(
    profile: str = "Default", domains: list[str] | None = ("google.com", "youtube.com")
) -> list[dict]:
    """Return Comet's cookies as rookiepy-style dicts (domain/name/value/...).

    Args:
        profile: Comet profile directory name (default "Default").
        domains: Substrings to filter host_key by (default Google domains).
            Pass None to read every cookie.
    """
    src = cookies_db_path(profile)
    if not src.exists():
        raise RuntimeError(
            f"Comet cookie database not found at {src}. "
            "Is Comet installed, and have you signed in to Google in it?"
        )
    key = _derive_key(_keychain_password())

    # Copy the DB first — Chromium keeps it locked while running.
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "Cookies"
        shutil.copy2(src, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        con.text_factory = bytes  # encrypted_value is a BLOB; avoid UTF-8 decode errors
        try:
            rows = con.execute(
                "SELECT host_key, name, encrypted_value, path, expires_utc, "
                "is_secure, is_httponly FROM cookies"
            ).fetchall()
        finally:
            con.close()

    def _s(v: object) -> str:
        return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

    out: list[dict] = []
    for host_b, name_b, enc, path_b, expires_utc, secure, httponly in rows:
        host, name, path = _s(host_b), _s(name_b), _s(path_b)
        if domains and not any(d in host for d in domains):
            continue
        value = _decrypt_value(enc, key, host)
        if not value:
            continue
        expires = None if not expires_utc else (expires_utc / 1_000_000 - _CHROMIUM_EPOCH_OFFSET)
        out.append(
            {
                "domain": host,
                "name": name,
                "value": value,
                "path": path or "/",
                "expires": expires,
                "secure": bool(secure),
                "http_only": bool(httponly),
            }
        )
    return out
