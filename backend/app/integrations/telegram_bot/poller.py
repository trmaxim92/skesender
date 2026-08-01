from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.integrations.telegram_bot.client import TelegramApiError, get_updates
from app.integrations.telegram_bot.inbox import process_update
from app.models import Channel, ChannelStatus, ChannelTransport, Dialog
from app.realtime.publish import emit_event, message_created_event, message_updated_event
from app.security import decrypt_secret

logger = logging.getLogger(__name__)


class TelegramBotPoller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="telegram-bot-poller")
        logger.info("Telegram bot long-poller started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Telegram bot long-poller stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_all_channels()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram poller loop error")
                await asyncio.sleep(3)

    async def _poll_all_channels(self) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Channel).where(
                    Channel.transport == ChannelTransport.TELEGRAM.value,
                    Channel.status == ChannelStatus.ONLINE.value,
                    Channel.credentials_enc.is_not(None),
                )
            )
            channels = list(result.scalars().all())

        if not channels:
            await asyncio.sleep(5)
            return

        await asyncio.gather(*(self._poll_channel(ch.id) for ch in channels))

    async def _poll_channel(self, channel_id: int) -> None:
        try:
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None or not channel.credentials_enc:
                    return
                try:
                    token = decrypt_secret(channel.credentials_enc)
                except ValueError as exc:
                    channel.status = ChannelStatus.ERROR.value
                    channel.last_error = str(exc)
                    await session.commit()
                    return

                offset = channel.poll_marker
                try:
                    updates = await get_updates(
                        token,
                        offset=offset,
                        timeout=25,
                        limit=100,
                        allowed_updates=["message", "edited_message"],
                    )
                except TelegramApiError as exc:
                    channel.last_error = str(exc)
                    await session.commit()
                    logger.warning("Telegram channel %s updates failed: %s", channel_id, exc)
                    await asyncio.sleep(2)
                    return

                events = []
                max_update_id: int | None = None
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)
                    msg = await process_update(session, channel, update)
                    if msg is not None:
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
                            if update.get("edited_message"):
                                events.append(
                                    message_updated_event(dialog, msg, channel.transport)
                                )
                            else:
                                events.append(
                                    message_created_event(dialog, msg, channel.transport)
                                )

                if max_update_id is not None:
                    channel.poll_marker = max_update_id + 1
                channel.last_error = None
                await session.commit()

            for event in events:
                await emit_event(event)
        except Exception:
            logger.exception("Telegram channel %s poll failed", channel_id)
            await asyncio.sleep(2)


poller = TelegramBotPoller()
