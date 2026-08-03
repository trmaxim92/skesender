from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telethon import TelegramClient, events
from telethon.errors import AuthKeyUnregisteredError, FloodWaitError, SessionPasswordNeededError
from telethon.tl import functions, types
from telethon.tl.custom.message import Message as TlMessage

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.base import IntegrationError
from app.integrations.max_personal.auth_qr import BridgePasswordProvider
from app.integrations.telegram_proxy import redact_proxy_url, telethon_proxy
from app.integrations.telegram_user.inbox import ingest_telethon_message
from app.models import Channel, ChannelStatus, ChannelTransport, Dialog, utcnow
from app.realtime.publish import emit_event, message_created_event
from app.security import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

_MTPROTO_FAIL_HINT = (
    "Не удалось подключиться к серверам Telegram (MTProto). "
    "HTTP Bot API может работать, а DC для личного аккаунта — нет (файрвол/провайдер). "
    "Задайте TELEGRAM_PROXY в backend/.env "
    "(EU SOCKS или локальный WARP: socks5://127.0.0.1:40000)."
)

_AUTH_KEY_HINT = (
    "Telegram принял вход, но сразу сбросил MTProto-ключ (AuthKeyUnregistered). "
    "Частая причина на RU-сервере — WARP с выходом в РФ (СПб): нужен EU SOCKS в TELEGRAM_PROXY. "
    "В Telegram: Настройки → Устройства — завершите сессии SkySender/trmaxim, "
    "затем подключите канал снова одним сканом QR."
)


def _wipe_session_files(work_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    for path in work_dir.glob("session*"):
        try:
            path.unlink()
        except OSError:
            logger.warning("Cannot remove telegram session file %s", path)


def _is_auth_key_error(exc: BaseException) -> bool:
    if isinstance(exc, AuthKeyUnregisteredError):
        return True
    text = str(exc).lower()
    return (
        "key is not registered" in text
        or "authkeyunregistered" in text
        or "ключ не зарегистрирован" in text
    )


@dataclass
class RuntimeState:
    channel_id: int
    status: str = "connecting"  # connecting | qr_pending | need_2fa | online | error
    qr_url: str | None = None
    hint: str | None = None
    error: str | None = None
    identity: str | None = None
    proxy_url: str | None = None
    client: TelegramClient | None = None
    task: asyncio.Task | None = None
    password_bridge: BridgePasswordProvider = field(default_factory=BridgePasswordProvider)
    qr_shown: asyncio.Event = field(default_factory=asyncio.Event)


class TelegramUserRuntime:
    def __init__(self) -> None:
        self._states: dict[int, RuntimeState] = {}
        self._lock = asyncio.Lock()

    def get_state(self, channel_id: int) -> RuntimeState | None:
        return self._states.get(channel_id)

    def get_client(self, channel_id: int) -> TelegramClient | None:
        state = self._states.get(channel_id)
        if state and state.status == "online" and state.client:
            return state.client
        return None

    async def start_qr_connect(
        self, channel_id: int, *, proxy: str | None = None
    ) -> RuntimeState:
        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise IntegrationError(
                "Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в .env (my.telegram.org)"
            )

        proxy_url = (proxy or "").strip() or None
        if proxy_url:
            # Validate early so UI gets a clear error before QR wait.
            telethon_proxy(proxy_url)

        async with self._lock:
            existing = self._states.get(channel_id)
            if existing and existing.task and not existing.task.done():
                if existing.status in {"qr_pending", "connecting", "need_2fa"} and existing.qr_url:
                    return existing
                # Stuck/error task — cancel and start clean.
                existing.task.cancel()
                try:
                    await existing.task
                except Exception:
                    pass
                self._states.pop(channel_id, None)

            work_dir = Path(settings.telegram_user_data_dir) / f"ch_{channel_id}"
            _wipe_session_files(work_dir)

            state = RuntimeState(
                channel_id=channel_id, status="connecting", proxy_url=proxy_url
            )
            self._states[channel_id] = state
            state.task = asyncio.create_task(
                self._run_client(channel_id, work_dir, fresh=True),
                name=f"telegram-user-{channel_id}",
            )

        state = self._states[channel_id]
        try:
            await asyncio.wait_for(state.qr_shown.wait(), timeout=45)
        except TimeoutError as exc:
            state.status = "error"
            detail = state.error or ""
            if "Connection" in detail or "failed" in detail.lower() or "TimeoutError" in detail:
                state.error = _MTPROTO_FAIL_HINT
            else:
                state.error = (
                    "Timeout waiting for Telegram QR. "
                    + _MTPROTO_FAIL_HINT
                )
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ERROR.value,
                last_error=state.error,
            )
            raise IntegrationError(state.error) from exc

        if not state.qr_url:
            state.status = "error"
            state.error = state.error or _MTPROTO_FAIL_HINT
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ERROR.value,
                last_error=state.error,
            )
            raise IntegrationError(state.error)

        state.status = "qr_pending"
        await self._update_channel(
            channel_id,
            status=ChannelStatus.QR_PENDING.value,
            identity="ожидает скана QR",
        )
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
                    Channel.transport == ChannelTransport.TGAPI.value,
                    Channel.status == ChannelStatus.ONLINE.value,
                    Channel.credentials_enc.is_not(None),
                )
            )
            channels = list(result.scalars().all())

        for channel in channels:
            try:
                await self._restore_channel(channel.id)
            except Exception:
                logger.exception("Failed to restore telegram user channel %s", channel.id)

    async def ensure_client(self, channel_id: int) -> TelegramClient:
        client = self.get_client(channel_id)
        if client and client.is_connected():
            return client
        await self._restore_channel(channel_id)
        for _ in range(50):
            client = self.get_client(channel_id)
            if client and client.is_connected():
                return client
            await asyncio.sleep(0.2)
        raise IntegrationError("Telegram personal client is offline; reconnect channel")

    async def stop_all(self) -> None:
        tasks = []
        for state in list(self._states.values()):
            if state.client:
                tasks.append(asyncio.create_task(state.client.disconnect()))
            if state.task and not state.task.done():
                state.task.cancel()
                tasks.append(state.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._states.clear()

    async def stop_channel(self, channel_id: int) -> None:
        """Disconnect a single Telegram user channel (e.g. after DB delete)."""
        state = self._states.pop(channel_id, None)
        if state is None:
            return
        pending: list[Any] = []
        if state.client:
            pending.append(asyncio.ensure_future(state.client.disconnect()))
        if state.task and not state.task.done():
            state.task.cancel()
            pending.append(state.task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("Telegram user channel %s stopped", channel_id)

    async def _restore_channel(self, channel_id: int) -> None:
        async with self._lock:
            existing = self._states.get(channel_id)
            if existing and existing.task and not existing.task.done():
                return
            meta = await self._load_session_meta(channel_id)
            if not meta:
                return
            work_dir = Path(meta["work_dir"])
            proxy_url = (meta.get("proxy") or "").strip() or None
            state = RuntimeState(
                channel_id=channel_id, status="connecting", proxy_url=proxy_url
            )
            self._states[channel_id] = state
            state.task = asyncio.create_task(
                self._run_client(channel_id, work_dir, fresh=False),
                name=f"telegram-user-restore-{channel_id}",
            )

    async def _run_client(self, channel_id: int, work_dir: Path, *, fresh: bool) -> None:
        settings = get_settings()
        state = self._states[channel_id]
        session_path = str(work_dir / "session")
        if not state.proxy_url and not fresh:
            meta = await self._load_session_meta(channel_id)
            if meta and meta.get("proxy"):
                state.proxy_url = str(meta["proxy"]).strip() or None
        proxy_cfg = None
        try:
            proxy_cfg = telethon_proxy(state.proxy_url)
        except IntegrationError as exc:
            state.status = "error"
            state.error = str(exc)
            state.qr_shown.set()
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ERROR.value,
                last_error=state.error,
            )
            return

        client_kwargs: dict[str, Any] = {
            # Raise FloodWaitError to our QR loop instead of burning internal retries.
            "request_retries": 5,
            "connection_retries": 10,
            "retry_delay": 2,
            "flood_sleep_threshold": 0,
            "use_ipv6": False,
            "device_model": "SkySender",
            "system_version": "Linux",
            "app_version": "1.0",
            "lang_code": "ru",
            "system_lang_code": "ru",
        }
        if proxy_cfg is not None:
            client_kwargs["proxy"] = proxy_cfg.proxy
            if proxy_cfg.connection is not None:
                client_kwargs["connection"] = proxy_cfg.connection
            logger.info(
                "Telegram user channel=%s using proxy type=%s source=%s",
                channel_id,
                proxy_cfg.kind,
                redact_proxy_url(state.proxy_url) if state.proxy_url else "env",
            )

        client = TelegramClient(
            session_path,
            settings.telegram_api_id,
            settings.telegram_api_hash,
            **client_kwargs,
        )
        state.client = client

        @client.on(events.NewMessage)
        async def on_new_message(event: events.NewMessage.Event) -> None:
            message: TlMessage = event.message
            if message is None:
                return
            async with SessionLocal() as session:
                channel = await session.get(Channel, channel_id)
                if channel is None:
                    return
                me = await client.get_me()
                my_id = int(me.id) if me else None
                created = await ingest_telethon_message(
                    session,
                    channel=channel,
                    client=client,
                    message=message,
                    my_user_id=my_id,
                )
                event_payload = None
                if created is not None:
                    result = await session.execute(
                        select(Dialog)
                        .options(selectinload(Dialog.current_appeal))
                        .where(Dialog.id == created.dialog_id)
                    )
                    dialog = result.scalar_one_or_none()
                    await session.refresh(created, attribute_names=["attachments"])
                    if dialog is not None:
                        event_payload = message_created_event(dialog, created, channel.transport)
                await session.commit()
                if event_payload is not None:
                    await emit_event(event_payload)

        try:
            await client.connect()
            if fresh or not await client.is_user_authorized():
                await self._qr_login(channel_id, client)
            await self._stabilize_authorized_session(client)
            await self._mark_online(channel_id, client, work_dir)
            # Keep client alive until cancelled
            await client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not "recover" on AuthKeyUnregistered — local session flag lies.
            if _is_auth_key_error(exc):
                _wipe_session_files(work_dir)
                state.status = "error"
                state.error = _AUTH_KEY_HINT
                state.qr_shown.set()
                await self._update_channel(
                    channel_id,
                    status=ChannelStatus.ERROR.value,
                    last_error=state.error,
                )
                logger.exception("Telegram auth key unregistered channel=%s", channel_id)
                return

            recovery_exc: BaseException | None = None
            try:
                if client.is_connected() and await client.is_user_authorized():
                    await self._stabilize_authorized_session(client)
                    logger.warning(
                        "Telegram user channel=%s recovered authorized session after error: %s",
                        channel_id,
                        exc,
                    )
                    await self._mark_online(channel_id, client, work_dir)
                    await client.run_until_disconnected()
                    return
            except Exception as recover_fail:
                recovery_exc = recover_fail
                logger.exception(
                    "Telegram user channel=%s recovery check failed", channel_id
                )
            state.status = "error"
            if _is_auth_key_error(exc) or (
                recovery_exc is not None and _is_auth_key_error(recovery_exc)
            ):
                _wipe_session_files(work_dir)
                state.error = _AUTH_KEY_HINT
            else:
                err = str(exc)
                if "Connection" in err or "failed" in err.lower():
                    state.error = _MTPROTO_FAIL_HINT
                else:
                    state.error = err
            state.qr_shown.set()
            await self._update_channel(
                channel_id,
                status=ChannelStatus.ERROR.value,
                last_error=state.error,
            )
            logger.exception("Telegram user client failed channel=%s", channel_id)
        finally:
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception:
                pass

    async def _stabilize_authorized_session(self, client: TelegramClient) -> None:
        """Reconnect and verify get_me after QR — avoids stale AuthKeyUnregistered."""
        me = await self._reconnect_until_authorized(client)
        logger.info("Telegram session stabilized as id=%s", getattr(me, "id", None))

    async def _reconnect_until_authorized(
        self, client: TelegramClient, *, attempts: int = 7
    ) -> Any:
        """After CheckPassword/QR, GetState often 401s once under WARP; retry on fresh TCP."""
        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(min(0.5 * attempt, 2.5))
            await client.connect()
            try:
                me = await client.get_me()
                if me is not None:
                    client._authorized = True  # type: ignore[attr-defined]
                    return me
                last_exc = IntegrationError("get_me returned empty after login")
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Telegram authorize reconnect attempt=%s/%s: %s",
                    attempt,
                    attempts,
                    exc,
                )
                if not _is_auth_key_error(exc):
                    raise
        raise IntegrationError(_AUTH_KEY_HINT) from last_exc

    async def _finalize_authorization(
        self, client: TelegramClient, user: Any | None = None
    ) -> None:
        """Run Telethon _on_login when possible; recover if GetState immediately 401s."""
        if user is not None:
            try:
                await client._on_login(user)
                return
            except Exception as exc:
                if not _is_auth_key_error(exc):
                    raise
                logger.warning(
                    "Telegram _on_login GetState failed after auth; reconnecting: %s",
                    exc,
                )
                try:
                    client._mb_entity_cache.set_self_user(
                        user.id, user.bot, user.access_hash
                    )
                    client._authorized = True  # type: ignore[attr-defined]
                    client.session.save()
                except Exception:
                    logger.exception("Failed to persist Telegram user after partial login")
        await self._reconnect_until_authorized(client)

    async def _complete_qr_2fa(self, client: TelegramClient, password: str) -> None:
        """Finish QR login when ExportLoginToken raised SessionPasswordNeededError."""
        from telethon.password import compute_check

        pwd = await client(functions.account.GetPasswordRequest())
        result = await client(
            functions.auth.CheckPasswordRequest(compute_check(pwd, password))
        )
        settings = get_settings()
        export_req = functions.auth.ExportLoginTokenRequest(
            settings.telegram_api_id,
            settings.telegram_api_hash,
            [],
        )
        # After 2FA, Telegram may still need a successful LoginToken export/import.
        try:
            resp = await client(export_req)
            if isinstance(resp, types.auth.LoginTokenMigrateTo):
                await client._switch_dc(resp.dc_id)
                resp = await client(
                    functions.auth.ImportLoginTokenRequest(resp.token)
                )
            if isinstance(resp, types.auth.LoginTokenSuccess):
                await self._finalize_authorization(client, resp.authorization.user)
                return
            logger.info(
                "Post-2FA ExportLoginToken returned %s — using CheckPassword user",
                type(resp).__name__,
            )
        except SessionPasswordNeededError:
            logger.info("Post-2FA ExportLoginToken still wants password; using CheckPassword user")
        except Exception as exc:
            if _is_auth_key_error(exc):
                logger.warning("Post-2FA ExportLoginToken auth-key error: %s", exc)
            else:
                logger.warning("Post-2FA ExportLoginToken failed: %s", exc)

        await self._finalize_authorization(client, getattr(result, "user", None))

    async def _qr_login(self, channel_id: int, client: TelegramClient) -> None:
        """QR login with flood-tolerant finalize.

        Under proxy/flood limits ``ExportLoginToken`` after a scan often returns a
        fresh ``LoginToken`` instead of ``LoginTokenSuccess``. Keep refreshing the
        QR for another scan instead of failing the channel.
        """
        import base64
        import datetime as dt

        state = self._states[channel_id]
        settings = get_settings()
        export_req = functions.auth.ExportLoginTokenRequest(
            settings.telegram_api_id,
            settings.telegram_api_hash,
            [],
        )

        async def _export_token() -> Any:
            while True:
                try:
                    return await client(export_req)
                except FloodWaitError as exc:
                    wait_s = max(int(exc.seconds) + 1, 3)
                    logger.warning(
                        "Telegram ExportLoginToken flood wait %ss channel=%s",
                        wait_s,
                        channel_id,
                    )
                    await asyncio.sleep(wait_s)

        def _token_url(token: bytes) -> str:
            return "tg://login?token={}".format(
                base64.urlsafe_b64encode(token).decode("utf-8").rstrip("=")
            )

        async def _session_really_authorized() -> bool:
            """is_user_authorized() can be true after _on_login while GetState still 401s."""
            try:
                if not await client.is_user_authorized():
                    return False
                me = await client.get_me()
                return me is not None
            except Exception as exc:
                if _is_auth_key_error(exc):
                    client._authorized = False  # type: ignore[attr-defined]
                    logger.warning(
                        "Telegram session looked authorized but key unregistered channel=%s",
                        channel_id,
                    )
                    return False
                raise

        async def _accept_login(authorization_user: Any) -> None:
            await self._finalize_authorization(client, authorization_user)
            if not await _session_really_authorized():
                raise IntegrationError(_AUTH_KEY_HINT)

        resp = await _export_token()
        if not isinstance(resp, types.auth.LoginToken):
            raise IntegrationError(
                f"Unexpected initial QR response: {type(resp).__name__}"
            )

        state.qr_url = _token_url(resp.token)
        state.qr_shown.set()
        state.status = "qr_pending"
        logger.info("Telegram QR ready for channel %s", channel_id)

        scanned = asyncio.Event()

        async def _on_login_token(_update: Any) -> None:
            scanned.set()

        client.add_event_handler(_on_login_token, events.Raw(types.UpdateLoginToken))
        try:
            while True:
                if await _session_really_authorized():
                    return

                expires = getattr(resp, "expires", None)
                if isinstance(expires, dt.datetime):
                    timeout = max(
                        (expires - dt.datetime.now(tz=dt.timezone.utc)).total_seconds(),
                        1.0,
                    )
                else:
                    timeout = 30.0

                scanned.clear()
                try:
                    await asyncio.wait_for(scanned.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    resp = await _export_token()
                    if isinstance(resp, types.auth.LoginTokenSuccess):
                        await _accept_login(resp.authorization.user)
                        return
                    if isinstance(resp, types.auth.LoginTokenMigrateTo):
                        await client._switch_dc(resp.dc_id)
                        imported = await client(
                            functions.auth.ImportLoginTokenRequest(resp.token)
                        )
                        if isinstance(imported, types.auth.LoginTokenSuccess):
                            await _accept_login(imported.authorization.user)
                            return
                        raise IntegrationError(
                            f"QR DC migrate failed: {type(imported).__name__}"
                        )
                    if isinstance(resp, types.auth.LoginToken):
                        state.qr_url = _token_url(resp.token)
                        state.status = "qr_pending"
                        state.hint = ""
                        logger.info("Telegram QR refreshed channel=%s", channel_id)
                        continue
                    raise IntegrationError(
                        f"Unexpected QR refresh response: {type(resp).__name__}"
                    )

                # Phone scanned — pause then finalize (avoid immediate flood).
                await asyncio.sleep(1.5)
                got_fresh_token = False
                for attempt in range(1, 20):
                    if await _session_really_authorized():
                        return
                    resp = await _export_token()

                    if isinstance(resp, types.auth.LoginTokenMigrateTo):
                        await client._switch_dc(resp.dc_id)
                        resp = await client(
                            functions.auth.ImportLoginTokenRequest(resp.token)
                        )

                    if isinstance(resp, types.auth.LoginTokenSuccess):
                        await _accept_login(resp.authorization.user)
                        return

                    if isinstance(resp, types.auth.LoginToken):
                        state.qr_url = _token_url(resp.token)
                        state.status = "qr_pending"
                        state.hint = "QR обновлён — отсканируйте ещё раз"
                        logger.warning(
                            "QR finalize got LoginToken again channel=%s attempt=%s; "
                            "refreshed QR for rescan",
                            channel_id,
                            attempt,
                        )
                        got_fresh_token = True
                        break

                    logger.warning(
                        "QR finalize unexpected %s channel=%s attempt=%s",
                        type(resp).__name__,
                        channel_id,
                        attempt,
                    )
                    await asyncio.sleep(2)

                if got_fresh_token:
                    continue
                if await _session_really_authorized():
                    return
                raise IntegrationError(
                    "Не удалось завершить вход по QR после скана. "
                    "Подождите минуту и попробуйте снова."
                )
        except SessionPasswordNeededError:
            state.status = "need_2fa"
            state.hint = "Пароль двухфакторной аутентификации Telegram"
            await self._update_channel(
                channel_id,
                status=ChannelStatus.CONNECTING.value,
                last_error="Требуется пароль 2FA",
            )
            password = await state.password_bridge.get_password(state.hint)
            await self._complete_qr_2fa(client, password)
            if not await _session_really_authorized():
                raise IntegrationError(_AUTH_KEY_HINT)
        finally:
            client.remove_event_handler(
                _on_login_token, events.Raw(types.UpdateLoginToken)
            )

    async def _mark_online(self, channel_id: int, client: TelegramClient, work_dir: Path) -> None:
        state = self._states[channel_id]
        me = await client.get_me()
        external_id = str(me.id) if me else None
        username = getattr(me, "username", None) if me else None
        first = getattr(me, "first_name", None) if me else None
        phone = getattr(me, "phone", None) if me else None
        identity = (
            (f"@{username}" if username else None)
            or (str(phone) if phone else None)
            or (str(first) if first else None)
            or (f"id:{external_id}" if external_id else "Telegram")
        )
        creds = {
            "work_dir": str(work_dir),
            "session_name": "session",
            "external_id": external_id,
        }
        if state.proxy_url:
            creds["proxy"] = state.proxy_url
        state.status = "online"
        state.identity = identity
        state.error = None
        state.qr_url = None
        await self._update_channel(
            channel_id,
            status=ChannelStatus.ONLINE.value,
            identity=identity,
            external_id=external_id,
            credentials_enc=encrypt_secret(json.dumps(creds)),
            connected_at=utcnow(),
            last_error=None,
        )
        logger.info("Telegram personal channel %s online as %s", channel_id, identity)

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


runtime = TelegramUserRuntime()
