from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymax import QrAuthFlow, WebClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.base import IntegrationError
from app.integrations.max_personal.auth_qr import BridgePasswordProvider, BridgeQrHandler
from app.integrations.max_personal.inbox import apply_read_mark, backfill_dialog_names, ingest_pymax_message
from app.models import Channel, ChannelStatus, ChannelTransport, Dialog, utcnow
from app.realtime.publish import (
    dialog_updated_event,
    emit_event,
    message_created_event,
    message_updated_event,
)
from app.security import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    channel_id: int
    status: str = "connecting"  # connecting | qr_pending | need_2fa | online | error
    qr_url: str | None = None
    hint: str | None = None
    error: str | None = None
    identity: str | None = None
    client: WebClient | None = None
    task: asyncio.Task | None = None
    qr_bridge: BridgeQrHandler = field(default_factory=BridgeQrHandler)
    password_bridge: BridgePasswordProvider = field(default_factory=BridgePasswordProvider)


class MaxPersonalRuntime:
    def __init__(self) -> None:
        self._states: dict[int, RuntimeState] = {}
        self._lock = asyncio.Lock()

    def get_state(self, channel_id: int) -> RuntimeState | None:
        return self._states.get(channel_id)

    def get_client(self, channel_id: int) -> WebClient | None:
        state = self._states.get(channel_id)
        if not state or state.status != "online" or state.client is None:
            return None
        # Task finished means the socket loop exited while status was left stale.
        if state.task is not None and state.task.done():
            return None
        return state.client

    async def start_qr_connect(self, channel_id: int) -> RuntimeState:
        async with self._lock:
            existing = self._states.get(channel_id)
            if existing and existing.task and not existing.task.done():
                return existing

            work_dir = Path(get_settings().max_personal_data_dir) / f"ch_{channel_id}"
            work_dir.mkdir(parents=True, exist_ok=True)
            # fresh QR: remove old session so PyMax asks for QR again
            session_file = work_dir / "web.db"
            if session_file.exists():
                session_file.unlink()

            state = RuntimeState(channel_id=channel_id, status="connecting")
            self._states[channel_id] = state
            state.task = asyncio.create_task(
                self._run_client(channel_id, work_dir, fresh=True),
                name=f"max-personal-{channel_id}",
            )

        # wait until QR is shown or error
        state = self._states[channel_id]
        try:
            await asyncio.wait_for(state.qr_bridge.shown.wait(), timeout=45)
            state.status = "qr_pending"
            state.qr_url = state.qr_bridge.qr_url
            await self._update_channel(
                channel_id,
                status=ChannelStatus.QR_PENDING.value,
                identity="ожидает скана QR",
            )
        except TimeoutError as exc:
            state.status = "error"
            state.error = "Timeout waiting for QR from Max"
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ERROR.value,
                last_error=state.error,
            )
            raise IntegrationError(state.error) from exc
        return state

    async def submit_2fa(self, channel_id: int, password: str) -> None:
        state = self._states.get(channel_id)
        if not state:
            raise IntegrationError("QR session not found")
        await state.password_bridge.submit(password)

    async def restore_online_channels(self) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Channel).where(
                    Channel.transport == ChannelTransport.MAX.value,
                    Channel.status == ChannelStatus.ONLINE.value,
                    Channel.credentials_enc.is_not(None),
                )
            )
            channels = list(result.scalars().all())

        for channel in channels:
            try:
                await self._restore_channel(channel.id)
            except Exception:
                logger.exception("Failed to restore max personal channel %s", channel.id)

    async def ensure_client(self, channel_id: int) -> WebClient:
        client = self.get_client(channel_id)
        if client:
            return client
        state = self._states.get(channel_id)
        if state and state.status == "online" and (state.task is None or state.task.done()):
            state.status = "error"
            state.client = None
        await self._restore_channel(channel_id)
        for _ in range(50):
            client = self.get_client(channel_id)
            if client:
                return client
            await asyncio.sleep(0.2)
        raise IntegrationError("MAX personal client is offline; reconnect channel")

    async def stop_all(self) -> None:
        tasks = []
        for state in list(self._states.values()):
            if state.client:
                tasks.append(asyncio.create_task(state.client.close()))
            if state.task and not state.task.done():
                state.task.cancel()
                tasks.append(state.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._states.clear()

    async def stop_channel(self, channel_id: int) -> None:
        """Disconnect a single personal channel (e.g. after DB delete)."""
        state = self._states.pop(channel_id, None)
        if state is None:
            return
        tasks = []
        if state.client:
            tasks.append(asyncio.create_task(state.client.close()))
        if state.task and not state.task.done():
            state.task.cancel()
            tasks.append(state.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("MAX personal channel %s stopped", channel_id)

    async def _restore_channel(self, channel_id: int) -> None:
        async with self._lock:
            existing = self._states.get(channel_id)
            if existing and existing.task and not existing.task.done():
                return
            meta = await self._load_session_meta(channel_id)
            if not meta:
                return
            work_dir = Path(meta["work_dir"])
            state = RuntimeState(channel_id=channel_id, status="connecting")
            self._states[channel_id] = state
            state.task = asyncio.create_task(
                self._run_client(
                    channel_id,
                    work_dir,
                    fresh=False,
                    session_name=meta.get("session_name", "web.db"),
                ),
                name=f"max-personal-restore-{channel_id}",
            )

    async def _mark_disconnected(self, channel_id: int, reason: str) -> None:
        state = self._states.get(channel_id)
        if state is None:
            return
        if state.status in {"qr_pending", "need_2fa", "connecting"}:
            return
        state.status = "error"
        state.error = reason
        state.client = None
        await self._update_channel(
            channel_id,
            status=ChannelStatus.ERROR.value,
            last_error=reason,
        )
        logger.warning("MAX personal channel %s disconnected: %s", channel_id, reason)
        # Soft reconnect with backoff (session still on disk).
        asyncio.create_task(
            self._reconnect_later(channel_id),
            name=f"max-personal-reconnect-{channel_id}",
        )

    async def _reconnect_later(self, channel_id: int) -> None:
        for delay in (2, 5, 15, 30):
            await asyncio.sleep(delay)
            if self._stop_requested(channel_id):
                return
            if self.get_client(channel_id):
                return
            try:
                await self._restore_channel(channel_id)
                for _ in range(25):
                    if self.get_client(channel_id):
                        return
                    await asyncio.sleep(0.2)
            except Exception:
                logger.exception("MAX personal reconnect failed channel=%s", channel_id)

    def _stop_requested(self, channel_id: int) -> bool:
        state = self._states.get(channel_id)
        return state is None

    async def _run_client(
        self,
        channel_id: int,
        work_dir: Path,
        *,
        fresh: bool,
        session_name: str = "web.db",
    ) -> None:
        state = self._states[channel_id]
        auth_flow = QrAuthFlow(
            qr_provider=state.qr_bridge,
            password_provider=state.password_bridge,
        )
        client = WebClient(
            work_dir=str(work_dir),
            session_name=session_name,
            auth_flow=auth_flow,
            qr_provider=state.qr_bridge,
        )
        state.client = client

        @client.on_start()
        async def on_start(c: WebClient) -> None:
            identity = "MAX аккаунт"
            external_id = None
            if c.me and c.me.contact:
                contact = c.me.contact
                external_id = str(getattr(contact, "id", None) or "")
                names = [
                    getattr(contact, "first_name", None) or getattr(contact, "names", None),
                    getattr(contact, "last_name", None),
                ]
                # User model fields may vary
                name = getattr(contact, "name", None) or getattr(contact, "first_name", None)
                username = getattr(contact, "username", None)
                phone = getattr(contact, "phone", None) or getattr(contact, "phone_number", None)
                identity = (
                    (f"@{username}" if username else None)
                    or (str(phone) if phone else None)
                    or (str(name) if name else None)
                    or f"id:{external_id}"
                )
            state.status = "online"
            state.identity = identity
            state.error = None
            creds = {
                "work_dir": str(work_dir),
                "session_name": session_name,
                "external_id": external_id,
            }
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ONLINE.value,
                identity=identity,
                external_id=external_id,
                credentials_enc=encrypt_secret(json.dumps(creds)),
                connected_at=utcnow(),
                last_error=None,
            )
            logger.info("MAX personal channel %s online as %s", channel_id, identity)
            try:
                async with SessionLocal() as session:
                    channel = await session.get(Channel, channel_id)
                    if channel is not None:
                        n = await backfill_dialog_names(session, channel=channel, client=c)
                        events: list[dict[str, Any]] = []
                        if n:
                            result = await session.execute(
                                select(Dialog)
                                .options(selectinload(Dialog.current_appeal))
                                .where(Dialog.channel_id == channel.id)
                            )
                            for dialog in result.scalars().all():
                                events.append(dialog_updated_event(dialog, channel.transport))
                        await session.commit()
                        if n:
                            logger.info("Backfilled %s dialog names for channel %s", n, channel_id)
                        for ev in events:
                            await emit_event(ev)
            except Exception:
                logger.exception("Dialog name backfill failed channel=%s", channel_id)

        @client.on_message()
        async def on_message(message: Any, c: WebClient) -> None:
            if message.chat_id is None:
                return
            my_id = None
            if c.me and c.me.contact:
                my_id = getattr(c.me.contact, "id", None)
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None:
                    return
                created = await ingest_pymax_message(
                    session,
                    channel=channel,
                    chat_id=int(message.chat_id),
                    message_id=getattr(message, "id", None),
                    sender_id=getattr(message, "sender", None),
                    text=getattr(message, "text", "") or "",
                    timestamp=getattr(message, "time", None),
                    my_user_id=int(my_id) if my_id is not None else None,
                    attaches=list(getattr(message, "attaches", None) or []),
                    client=c,
                    # prev_message_id is chronological previous message, NOT a reply quote.
                    reply_to_external_id=None,
                )
                event = None
                if created is not None:
                    result = await session.execute(
                        select(Dialog)
                        .options(selectinload(Dialog.current_appeal))
                        .where(Dialog.id == created.dialog_id)
                    )
                    dialog = result.scalar_one_or_none()
                    await session.refresh(created, attribute_names=["attachments"])
                    if dialog is not None:
                        event = message_created_event(dialog, created, channel.transport)
                await session.commit()
                if event is not None:
                    await emit_event(event)

        @client.on_message_read()
        async def on_message_read(event: Any, c: WebClient) -> None:
            chat_id = getattr(event, "chat_id", None)
            mark = getattr(event, "mark", None)
            if chat_id is None or mark is None:
                return
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None:
                    return
                updated = await apply_read_mark(
                    session,
                    channel=channel,
                    chat_id=int(chat_id),
                    mark=int(mark),
                    set_as_unread=bool(getattr(event, "set_as_unread", False)),
                )
                events: list[dict[str, Any]] = []
                if updated:
                    result = await session.execute(
                        select(Dialog)
                        .options(selectinload(Dialog.current_appeal))
                        .where(Dialog.id == updated[0].dialog_id)
                    )
                    dialog = result.scalar_one_or_none()
                    if dialog is not None:
                        for msg in updated:
                            events.append(
                                message_updated_event(dialog, msg, channel.transport)
                            )
                await session.commit()
                for ev in events:
                    await emit_event(ev)

        @client.on_typing()
        async def on_typing(event: Any, c: WebClient) -> None:
            chat_id = getattr(event, "chat_id", None)
            user_id = getattr(event, "user_id", None)
            if chat_id is None:
                return
            my_id = None
            if c.me and c.me.contact:
                my_id = getattr(c.me.contact, "id", None)
            if my_id is not None and user_id is not None and int(user_id) == int(my_id):
                return
            logger.info(
                "MAX personal typing channel=%s chat=%s user=%s",
                channel_id,
                chat_id,
                user_id,
            )
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None:
                    return
                result = await session.execute(
                    select(Dialog).where(
                        Dialog.channel_id == channel.id,
                        Dialog.external_chat_id == str(chat_id),
                    )
                )
                dialog = result.scalar_one_or_none()
                if dialog is None:
                    return
                payload = {
                    "type": "dialog.typing",
                    "dialog_id": dialog.id,
                    "channel_id": channel.id,
                    "department_id": dialog.department_id,
                    "user_id": user_id,
                }
            await emit_event(payload)

        @client.on_disconnect()
        async def on_disconnect(*_args: Any, **_kwargs: Any) -> None:
            await self._mark_disconnected(channel_id, "MAX personal socket disconnected")

        # watch for 2FA wait in parallel
        watch_task = asyncio.create_task(self._watch_2fa(channel_id))
        try:
            await client.start()
            # start() returned without exception — treat as unexpected disconnect.
            if state.status == "online":
                await self._mark_disconnected(channel_id, "MAX personal client loop ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.status = "error"
            state.error = str(exc)
            state.client = None
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ERROR.value,
                last_error=state.error,
            )
            logger.exception("MAX personal client failed channel=%s", channel_id)
            asyncio.create_task(
                self._reconnect_later(channel_id),
                name=f"max-personal-reconnect-{channel_id}",
            )
        finally:
            watch_task.cancel()
            await asyncio.gather(watch_task, return_exceptions=True)

    async def _watch_2fa(self, channel_id: int) -> None:
        state = self._states[channel_id]
        while True:
            await state.password_bridge.waiting.wait()
            state.status = "need_2fa"
            state.hint = state.password_bridge.hint
            await self._update_channel(
                channel_id,
                status=ChannelStatus.CONNECTING.value,
                last_error="Требуется пароль 2FA",
            )
            # wait until password submitted (waiting cleared)
            while state.password_bridge.waiting.is_set():
                await asyncio.sleep(0.2)

    async def _load_session_meta(self, channel_id: int) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            channel = await session.get(Channel, channel_id)
            if not channel or not channel.credentials_enc:
                return None
            try:
                return json.loads(decrypt_secret(channel.credentials_enc))
            except Exception:
                return None

    async def _update_channel(
        self,
        channel_id: int,
        *,
        status: str | None = None,
        identity: str | None = None,
        external_id: str | None = None,
        credentials_enc: str | None = None,
        connected_at: Any = None,
        last_error: str | None = ...,  # type: ignore[assignment]
    ) -> None:
        async with SessionLocal() as session:
            channel = await session.get(Channel, channel_id)
            if channel is None:
                return
            if status is not None:
                channel.status = status
            if identity is not None:
                channel.identity = identity
            if external_id is not None:
                channel.external_id = external_id
            if credentials_enc is not None:
                channel.credentials_enc = credentials_enc
            if connected_at is not None:
                channel.connected_at = connected_at
            if last_error is not ...:
                channel.last_error = last_error
            await session.commit()


runtime = MaxPersonalRuntime()
