"""Shared TELEGRAM_PROXY helpers for Bot API (httpx) and Telethon (MTProto)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.config import get_settings
from app.integrations.base import IntegrationError

logger = logging.getLogger(__name__)

# host:port or host:port:user:pass (PROXYMANIA-style SOCKS)
_HOST_PORT_RE = re.compile(
    r"^(?P<host>[^:\s]+):(?P<port>\d{2,5})(?::(?P<user>[^:]*):(?P<password>.*))?$"
)
# mtproto:host:port:secret
_MTPROTO_BARE_RE = re.compile(
    r"^mtproto:(?P<host>[^:\s]+):(?P<port>\d{2,5}):(?P<secret>\S+)$",
    re.IGNORECASE,
)


@dataclass
class TelethonProxyConfig:
    """Ready-to-pass kwargs pieces for TelegramClient."""

    proxy: Any
    connection: Any | None = None
    kind: str = "socks5"


def telegram_proxy_url() -> str | None:
    raw = (get_settings().telegram_proxy or "").strip()
    return raw or None


def httpx_proxy() -> str | None:
    """Return proxy URL for httpx.AsyncClient(proxy=...), or None.

    MTProto / tg://proxy links are not usable by httpx — ignore them for Bot API.
    """
    raw = telegram_proxy_url()
    if not raw:
        return None
    if _is_mtproto_raw(raw):
        return None
    try:
        return normalize_proxy_url(raw)
    except IntegrationError:
        return raw if "://" in raw else None


def _is_mtproto_raw(text: str) -> bool:
    t = text.strip().lower()
    return (
        t.startswith("tg://proxy")
        or t.startswith("tg:proxy")
        or t.startswith("mtproto:")
        or t.startswith("mtproxy:")
    )


def normalize_proxy_url(raw: str) -> str:
    """Normalize user/env proxy string to a canonical form."""
    text = (raw or "").strip()
    if not text:
        raise IntegrationError("Прокси не задан")

    if _is_mtproto_raw(text):
        host, port, secret = parse_mtproto_endpoint(text)
        return f"tg://proxy?server={host}&port={port}&secret={secret}"

    if "://" in text:
        return text

    match = _HOST_PORT_RE.match(text)
    if not match:
        raise IntegrationError(
            "Прокси: socks5://user:pass@host:port, host:port:user:pass "
            "или tg://proxy?server=…&port=…&secret=…"
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


def parse_mtproto_endpoint(raw: str) -> tuple[str, int, str]:
    text = (raw or "").strip()
    bare = _MTPROTO_BARE_RE.match(text)
    if bare:
        return bare.group("host"), int(bare.group("port")), bare.group("secret")

    # Accept mtproto://host:port?secret=…
    if text.lower().startswith("mtproto://") or text.lower().startswith("mtproxy://"):
        parsed = urlparse(text)
        secret = (parse_qs(parsed.query).get("secret") or [None])[0]
        if not parsed.hostname or not parsed.port or not secret:
            raise IntegrationError(
                "MTProto: mtproto://host:port?secret=… или tg://proxy?server=…&port=…&secret=…"
            )
        return parsed.hostname, int(parsed.port), unquote(secret)

    # tg://proxy?server=&port=&secret=
    if text.lower().startswith("tg://") or text.lower().startswith("tg:"):
        parsed = urlparse(text.replace("tg:proxy", "tg://proxy", 1))
        qs = parse_qs(parsed.query)
        server = (qs.get("server") or [None])[0]
        port_s = (qs.get("port") or [None])[0]
        secret = (qs.get("secret") or [None])[0]
        if not server or not port_s or not secret:
            raise IntegrationError(
                "tg://proxy должен содержать server, port и secret"
            )
        return server, int(port_s), unquote(secret)

    raise IntegrationError("Не удалось разобрать MTProto-прокси")


def _prepare_faketls_secret(secret: str) -> str:
    """TelethonFakeTLS expects base64 without leading 7 / hex without ee."""
    s = secret.strip()
    if re.fullmatch(r"[0-9a-fA-F]+", s) and s.lower().startswith("ee"):
        return s[2:]
    if s.startswith("7") and not re.fullmatch(r"[0-9a-fA-F]+", s):
        return s[1:]
    return s


def parse_telethon_proxy(raw: str) -> TelethonProxyConfig:
    """Parse a proxy string into Telethon client proxy (+ optional connection)."""
    text = (raw or "").strip()
    if _is_mtproto_raw(text):
        host, port, secret = parse_mtproto_endpoint(text)
        try:
            import TelethonFakeTLS
        except ImportError as exc:
            raise IntegrationError(
                "Для tg://proxy (FakeTLS) нужен пакет TelethonFakeTLS"
            ) from exc
        prepared = _prepare_faketls_secret(secret)
        return TelethonProxyConfig(
            proxy=(host, port, prepared),
            connection=TelethonFakeTLS.ConnectionTcpMTProxyFakeTLS,
            kind="mtproto",
        )

    url = normalize_proxy_url(text)
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
    return TelethonProxyConfig(proxy=cfg, connection=None, kind=proxy_type)


def redact_proxy_url(raw: str) -> str:
    """Hide password/secret in logs."""
    text = (raw or "").strip()
    if not text:
        return "(set)"
    if "secret=" in text.lower():
        return re.sub(r"(secret=)[^&\s]+", r"\1***", text, flags=re.IGNORECASE)
    try:
        url = normalize_proxy_url(text)
        if url.lower().startswith("tg://"):
            return re.sub(r"(secret=)[^&\s]+", r"\1***", url, flags=re.IGNORECASE)
        parsed = urlparse(url)
        if not parsed.password:
            return url
        return url.replace(parsed.password, "***").replace(
            quote(unquote(parsed.password), safe=""), "***"
        )
    except Exception:
        return "(set)"


def telethon_proxy(override: str | None = None) -> TelethonProxyConfig | None:
    """Parse channel override or env TELEGRAM_PROXY for Telethon."""
    raw = (override or "").strip() or telegram_proxy_url()
    if not raw:
        return None
    # Env MTProto is fine for user channels; Bot API ignores via httpx_proxy().
    return parse_telethon_proxy(raw)


async def log_telegram_proxy_status() -> None:
    """Startup check: warn if proxy is set but unreachable, or log that it is active."""
    import httpx

    proxy = httpx_proxy()
    raw = telegram_proxy_url()
    if raw and _is_mtproto_raw(raw):
        logger.info(
            "TELEGRAM_PROXY is MTProto (%s) — used for Telegram · аккаунт only",
            redact_proxy_url(raw),
        )
        return
    if not proxy:
        logger.info(
            "TELEGRAM_PROXY not set — Bot/MTProto go direct (per-channel proxy still OK)"
        )
        return

    safe = redact_proxy_url(proxy)

    try:
        httpx_url = normalize_proxy_url(proxy)
        async with httpx.AsyncClient(
            proxy=httpx_url, timeout=12.0, follow_redirects=True
        ) as client:
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
