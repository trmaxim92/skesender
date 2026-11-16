"""TLS verify helper for MAX API (platform-api2.max.ru uses Минцифры CA)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.config import BACKEND_DIR, get_settings

logger = logging.getLogger(__name__)

_RUSSIAN_BUNDLE = BACKEND_DIR / "certs" / "russian_trusted_ca_bundle.pem"
_COMBINED_BUNDLE = BACKEND_DIR / "data" / "cacert_with_russian_trusted.pem"
_SYSTEM_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")


def _ensure_combined_bundle() -> Path | None:
    """certifi + Russian Trusted CA — httpx uses certifi by default, not system store."""
    if not _RUSSIAN_BUNDLE.is_file():
        return None
    try:
        import certifi
    except ImportError:
        return _RUSSIAN_BUNDLE if _RUSSIAN_BUNDLE.is_file() else None

    certifi_path = Path(certifi.where())
    russian = _RUSSIAN_BUNDLE.read_bytes().strip()
    marker = b"Russian Trusted Root CA"
    if _COMBINED_BUNDLE.is_file():
        existing = _COMBINED_BUNDLE.read_bytes()
        if marker in existing and _COMBINED_BUNDLE.stat().st_mtime >= max(
            certifi_path.stat().st_mtime, _RUSSIAN_BUNDLE.stat().st_mtime
        ):
            return _COMBINED_BUNDLE

    _COMBINED_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    base = certifi_path.read_bytes().rstrip() + b"\n"
    _COMBINED_BUNDLE.write_bytes(base + russian + b"\n")
    logger.info("Wrote MAX TLS bundle with Минцифры CA: %s", _COMBINED_BUNDLE)
    return _COMBINED_BUNDLE


@lru_cache(maxsize=1)
def max_ssl_verify() -> bool | str:
    """Return httpx ``verify`` value for MAX HTTP clients.

    - ``False`` when MAX_API_VERIFY_SSL=false
    - path to CA bundle when verification is on (Минцифры + certifi / system)
    """
    settings = get_settings()
    if not settings.max_api_verify_ssl:
        return False

    custom = (settings.max_api_ca_bundle or "").strip()
    if custom:
        path = Path(custom)
        if path.is_file():
            return str(path)
        logger.warning("MAX_API_CA_BUNDLE not found: %s — falling back", custom)

    combined = _ensure_combined_bundle()
    if combined and combined.is_file():
        return str(combined)

    if _SYSTEM_BUNDLE.is_file():
        return str(_SYSTEM_BUNDLE)

    if _RUSSIAN_BUNDLE.is_file():
        return str(_RUSSIAN_BUNDLE)

    logger.warning(
        "MAX_API_VERIFY_SSL=true but no Минцифры CA bundle found under %s",
        _RUSSIAN_BUNDLE,
    )
    return True
