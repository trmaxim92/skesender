from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.channel_events import record_channel_event
from app.db import SessionLocal
from app.integrations.credentials_cache import decrypt_cached
from app.integrations.media_jobs import schedule_media_job
from app.integrations.maxbot.client import MaxApiError, get_subscriptions, get_updates
from app.integrations.maxbot.inbox import backfill_maxbot_attachments, process_update
from app.models import Channel, ChannelStatus, ChannelTransport, Dialog
from app.realtime.publish import emit_event, message_created_event
from app.security import decrypt_secret

logger = logging.getLogger(__name__)

_POLL_CONCURRENCY = 8
_DIAG_IDLE_SEC = 300  # heartbeat into channel_events while idle


class MaxBotPoller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._sem = asyncio.Semaphore(_POLL_CONCURRENCY)
        self._last_diag: dict[int, float] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="maxbot-poller")
        logger.info("MAX bot long-poller started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("MAX bot long-poller stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_all_channels()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Poller loop error")
                await asyncio.sleep(3)

    async def _poll_all_channels(self) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Channel.id).where(
                    Channel.transport == ChannelTransport.MAXBOT.value,
                    Channel.status == ChannelStatus.ONLINE.value,
                    Channel.credentials_enc.is_not(None),
                )
            )
            channel_ids = list(result.scalars().all())

        if not channel_ids:
            await asyncio.sleep(5)
            return

        await asyncio.gather(*(self._poll_channel(cid) for cid in channel_ids))

    async def _poll_channel(self, channel_id: int) -> None:
        async with self._sem:
            await self._poll_channel_unlocked(channel_id)

    async def _maybe_diag(
        self,
        channel_id: int,
        *,
        kind: str,
        message: str,
        detail: str | None = None,
        level: str | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and (now - self._last_diag.get(channel_id, 0.0)) < _DIAG_IDLE_SEC:
            return
        self._last_diag[channel_id] = now
        await record_channel_event(
            channel_id, kind=kind, message=message, detail=detail, level=level
        )

    async def _poll_channel_unlocked(self, channel_id: int) -> None:
        try:
            token: str | None = None
            marker: int | None = None
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None or not channel.credentials_enc:
                    return
                try:
                    token = decrypt_cached(
                        channel_id, channel.credentials_enc, decrypt=decrypt_secret
                    )
                except ValueError as exc:
                    channel.status = ChannelStatus.ERROR.value
                    channel.last_error = str(exc)
                    await session.commit()
                    await record_channel_event(
                        channel_id,
                        kind="error",
                        message="Не удалось расшифровать токен",
                        detail=str(exc),
                        level="error",
                    )
                    return
                marker = channel.poll_marker

            assert token is not None
            try:
                payload = await get_updates(
                    token,
                    marker=marker,
                    timeout=25,
                    limit=100,
                    # No types filter: catch bot_started / message_created / etc.
                )
            except MaxApiError as exc:
                # Webhook may be blocking long-poll — surface that in diagnostics.
                hook_hint = ""
                try:
                    subs = await get_subscriptions(token)
                    if subs:
                        urls = [str(s.get("url") or "?") for s in subs]
                        hook_hint = (
                            " Активны webhook-подписки (long-poll отключён Max): "
                            + ", ".join(urls)
                        )
                except Exception:
                    pass
                async with SessionLocal() as session:
                    channel = await session.get(Channel, channel_id)
                    if channel is not None:
                        channel.last_error = str(exc) + hook_hint
                        await session.commit()
                logger.warning("Channel %s updates failed: %s%s", channel_id, exc, hook_hint)
                await record_channel_event(
                    channel_id,
                    kind="poll_error",
                    message=f"Ошибка long-poll: {exc}",
                    detail=hook_hint.strip() or None,
                    level="error",
                )
                await asyncio.sleep(2)
                return

            updates = payload.get("updates") or []
            new_marker = payload.get("marker")
            if not updates and new_marker is None:
                return

            events = []
            media_ids: list[int] = []
            processed = 0
            skipped = 0
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None:
                    return
                for update in updates:
                    if isinstance(update, dict):
                        msg = await process_update(
                            session, channel, update, download_media=False
                        )
                        if msg is not None:
                            processed += 1
                            if any(
                                not att.storage_path
                                for att in (msg.attachments or [])
                                if att.remote_url or att.provider_file_id
                            ):
                                media_ids.append(msg.id)
                            result = await session.execute(
                                select(Dialog)
                                .options(
                                    selectinload(Dialog.channel),
                                    selectinload(Dialog.current_appeal),
                                )
                                .where(Dialog.id == msg.dialog_id)
                            )
                            dialog = result.scalar_one_or_none()
                            await session.refresh(msg, attribute_names=["attachments"])
                            if dialog is not None:
                                events.append(
                                    message_created_event(dialog, msg, channel.transport)
                                )
                        else:
                            skipped += 1

                if new_marker is not None:
                    channel.poll_marker = int(new_marker)
                channel.last_error = None
                await session.commit()

            for event in events:
                await emit_event(event)

            for msg_id in media_ids:
                schedule_media_job(
                    backfill_maxbot_attachments(msg_id),
                    name=f"maxbot-media-{channel_id}-{msg_id}",
                )

            if updates:
                types = [
                    str(u.get("update_type") or u.get("updateType") or "?")
                    for u in updates
                    if isinstance(u, dict)
                ]
                logger.info(
                    "Channel %s poll: %s updates (processed=%s skipped=%s) marker=%s types=%s",
                    channel_id,
                    len(updates),
                    processed,
                    skipped,
                    new_marker,
                    ",".join(types[:12]),
                )
                await record_channel_event(
                    channel_id,
                    kind="poll_updates",
                    message=(
                        f"Получено {len(updates)} апдейт(ов), "
                        f"в CRM: {processed}, пропущено: {skipped}"
                    ),
                    detail=f"marker→{new_marker}; types={','.join(types[:20])}",
                    level="info",
                )
                self._last_diag[channel_id] = time.monotonic()
            else:
                await self._maybe_diag(
                    channel_id,
                    kind="poll_ok",
                    message=f"Long-poll OK, новых апдейтов нет (marker={new_marker})",
                    level="info",
                )
        except Exception:
            logger.exception("Channel %s poll failed", channel_id)
            await record_channel_event(
                channel_id,
                kind="poll_error",
                message="Сбой цикла long-poll",
                level="error",
            )
            await asyncio.sleep(2)


poller = MaxBotPoller()
