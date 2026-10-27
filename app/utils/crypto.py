"""API key gateway: lgw_<prefix 8 [a-z0-9]>_<secret 43 char token_urlsafe(32)>.

DB hanya menyimpan key_prefix (`lgw_<prefix>`) dan HMAC-SHA256(pepper, full_key)."""

import hashlib
import hmac
import re
import secrets
import string

from app.core.config import get_settings

KEY_SCHEME = "lgw"
PREFIX_LEN = 8
_PREFIX_ALPHABET = string.ascii_lowercase + string.digits
KEY_RE = re.compile(r"^(lgw_[a-z0-9]{8})_([A-Za-z0-9_\-]{43})$")


def _pepper() -> bytes:
    return get_settings().gateway_key_pepper.get_secret_value().encode()


def hash_api_key(full_key: str, *, pepper: bytes | None = None) -> str:
    return hmac.new(pepper or _pepper(), full_key.encode(), hashlib.sha256).hexdigest()


def verify(full_key: str, stored_hash: str, *, pepper: bytes | None = None) -> bool:
    return hmac.compare_digest(hash_api_key(full_key, pepper=pepper), stored_hash)


def parse_key_prefix(raw_key: str) -> str | None:
    """Kembalikan key_prefix (`lgw_xxxxxxxx`) bila format valid, selain itu None."""
    match = KEY_RE.match(raw_key)
    return match.group(1) if match else None


def generate_api_key(*, pepper: bytes | None = None) -> tuple[str, str, str]:
    """Kembalikan (full_key, key_prefix, key_hash). full_key hanya ditampilkan sekali."""
    while True:
        prefix = KEY_SCHEME + "_" + "".join(
            secrets.choice(_PREFIX_ALPHABET) for _ in range(PREFIX_LEN)
        )
        full_key = f"{prefix}_{secrets.token_urlsafe(32)}"
        if KEY_RE.match(full_key):  # token_urlsafe(32) selalu 43 char; dijaga eksplisit
            return full_key, prefix, hash_api_key(full_key, pepper=pepper)
