"""Shared TELEGRAM_PROXY helpers for Bot API (httpx) and Telethon (MTProto)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, unquote, urlparse

from app.config import get_settings
from app.integrations.base import IntegrationError

logger = logging.getLogger(__name__)

# host:port or host:port:user:pass (PROXYMANIA-style)
_HOST_PORT_RE = re.compile(
    r"^(?P<host>[^:\s]+):(?P<port>\d{2,5})(?::(?P<user>[^:]*):(?P<password>.*))?$"
)


def telegram_proxy_url() -> str | None:
    raw = (get_settings().telegram_proxy or "").strip()
    return raw or None


def httpx_proxy() -> str | None:
    """Return proxy URL for httpx.AsyncClient(proxy=...), or None."""
    return telegram_proxy_url()


def normalize_proxy_url(raw: str) -> str:
    """Normalize user/env proxy string to a URL with scheme."""
    text = (raw or "").strip()
    if not text:
        raise IntegrationError("Прокси не задан")

    if "://" in text:
        return text

    match = _HOST_PORT_RE.match(text)
    if not match:
        raise IntegrationError(
            "Прокси: socks5://user:pass@host:port или host:port:user:pass"
        )
    host = match.group("host")
    port = match.group("port")
    user = match.group("user")
    password = match.group("password")
    if user is not None:
        return (
            f"socks5://{quote(user, safe='')}:{quote(password or '', safe='')}@"
            f"{host}:{port}"
        )
    return f"socks5://{host}:{port}"


def parse_telethon_proxy(raw: str) -> dict[str, Any]:
    """Parse a proxy string into a Telethon proxy config dict."""
    url = normalize_proxy_url(raw)
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise IntegrationError(
            "Прокси должен быть вида socks5://host:1080 или host:port:user:pass"
        )
    if scheme in {"socks5", "socks5h"}:
        proxy_type = "socks5"
    elif scheme in {"socks4", "socks4a"}:
        proxy_type = "socks4"
    elif scheme in {"http", "https"}:
        proxy_type = "http"
    else:
        raise IntegrationError(f"Неподдерживаемый proxy scheme: {scheme}")

    cfg: dict[str, Any] = {
        "proxy_type": proxy_type,
        "addr": host,
        "port": int(port),
        "rdns": True,
    }
    if parsed.username:
        cfg["username"] = unquote(parsed.username)
    if parsed.password:
        cfg["password"] = unquote(parsed.password)
    return cfg


def redact_proxy_url(raw: str) -> str:
    """Hide password in logs."""
    try:
        url = normalize_proxy_url(raw)
        parsed = urlparse(url)
        if not parsed.password:
            return url
        return url.replace(parsed.password, "***").replace(
            quote(unquote(parsed.password), safe=""), "***"
        )
    except Exception:
        return "(set)"


def telethon_proxy(override: str | None = None) -> dict[str, Any] | None:
    """Parse channel override or env TELEGRAM_PROXY into a Telethon proxy config."""
    raw = (override or "").strip() or telegram_proxy_url()
    if not raw:
        return None
    return parse_telethon_proxy(raw)


async def log_telegram_proxy_status() -> None:
    """Startup check: warn if proxy is set but unreachable, or log that it is active."""
    import httpx

    proxy = httpx_proxy()
    if not proxy:
        logger.info("TELEGRAM_PROXY not set — Bot/MTProto go direct (per-channel proxy still OK)")
        return

    safe = redact_proxy_url(proxy)

    try:
        # httpx needs a URL with scheme; normalize bare host:port forms
        httpx_url = normalize_proxy_url(proxy)
        async with httpx.AsyncClient(proxy=httpx_url, timeout=12.0, follow_redirects=True) as client:
            response = await client.get("https://api.telegram.org/")
        logger.info(
            "TELEGRAM_PROXY ok (%s) — api.telegram.org HTTP %s",
            safe,
            response.status_code,
        )
    except Exception as exc:
        logger.error(
            "TELEGRAM_PROXY unreachable (%s): %s — Telegram bot/user channels will fail",
            safe,
            exc,
        )
