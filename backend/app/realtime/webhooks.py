from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models import OutboundWebhook, WebhookOutbox, WebhookOutboxStatus, utcnow

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_MAX_ATTEMPTS = 8
_BACKOFF_SEC = (5, 15, 45, 120, 300, 900, 1800, 3600)
_SENT_KEEP_DAYS = 7
_DEAD_KEEP_DAYS = 30
_PRUNE_EVERY_TICKS = 40


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


def _should_retry_status(status_code: int) -> bool:
    return status_code >= 500 or status_code == 429


def _next_attempt_at(attempts_after_fail: int) -> datetime:
    idx = min(max(attempts_after_fail - 1, 0), len(_BACKOFF_SEC) - 1)
    return utcnow() + timedelta(seconds=_BACKOFF_SEC[idx])


async def enqueue_webhook_event(event_type: str, payload: dict[str, Any]) -> int:
    """Persist one outbox row per subscribed active webhook. Returns enqueued count."""
    body = {
        "type": event_type,
        "payload": payload,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    body_json = json.dumps(body, ensure_ascii=False, default=str)
    enqueued = 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(OutboundWebhook).where(OutboundWebhook.active.is_(True))
        )
        rows = list(result.scalars().all())
        now = utcnow()
        for row in rows:
            try:
                events = json.loads(row.events_json or "[]")
            except json.JSONDecodeError:
                continue
            if not isinstance(events, list) or event_type not in events:
                continue
            session.add(
                WebhookOutbox(
                    webhook_id=row.id,
                    event_type=event_type,
                    body_json=body_json,
                    status=WebhookOutboxStatus.PENDING.value,
                    attempts=0,
                    next_attempt_at=now,
                )
            )
            enqueued += 1
        if enqueued:
            await session.commit()
    return enqueued


async def dispatch_webhook_event(event_type: str, payload: dict[str, Any]) -> None:
    """Enqueue durable deliveries (worker performs HTTP)."""
    try:
        n = await enqueue_webhook_event(event_type, payload)
        if n:
            logger.debug("Webhook outbox enqueued %s for %s", n, event_type)
    except Exception:
        logger.exception("Failed to enqueue webhook event %s", event_type)


async def _http_deliver(
    *,
    delivery_id: int,
    event_type: str,
    url: str,
    secret: str | None,
    body_json: str,
) -> None:
    raw = body_json.encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-SkySender-Event": event_type,
        "X-SkySender-Delivery": str(delivery_id),
    }
    if secret:
        sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-SkySender-Signature"] = f"sha256={sig}"
    response = await _http_client().post(url, content=raw, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}")


class WebhookOutboxWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._idle_ticks = 0

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._idle_ticks = 0
        self._task = asyncio.create_task(self._run(), name="webhook-outbox-worker")
        logger.info("Webhook outbox worker started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Webhook outbox worker stopped")

    async def recover_stale_sending(self) -> int:
        async with SessionLocal() as session:
            result = await session.execute(
                update(WebhookOutbox)
                .where(WebhookOutbox.status == WebhookOutboxStatus.SENDING.value)
                .values(
                    status=WebhookOutboxStatus.PENDING.value,
                    next_attempt_at=utcnow(),
                )
                .returning(WebhookOutbox.id)
            )
            ids = list(result.scalars().all())
            await session.commit()
            if ids:
                logger.warning("Recovered %s stale webhook outbox rows from SENDING", len(ids))
            return len(ids)

    async def prune_old_rows(self) -> int:
        """Drop delivered/dead rows past retention to keep the table small."""
        now = utcnow()
        async with SessionLocal() as session:
            sent_cut = now - timedelta(days=_SENT_KEEP_DAYS)
            dead_cut = now - timedelta(days=_DEAD_KEEP_DAYS)
            result = await session.execute(
                delete(WebhookOutbox).where(
                    (
                        (WebhookOutbox.status == WebhookOutboxStatus.SENT.value)
                        & (WebhookOutbox.created_at < sent_cut)
                    )
                    | (
                        (WebhookOutbox.status == WebhookOutboxStatus.DEAD.value)
                        & (WebhookOutbox.created_at < dead_cut)
                    )
                )
            )
            await session.commit()
            removed = int(result.rowcount or 0)
            if removed:
                logger.info("Pruned %s old webhook outbox rows", removed)
            return removed

    async def _run(self) -> None:
        try:
            await self.recover_stale_sending()
        except Exception:
            logger.exception("Failed to recover stale webhook outbox rows")
        while not self._stop.is_set():
            try:
                did = await self._tick()
                if not did:
                    self._idle_ticks += 1
                    if self._idle_ticks >= _PRUNE_EVERY_TICKS:
                        self._idle_ticks = 0
                        try:
                            await self.prune_old_rows()
                        except Exception:
                            logger.exception("Webhook outbox prune failed")
                    await asyncio.sleep(1.5)
                else:
                    self._idle_ticks = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Webhook outbox worker loop error")
                await asyncio.sleep(3)

    async def _tick(self) -> bool:
        async with SessionLocal() as session:
            now = utcnow()
            row = (
                await session.execute(
                    select(WebhookOutbox)
                    .options(selectinload(WebhookOutbox.webhook))
                    .where(
                        WebhookOutbox.status == WebhookOutboxStatus.PENDING.value,
                        WebhookOutbox.next_attempt_at <= now,
                    )
                    .order_by(WebhookOutbox.id.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if row is None:
                return False

            webhook = row.webhook
            row.status = WebhookOutboxStatus.SENDING.value
            row.attempts = int(row.attempts or 0) + 1
            await session.commit()

            row_id = row.id
            attempt = row.attempts
            event_type = row.event_type
            webhook_id = row.webhook_id
            body_json = row.body_json
            url = webhook.url if webhook else ""
            secret = webhook.secret if webhook else None
            active = bool(webhook and webhook.active)

        if not active or not url:
            async with SessionLocal() as session:
                item = await session.get(WebhookOutbox, row_id)
                if item is not None:
                    item.status = WebhookOutboxStatus.DEAD.value
                    item.last_error = "Webhook missing or inactive"
                    await session.commit()
            return True

        try:
            await _http_deliver(
                delivery_id=row_id,
                event_type=event_type,
                url=url,
                secret=secret,
                body_json=body_json,
            )
        except Exception as exc:
            async with SessionLocal() as session:
                item = await session.get(WebhookOutbox, row_id)
                if item is None:
                    return True
                err = str(exc)[:2000]
                status_code = None
                if err.startswith("HTTP "):
                    try:
                        status_code = int(err.split()[1])
                    except (IndexError, ValueError):
                        status_code = None
                retryable = status_code is None or _should_retry_status(status_code)
                if (not retryable) or attempt >= _MAX_ATTEMPTS:
                    item.status = WebhookOutboxStatus.DEAD.value
                    item.last_error = err
                    logger.warning(
                        "Webhook outbox %s dead webhook=%s attempts=%s: %s",
                        row_id,
                        webhook_id,
                        attempt,
                        err,
                    )
                else:
                    item.status = WebhookOutboxStatus.PENDING.value
                    item.last_error = err
                    item.next_attempt_at = _next_attempt_at(attempt)
                    logger.warning(
                        "Webhook outbox %s retry webhook=%s attempt=%s next=%s: %s",
                        row_id,
                        webhook_id,
                        attempt,
                        item.next_attempt_at.isoformat(),
                        err,
                    )
                await session.commit()
            return True

        async with SessionLocal() as session:
            item = await session.get(WebhookOutbox, row_id)
            if item is not None:
                item.status = WebhookOutboxStatus.SENT.value
                item.last_error = None
                await session.commit()
        return True


worker = WebhookOutboxWorker()
