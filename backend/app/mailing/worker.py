from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.mailing.senders import send_mailing
from app.models import (
    Channel,
    ChannelStatus,
    MailingCampaign,
    MailingCampaignStatus,
    MailingRecipient,
    MailingRecipientStatus,
    MailingTemplate,
    utcnow,
)
from app.outbound_start import PeerResolveError, resolve_outbound_peer
from app.storage.attachments import absolute_path

logger = logging.getLogger(__name__)

_FLOOD_RE = re.compile(r"FloodWait:(\d+)", re.I)


class MailingWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._rr_index: dict[int, int] = {}

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="mailing-worker")
        logger.info("Mailing worker started")

    async def recover_stale_sending(self) -> int:
        """Return stuck SENDING rows to PENDING after crash/restart."""
        async with SessionLocal() as session:
            result = await session.execute(
                update(MailingRecipient)
                .where(MailingRecipient.status == MailingRecipientStatus.SENDING.value)
                .values(status=MailingRecipientStatus.PENDING.value)
                .returning(MailingRecipient.id)
            )
            ids = list(result.scalars().all())
            await session.commit()
            if ids:
                logger.warning("Recovered %s stale mailing recipients from SENDING", len(ids))
            return len(ids)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Mailing worker stopped")

    async def _run(self) -> None:
        try:
            await self.recover_stale_sending()
        except Exception:
            logger.exception("Failed to recover stale SENDING recipients")
        while not self._stop.is_set():
            try:
                did_work = await self._tick()
                if not did_work:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Mailing worker loop error")
                await asyncio.sleep(3)

    async def _tick(self) -> bool:
        async with SessionLocal() as session:
            campaign_ids = list(
                (
                    await session.execute(
                        select(MailingCampaign.id).where(
                            MailingCampaign.status == MailingCampaignStatus.RUNNING.value
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not campaign_ids:
            return False
        for campaign_id in campaign_ids:
            if await self._process_one(campaign_id):
                return True
        return False

    async def _process_one(self, campaign_id: int) -> bool:
        async with SessionLocal() as session:
            campaign = (
                await session.execute(
                    select(MailingCampaign)
                    .options(
                        selectinload(MailingCampaign.template),
                        selectinload(MailingCampaign.channels),
                    )
                    .where(MailingCampaign.id == campaign_id)
                )
            ).scalar_one_or_none()
            if campaign is None or campaign.status != MailingCampaignStatus.RUNNING.value:
                return False

            recipient = (
                await session.execute(
                    select(MailingRecipient)
                    .where(
                        MailingRecipient.campaign_id == campaign.id,
                        MailingRecipient.status == MailingRecipientStatus.PENDING.value,
                    )
                    .order_by(MailingRecipient.id.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()

            if recipient is None:
                in_flight = (
                    await session.execute(
                        select(MailingRecipient.id)
                        .where(
                            MailingRecipient.campaign_id == campaign.id,
                            MailingRecipient.status == MailingRecipientStatus.SENDING.value,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if in_flight is not None:
                    # Another worker tick / crash mid-send — do not false-complete.
                    return False
                remaining = (
                    await session.execute(
                        select(MailingRecipient.id)
                        .where(
                            MailingRecipient.campaign_id == campaign.id,
                            MailingRecipient.status.in_(
                                [
                                    MailingRecipientStatus.PENDING.value,
                                    MailingRecipientStatus.SENDING.value,
                                ]
                            ),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if remaining is None:
                    campaign.status = MailingCampaignStatus.COMPLETED.value
                    campaign.finished_at = utcnow()
                    await session.commit()
                return False

            channel_ids = [link.channel_id for link in campaign.channels]
            if not channel_ids:
                recipient.status = MailingRecipientStatus.FAILED.value
                recipient.error = "Нет каналов-отправителей"
                campaign.failed = (campaign.failed or 0) + 1
                await session.commit()
                return True

            # Один получатель → один аккаунт. Не шлём с нескольких.
            channel = None
            if recipient.channel_id and recipient.channel_id in channel_ids:
                assigned = await session.get(Channel, recipient.channel_id)
                if (
                    assigned
                    and assigned.status == ChannelStatus.ONLINE.value
                    and assigned.credentials_enc
                ):
                    channel = assigned
            if channel is None:
                channel = await self._pick_online_channel(session, campaign.id, channel_ids)
            if channel is None:
                recipient.status = MailingRecipientStatus.FAILED.value
                recipient.error = "Нет online каналов-отправителей"
                campaign.failed = (campaign.failed or 0) + 1
                await session.commit()
                return True

            template = campaign.template
            media_bytes = self._load_media(template)
            template_ns = SimpleNamespace(
                body=template.body or "",
                media_kind=template.media_kind,
                media_path=template.media_path,
                media_name=template.media_name,
                mime_type=template.mime_type,
            )

            recipient_raw = (recipient.raw or recipient.normalized or "").strip()
            try:
                peer = await resolve_outbound_peer(channel, recipient_raw, session)
            except PeerResolveError as exc:
                flood = _FLOOD_RE.search(exc.message or "")
                if flood:
                    recipient.status = MailingRecipientStatus.PENDING.value
                    recipient.channel_id = channel.id
                    recipient.error = None
                    await session.commit()
                    await asyncio.sleep(int(flood.group(1)))
                    return True
                recipient.status = MailingRecipientStatus.FAILED.value
                recipient.error = (exc.message or str(exc))[:2000]
                recipient.channel_id = channel.id
                campaign.failed = (campaign.failed or 0) + 1
                await session.commit()
                return True
            except Exception as exc:
                flood = _FLOOD_RE.search(str(exc))
                if flood or type(exc).__name__ == "FloodWaitError":
                    seconds = int(flood.group(1)) if flood else int(getattr(exc, "seconds", 30) or 30)
                    recipient.status = MailingRecipientStatus.PENDING.value
                    recipient.channel_id = channel.id
                    recipient.error = None
                    await session.commit()
                    await asyncio.sleep(seconds)
                    return True
                logger.exception("Mailing peer resolve failed recipient=%s", recipient.id)
                recipient.status = MailingRecipientStatus.FAILED.value
                recipient.error = f"Не удалось найти получателя: {exc}"[:2000]
                recipient.channel_id = channel.id
                campaign.failed = (campaign.failed or 0) + 1
                await session.commit()
                return True

            channel_ns = SimpleNamespace(
                id=channel.id,
                transport=channel.transport,
                credentials_enc=channel.credentials_enc,
                external_id=channel.external_id,
            )
            recipient_id = recipient.id
            delay = max(1, int(campaign.delay_sec or 5))
            assigned_channel_id = channel.id

            recipient.status = MailingRecipientStatus.SENDING.value
            recipient.channel_id = assigned_channel_id
            await session.commit()

        result = await send_mailing(
            channel_ns,  # type: ignore[arg-type]
            peer=peer,
            template=template_ns,  # type: ignore[arg-type]
            media_bytes=media_bytes,
        )

        async with SessionLocal() as session:
            campaign = await session.get(MailingCampaign, campaign_id)
            recipient = await session.get(MailingRecipient, recipient_id)
            if campaign is None or recipient is None:
                return True

            if result.ok:
                recipient.status = MailingRecipientStatus.SENT.value
                recipient.error = None
                recipient.sent_at = utcnow()
                recipient.channel_id = assigned_channel_id
                campaign.sent = (campaign.sent or 0) + 1
            else:
                flood = _FLOOD_RE.search(result.error or "")
                if flood:
                    # Сохраняем закрепление аккаунта — повтор только с него
                    recipient.status = MailingRecipientStatus.PENDING.value
                    recipient.channel_id = assigned_channel_id
                    recipient.error = None
                    await session.commit()
                    await asyncio.sleep(int(flood.group(1)))
                    return True
                recipient.status = MailingRecipientStatus.FAILED.value
                recipient.error = (result.error or "Ошибка отправки")[:2000]
                campaign.failed = (campaign.failed or 0) + 1

            pending = (
                await session.execute(
                    select(MailingRecipient.id)
                    .where(
                        MailingRecipient.campaign_id == campaign_id,
                        MailingRecipient.status.in_(
                            [
                                MailingRecipientStatus.PENDING.value,
                                MailingRecipientStatus.SENDING.value,
                            ]
                        ),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if pending is None and campaign.status == MailingCampaignStatus.RUNNING.value:
                campaign.status = MailingCampaignStatus.COMPLETED.value
                campaign.finished_at = utcnow()

            await session.commit()

        await asyncio.sleep(delay)
        return True

    async def _pick_online_channel(
        self, session, campaign_id: int, channel_ids: list[int]
    ) -> Channel | None:
        if not channel_ids:
            return None
        start = self._rr_index.get(campaign_id, 0)
        for offset in range(len(channel_ids)):
            cid = channel_ids[(start + offset) % len(channel_ids)]
            channel = await session.get(Channel, cid)
            if channel and channel.status == ChannelStatus.ONLINE.value and channel.credentials_enc:
                self._rr_index[campaign_id] = start + offset + 1
                return channel
        return None

    def _load_media(self, template: MailingTemplate | None) -> bytes | None:
        if not template or not template.media_path:
            return None
        try:
            path = absolute_path(template.media_path)
            if path.exists():
                return path.read_bytes()
        except Exception:
            logger.exception("Failed to load mailing media %s", template.media_path)
        return None


worker = MailingWorker()
