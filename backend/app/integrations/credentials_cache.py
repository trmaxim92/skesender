"""In-process cache for decrypted channel credentials (C8)."""

from __future__ import annotations

import hashlib
import threading
from typing import Callable

_lock = threading.Lock()
# channel_id -> (credentials_enc fingerprint, plaintext)
_cache: dict[int, tuple[str, str]] = {}


def _fp(credentials_enc: str) -> str:
    return hashlib.sha256(credentials_enc.encode("utf-8")).hexdigest()


def decrypt_cached(
    channel_id: int,
    credentials_enc: str,
    *,
    decrypt: Callable[[str], str],
) -> str:
    """Decrypt credentials once per (channel_id, credentials_enc) value."""
    key = _fp(credentials_enc)
    with _lock:
        hit = _cache.get(channel_id)
        if hit is not None and hit[0] == key:
            return hit[1]
    plain = decrypt(credentials_enc)
    with _lock:
        _cache[channel_id] = (key, plain)
    return plain


def invalidate(channel_id: int | None = None) -> None:
    with _lock:
        if channel_id is None:
            _cache.clear()
        else:
            _cache.pop(channel_id, None)
