"""Shared TELEGRAM_PROXY helpers for Bot API (httpx) and Telethon (MTProto)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import unquote, urlparse

from app.config import get_settings
from app.integrations.base import IntegrationError

logger = logging.getLogger(__name__)


def telegram_proxy_url() -> str | None:
    raw = (get_settings().telegram_proxy or "").strip()
    return raw or None


def httpx_proxy() -> str | None:
    """Return proxy URL for httpx.AsyncClient(proxy=...), or None."""
    return telegram_proxy_url()


def telethon_proxy() -> dict[str, Any] | None:
    """Parse TELEGRAM_PROXY into a Telethon proxy config."""
    raw = telegram_proxy_url()
    if not raw:
        return None

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise IntegrationError(
            "TELEGRAM_PROXY должен быть URL вида socks5://host:1080 или http://host:8080"
        )
    if scheme in {"socks5", "socks5h"}:
        proxy_type = "socks5"
    elif scheme in {"socks4", "socks4a"}:
        proxy_type = "socks4"
    elif scheme in {"http", "https"}:
        proxy_type = "http"
    else:
        raise IntegrationError(f"Неподдерживаемый TELEGRAM_PROXY scheme: {scheme}")

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


async def log_telegram_proxy_status() -> None:
    """Startup check: warn if proxy is set but unreachable, or log that it is active."""
    import httpx

    proxy = httpx_proxy()
    if not proxy:
        logger.info("TELEGRAM_PROXY not set — Bot/MTProto go direct")
        return

    # Redact credentials in logs
    safe = proxy
    try:
        p = urlparse(proxy)
        if p.password:
            safe = proxy.replace(p.password, "***")
    except Exception:
        safe = "(set)"

    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=12.0, follow_redirects=True) as client:
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
