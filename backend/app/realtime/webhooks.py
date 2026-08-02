from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import OutboundWebhook

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=8.0)
    return _client


async def close_webhook_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def dispatch_webhook_event(event_type: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget HTTP POST to active outbound webhooks subscribed to event_type."""
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(OutboundWebhook).where(OutboundWebhook.active.is_(True))
            )
            rows = list(result.scalars().all())
    except Exception:
        logger.exception("Failed to load outbound webhooks")
        return

    body = {
        "type": event_type,
        "payload": payload,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    client = _http_client()

    for row in rows:
        try:
            events = json.loads(row.events_json or "[]")
        except json.JSONDecodeError:
            continue
        if event_type not in events:
            continue
        headers = {"Content-Type": "application/json", "X-SkySender-Event": event_type}
        if row.secret:
            sig = hmac.new(row.secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            headers["X-SkySender-Signature"] = f"sha256={sig}"
        try:
            response = await client.post(row.url, content=raw, headers=headers)
            if response.status_code >= 400:
                logger.warning(
                    "Webhook %s -> %s failed: %s",
                    row.id,
                    row.url,
                    response.status_code,
                )
        except Exception:
            logger.exception("Webhook %s delivery error url=%s", row.id, row.url)
