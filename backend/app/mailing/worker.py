from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import or_, select, update
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.mailing.crm_write import write_mailing_to_crm
from app.mailing.errors import MailingErrorKind, classify_mailing_error
from app.mailing.senders import send_mailing
from app.mailing.template_render import render_mailing_body
from app.mailing.throttle import (
    channel_under_caps,
    fail_rate_should_pause,
    in_quiet_hours,
    jittered_delay,
)
from app.models import (
    Channel,
    ChannelStatus,
    MailingCampaign,
    MailingCampaignChannel,
    MailingCampaignStatus,
    MailingRecipient,
    MailingRecipientStatus,
    MailingTemplate,
    utcnow,
)
from app.outbound_start import PeerResolveError, ResolvedPeer, resolve_outbound_peer
from app.storage.attachments import absolute_path

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
_PEER_FLOOD_QUARANTINE_SEC = 6 * 3600
_BAN_QUARANTINE_SEC = 12 * 3600
_AUTH_QUARANTINE_SEC = 24 * 3600


class MailingWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._rr_index: dict[int, int] = {}
        # channel_id → monotonic deadline (FloodWait / temporary)
        self._channel_backoff_until: dict[int, float] = {}

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
                    await self._sleep_interruptible(2.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Mailing worker loop error")
                await self._sleep_interruptible(3.0)

    async def _sleep_interruptible(
        self,
        seconds: float,
        *,
        campaign_id: int | None = None,
    ) -> bool:
        """Sleep in short slices. Returns False if stop/pause aborted early."""
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            if campaign_id is not None:
                async with SessionLocal() as session:
                    campaign = await session.get(MailingCampaign, campaign_id)
                    if campaign is None or campaign.status != MailingCampaignStatus.RUNNING.value:
                        return False
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.5, remaining))
        return True

    def _channel_in_memory_backoff(self, channel_id: int) -> bool:
        until = self._channel_backoff_until.get(channel_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._channel_backoff_until.pop(channel_id, None)
            return False
        return True

    def _set_channel_backoff(self, channel_id: int, seconds: int) -> None:
        seconds = max(1, int(seconds))
        until = time.monotonic() + seconds
        prev = self._channel_backoff_until.get(channel_id, 0)
        if until > prev:
            self._channel_backoff_until[channel_id] = until

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

    async def _link_for(
        self, session, campaign_id: int, channel_id: int
    ) -> MailingCampaignChannel | None:
        return (
            await session.execute(
                select(MailingCampaignChannel).where(
                    MailingCampaignChannel.campaign_id == campaign_id,
                    MailingCampaignChannel.channel_id == channel_id,
                )
            )
        ).scalar_one_or_none()

    async def _channel_mailing_ready(
        self,
        session,
        campaign: MailingCampaign,
        channel: Channel,
        *,
        now: datetime,
    ) -> tuple[bool, str | None]:
        if channel.status != ChannelStatus.ONLINE.value or not channel.credentials_enc:
            return False, "Канал offline"
        if self._channel_in_memory_backoff(channel.id):
            return False, "Backoff FloodWait"
        link = await self._link_for(session, campaign.id, channel.id)
        if link and link.paused_until and link.paused_until > now:
            return False, link.pause_reason or "Аккаунт на паузе рассылки"
        ok, reason = await channel_under_caps(session, channel.id, campaign, now=now)
        if not ok:
            return False, reason
        return True, None

    async def _quarantine_channel(
        self,
        session,
        campaign: MailingCampaign,
        channel_id: int,
        *,
        seconds: int,
        reason: str,
        now: datetime,
        reassign: bool = True,
    ) -> None:
        self._set_channel_backoff(channel_id, min(seconds, 3600))
        link = await self._link_for(session, campaign.id, channel_id)
        if link is not None:
            link.paused_until = now + timedelta(seconds=seconds)
            link.pause_reason = reason[:2000]
        if not reassign:
            return
        channel_ids = [lnk.channel_id for lnk in campaign.channels]
        others = [cid for cid in channel_ids if cid != channel_id]
        if not others:
            return
        pending = list(
            (
                await session.execute(
                    select(MailingRecipient).where(
                        MailingRecipient.campaign_id == campaign.id,
                        MailingRecipient.status == MailingRecipientStatus.PENDING.value,
                        MailingRecipient.channel_id == channel_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        ready_others: list[int] = []
        for cid in others:
            ch = await session.get(Channel, cid)
            if ch is None:
                continue
            ok, _ = await self._channel_mailing_ready(session, campaign, ch, now=now)
            if ok:
                ready_others.append(cid)
        if not ready_others:
            return
        for idx, recipient in enumerate(pending):
            recipient.channel_id = ready_others[idx % len(ready_others)]

    async def _apply_fail_rate_if_needed(self, campaign: MailingCampaign) -> bool:
        if fail_rate_should_pause(
            campaign.sent or 0,
            campaign.failed or 0,
            int(getattr(campaign, "fail_pause_pct", 0) or 0),
        ):
            campaign.status = MailingCampaignStatus.FAILED.value
            campaign.finished_at = utcnow()
            logger.warning(
                "Mailing campaign %s failed by fail-rate sent=%s failed=%s pct=%s",
                campaign.id,
                campaign.sent,
                campaign.failed,
                campaign.fail_pause_pct,
            )
            return True
        return False

    def _peer_from_cache(self, recipient: MailingRecipient) -> ResolvedPeer | None:
        chat_id = (recipient.peer_chat_id or "").strip()
        if not chat_id:
            return None
        return ResolvedPeer(
            external_chat_id=chat_id,
            contact_external_id=recipient.peer_contact_id,
            contact_name=recipient.peer_name or recipient.raw or chat_id,
            contact_username=recipient.peer_username,
            contact_phone=(
                recipient.normalized if recipient.kind == "phone" else None
            ),
        )

    def _store_peer_cache(self, recipient: MailingRecipient, peer: ResolvedPeer) -> None:
        recipient.peer_chat_id = peer.external_chat_id
        recipient.peer_contact_id = peer.contact_external_id
        recipient.peer_name = (peer.contact_name or "")[:255] or None
        recipient.peer_username = peer.contact_username

    async def _process_one(self, campaign_id: int) -> bool:
        now = datetime.now(timezone.utc)
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

            if in_quiet_hours(now, campaign.quiet_start_hour, campaign.quiet_end_hour):
                return False

            recipient = (
                await session.execute(
                    select(MailingRecipient)
                    .where(
                        MailingRecipient.campaign_id == campaign.id,
                        MailingRecipient.status == MailingRecipientStatus.PENDING.value,
                        or_(
                            MailingRecipient.next_attempt_at.is_(None),
                            MailingRecipient.next_attempt_at <= now,
                        ),
                    )
                    .order_by(MailingRecipient.id.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()

            if recipient is None:
                # Still waiting on backoff timers?
                deferred = (
                    await session.execute(
                        select(MailingRecipient.id)
                        .where(
                            MailingRecipient.campaign_id == campaign.id,
                            MailingRecipient.status == MailingRecipientStatus.PENDING.value,
                            MailingRecipient.next_attempt_at.is_not(None),
                            MailingRecipient.next_attempt_at > now,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
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
                if deferred is not None or in_flight is not None:
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

            channel = None
            if recipient.channel_id and recipient.channel_id in channel_ids:
                assigned = await session.get(Channel, recipient.channel_id)
                if assigned:
                    ok, _ = await self._channel_mailing_ready(session, campaign, assigned, now=now)
                    if ok:
                        channel = assigned
            if channel is None:
                channel = await self._pick_online_channel(session, campaign, channel_ids, now=now)
            if channel is None:
                # All channels cooling / capped — defer sticky recipient briefly.
                recipient.next_attempt_at = now + timedelta(seconds=30)
                await session.commit()
                return False

            template = campaign.template
            media_bytes = self._load_media(template)
            body = render_mailing_body(template.body or "", recipient) if template else ""
            template_ns = SimpleNamespace(
                body=body,
                media_kind=template.media_kind if template else None,
                media_path=template.media_path if template else None,
                media_name=template.media_name if template else None,
                mime_type=template.mime_type if template else None,
            )

            peer = self._peer_from_cache(recipient)
            if peer is None:
                recipient_raw = (recipient.raw or recipient.normalized or "").strip()
                try:
                    peer = await resolve_outbound_peer(channel, recipient_raw, session)
                except PeerResolveError as exc:
                    classified = classify_mailing_error(exc.message)
                    handled = await self._handle_soft_error(
                        session,
                        campaign=campaign,
                        recipient=recipient,
                        channel=channel,
                        classified=classified,
                        now=now,
                    )
                    if handled:
                        return True
                    recipient.status = MailingRecipientStatus.FAILED.value
                    recipient.error = classified.message
                    recipient.channel_id = channel.id
                    campaign.failed = (campaign.failed or 0) + 1
                    await self._apply_fail_rate_if_needed(campaign)
                    await session.commit()
                    return True
                except Exception as exc:
                    classified = classify_mailing_error(str(exc), exc_name=type(exc).__name__)
                    handled = await self._handle_soft_error(
                        session,
                        campaign=campaign,
                        recipient=recipient,
                        channel=channel,
                        classified=classified,
                        now=now,
                    )
                    if handled:
                        return True
                    logger.exception("Mailing peer resolve failed recipient=%s", recipient.id)
                    recipient.status = MailingRecipientStatus.FAILED.value
                    recipient.error = f"Не удалось найти получателя: {exc}"[:2000]
                    recipient.channel_id = channel.id
                    campaign.failed = (campaign.failed or 0) + 1
                    await self._apply_fail_rate_if_needed(campaign)
                    await session.commit()
                    return True
                self._store_peer_cache(recipient, peer)

            channel_ns = SimpleNamespace(
                id=channel.id,
                transport=channel.transport,
                credentials_enc=channel.credentials_enc,
                external_id=channel.external_id,
            )
            recipient_id = recipient.id
            delay = jittered_delay(int(campaign.delay_sec or 15))
            assigned_channel_id = channel.id
            write_to_crm = bool(getattr(campaign, "write_to_crm", True))
            campaign_name = campaign.name
            peer_snapshot = peer

            # Re-check pause before network send.
            await session.refresh(campaign)
            if campaign.status != MailingCampaignStatus.RUNNING.value:
                await session.commit()
                return False

            recipient.status = MailingRecipientStatus.SENDING.value
            recipient.channel_id = assigned_channel_id
            recipient.attempts = int(recipient.attempts or 0) + 1
            recipient.next_attempt_at = None
            await session.commit()

        result = await send_mailing(
            channel_ns,  # type: ignore[arg-type]
            peer=peer_snapshot,
            template=template_ns,  # type: ignore[arg-type]
            media_bytes=media_bytes,
        )

        async with SessionLocal() as session:
            campaign = (
                await session.execute(
                    select(MailingCampaign)
                    .options(selectinload(MailingCampaign.channels))
                    .where(MailingCampaign.id == campaign_id)
                )
            ).scalar_one_or_none()
            recipient = await session.get(MailingRecipient, recipient_id)
            if campaign is None or recipient is None:
                return True

            # Campaign paused while we were sending — don't count as success path specially,
            # but still persist outcome.
            if result.ok:
                recipient.status = MailingRecipientStatus.SENT.value
                recipient.error = None
                recipient.sent_at = utcnow()
                recipient.channel_id = assigned_channel_id
                campaign.sent = (campaign.sent or 0) + 1
                if write_to_crm:
                    channel_row = await session.get(Channel, assigned_channel_id)
                    if channel_row is not None:
                        await write_mailing_to_crm(
                            session,
                            channel=channel_row,
                            peer=peer_snapshot,
                            text=body,
                            external_id=result.external_id,
                            campaign_name=campaign_name,
                        )
            else:
                classified = classify_mailing_error(result.error)
                handled = await self._handle_soft_error(
                    session,
                    campaign=campaign,
                    recipient=recipient,
                    channel_id=assigned_channel_id,
                    classified=classified,
                    now=datetime.now(timezone.utc),
                )
                if handled:
                    return True
                if int(recipient.attempts or 0) < _MAX_ATTEMPTS and classified.kind == MailingErrorKind.TRANSIENT:
                    recipient.status = MailingRecipientStatus.PENDING.value
                    recipient.channel_id = assigned_channel_id
                    recipient.error = classified.message
                    recipient.next_attempt_at = utcnow() + timedelta(
                        seconds=classified.wait_seconds or 60
                    )
                    await session.commit()
                    return True
                recipient.status = MailingRecipientStatus.FAILED.value
                recipient.error = classified.message
                campaign.failed = (campaign.failed or 0) + 1
                await self._apply_fail_rate_if_needed(campaign)

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

        await self._sleep_interruptible(delay, campaign_id=campaign_id)
        return True

    async def _handle_soft_error(
        self,
        session,
        *,
        campaign: MailingCampaign,
        recipient: MailingRecipient,
        classified,
        now: datetime,
        channel: Channel | None = None,
        channel_id: int | None = None,
    ) -> bool:
        """Return True if error was handled (recipient left pending / skipped) and committed."""
        cid = channel.id if channel is not None else channel_id
        if cid is None:
            return False

        if classified.kind == MailingErrorKind.FLOOD_WAIT:
            wait = classified.wait_seconds or 30
            self._set_channel_backoff(cid, wait)
            recipient.status = MailingRecipientStatus.PENDING.value
            recipient.channel_id = cid
            recipient.error = None
            recipient.next_attempt_at = now + timedelta(seconds=wait)
            await session.commit()
            logger.info(
                "Mailing FloodWait channel=%s wait=%ss recipient=%s (no global block)",
                cid,
                wait,
                recipient.id,
            )
            return True

        if classified.kind == MailingErrorKind.SLOW_MODE:
            wait = classified.wait_seconds or 30
            self._set_channel_backoff(cid, wait)
            recipient.status = MailingRecipientStatus.PENDING.value
            recipient.channel_id = cid
            recipient.next_attempt_at = now + timedelta(seconds=wait)
            await session.commit()
            return True

        if classified.kind == MailingErrorKind.PEER_FLOOD:
            await self._quarantine_channel(
                session,
                campaign,
                cid,
                seconds=_PEER_FLOOD_QUARANTINE_SEC,
                reason=classified.message,
                now=now,
                reassign=True,
            )
            recipient.status = MailingRecipientStatus.PENDING.value
            recipient.channel_id = None  # will re-pin to healthy account
            recipient.error = classified.message
            recipient.next_attempt_at = now + timedelta(seconds=60)
            await session.commit()
            return True

        if classified.kind in {MailingErrorKind.ACCOUNT_BAN, MailingErrorKind.AUTH_DEAD}:
            seconds = (
                _AUTH_QUARANTINE_SEC
                if classified.kind == MailingErrorKind.AUTH_DEAD
                else _BAN_QUARANTINE_SEC
            )
            await self._quarantine_channel(
                session,
                campaign,
                cid,
                seconds=seconds,
                reason=classified.message,
                now=now,
                reassign=True,
            )
            if classified.kind == MailingErrorKind.AUTH_DEAD:
                ch = channel or await session.get(Channel, cid)
                if ch is not None:
                    ch.status = ChannelStatus.OFFLINE.value
            recipient.status = MailingRecipientStatus.SKIPPED.value
            recipient.error = classified.message
            recipient.channel_id = cid
            campaign.failed = (campaign.failed or 0) + 1
            await self._apply_fail_rate_if_needed(campaign)
            await session.commit()
            return True

        return False

    async def _pick_online_channel(
        self,
        session,
        campaign: MailingCampaign,
        channel_ids: list[int],
        *,
        now: datetime,
    ) -> Channel | None:
        if not channel_ids:
            return None
        start = self._rr_index.get(campaign.id, 0)
        for offset in range(len(channel_ids)):
            cid = channel_ids[(start + offset) % len(channel_ids)]
            channel = await session.get(Channel, cid)
            if channel is None:
                continue
            ok, _ = await self._channel_mailing_ready(session, campaign, channel, now=now)
            if ok:
                self._rr_index[campaign.id] = start + offset + 1
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
