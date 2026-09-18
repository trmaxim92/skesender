from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.departments import ensure_default_department
from app.deps import get_current_user
from app.integrations.base import IntegrationError
from app.integrations.max_personal.runtime import runtime as max_runtime
from app.integrations.telegram_user.runtime import runtime as telegram_user_runtime
from app.integrations.registry import get_adapter
from app.models import Channel, ChannelEvent, ChannelStatus, ChannelTransport, Department, Dialog, User
from app.rbac import (
    ACTION_MANAGE_CHANNELS,
    ACTION_MANAGE_USERS,
    SECTION_APPEALS,
    SECTION_CHANNELS,
    SECTION_CHATS,
    SECTION_MAILING,
    accessible_channel_ids,
    ensure_channel_access,
    load_user_rbac,
    require_permission,
    user_can,
)
from app.schemas import (
    ChannelConnectResult,
    ChannelEventOut,
    ChannelOut,
    ChannelTestRequest,
    ChannelTestResult,
    ChannelUpdateRequest,
    MaxBotConnectRequest,
    MaxQr2FARequest,
    MaxQrStartRequest,
    MaxQrStartResponse,
    MaxQrStatusResponse,
    TelegramConnectRequest,
    WebchatConnectRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])


def _webchat_public_key(ch: Channel) -> str | None:
    if ch.transport != ChannelTransport.WEBCHAT.value:
        return None
    if ch.external_id:
        return ch.external_id
    if not ch.meta_json:
        return None
    try:
        import json

        meta = json.loads(ch.meta_json)
        key = meta.get("public_key")
        return str(key) if key else None
    except Exception:
        return None


def to_channel_out(ch: Channel) -> ChannelOut:
    dept = getattr(ch, "department", None)
    return ChannelOut(
        id=ch.id,
        name=ch.name,
        transport=ChannelTransport(ch.transport),
        status=ChannelStatus(ch.status),
        identity=ch.identity,
        external_id=ch.external_id,
        connected_at=ch.connected_at,
        last_error=ch.last_error,
        created_at=ch.created_at,
        has_credentials=bool(ch.credentials_enc),
        department_id=ch.department_id,
        department_name=dept.name if dept is not None else None,
        public_key=_webchat_public_key(ch),
    )


async def _resolve_department_id(
    db: AsyncSession, department_id: int | None
) -> int:
    if department_id is not None:
        dept = await db.get(Department, department_id)
        if dept is None or not dept.is_active:
            raise HTTPException(status_code=400, detail="Отдел не найден")
        return dept.id
    default = await ensure_default_department(db)
    return default.id


async def _load_channel(db: AsyncSession, channel_id: int) -> Channel | None:
    result = await db.execute(
        select(Channel)
        .options(selectinload(Channel.department))
        .where(Channel.id == channel_id)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChannelOut]:
    loaded = await load_user_rbac(db, user)
    # Read-only channel list for chats/appeals/filter/outbound — not the settings section.
    if not (
        user_can(loaded, SECTION_CHATS)
        or user_can(loaded, SECTION_APPEALS)
        or user_can(loaded, SECTION_MAILING)
        or user_can(loaded, SECTION_CHANNELS)
        or user_can(loaded, ACTION_MANAGE_USERS)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    stmt = (
        select(Channel)
        .options(selectinload(Channel.department))
        .order_by(Channel.id.desc())
    )
    ids = await accessible_channel_ids(loaded, db)
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Channel.id.in_(ids))
    result = await db.execute(stmt)
    return [to_channel_out(ch) for ch in result.scalars().all()]


@router.get("/events", response_model=list[ChannelEventOut])
async def list_channel_events(
    channel_id: int | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHANNELS)),
) -> list[ChannelEventOut]:
    """Diagnostics trail: disconnects, reconnects, errors."""
    limit = max(1, min(limit, 300))
    loaded = await load_user_rbac(db, user)
    ids = await accessible_channel_ids(loaded, db)

    stmt = (
        select(ChannelEvent, Channel)
        .join(Channel, Channel.id == ChannelEvent.channel_id)
        .order_by(ChannelEvent.created_at.desc(), ChannelEvent.id.desc())
        .limit(limit)
    )
    if channel_id is not None:
        if ids is not None and channel_id not in ids:
            raise HTTPException(status_code=403, detail="Нет доступа к каналу")
        stmt = stmt.where(ChannelEvent.channel_id == channel_id)
    elif ids is not None:
        if not ids:
            return []
        stmt = stmt.where(ChannelEvent.channel_id.in_(ids))

    rows = (await db.execute(stmt)).all()
    out: list[ChannelEventOut] = []
    for ev, ch in rows:
        out.append(
            ChannelEventOut(
                id=ev.id,
                channel_id=ev.channel_id,
                channel_name=ch.name,
                transport=ChannelTransport(ch.transport),
                level=ev.level,
                kind=ev.kind,
                message=ev.message,
                detail=ev.detail,
                created_at=ev.created_at,
            )
        )
    return out


@router.patch("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: int,
    body: ChannelUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelOut:
    channel = await _load_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if body.name is not None:
        channel.name = body.name.strip()
    if body.department_id is not None:
        new_dept = await _resolve_department_id(db, body.department_id)
        channel.department_id = new_dept
        await db.execute(
            update(Dialog)
            .where(Dialog.channel_id == channel.id)
            .values(department_id=new_dept)
        )
    if body.status is not None:
        if channel.transport != ChannelTransport.WEBCHAT.value:
            raise HTTPException(
                status_code=400,
                detail="Смену статуса поддерживает только канал «Виджет на сайт»",
            )
        if body.status not in (ChannelStatus.ONLINE, ChannelStatus.OFFLINE):
            raise HTTPException(status_code=400, detail="Допустимы статусы online или offline")
        channel.status = body.status.value
        channel.last_error = None
    await db.commit()
    loaded = await _load_channel(db, channel_id)
    assert loaded is not None
    return to_channel_out(loaded)


@router.post("/webchat", response_model=ChannelConnectResult)
async def connect_webchat(
    body: WebchatConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelConnectResult:
    adapter = get_adapter(ChannelTransport.WEBCHAT)
    try:
        channel, info = await adapter.connect(
            db,
            credentials={"allowed_origins": body.allowed_origins},
            created_by_id=user.id,
            name=body.name,
        )
        channel.department_id = await _resolve_department_id(db, body.department_id)
        await db.commit()
        channel = await _load_channel(db, channel.id)
        assert channel is not None
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ChannelConnectResult(channel=to_channel_out(channel), bot=info)


@router.post("/maxbot", response_model=ChannelConnectResult)
async def connect_maxbot(
    body: MaxBotConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelConnectResult:
    from app.channel_events import record_channel_event

    adapter = get_adapter(ChannelTransport.MAXBOT)
    cleared: list[str] = []
    try:
        channel, bot_info = await adapter.connect(
            db,
            credentials={"token": body.token.strip()},
            created_by_id=user.id,
            name=body.name,
        )
        channel.department_id = await _resolve_department_id(db, body.department_id)
        cleared = list(getattr(channel, "_cleared_webhooks", []) or [])
        await db.commit()
        channel = await _load_channel(db, channel.id)
        assert channel is not None
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await record_channel_event(
        channel.id,
        kind="connect",
        message=f"Подключён {channel.identity}",
        detail=(
            f"Сняты webhook-подписки: {', '.join(cleared)}"
            if cleared
            else "Webhook-подписок не было — long-poll активен"
        ),
        level="info",
    )
    return ChannelConnectResult(channel=to_channel_out(channel), bot=bot_info)


@router.post("/{channel_id}/test", response_model=ChannelTestResult)
async def test_channel_connection(
    channel_id: int,
    body: ChannelTestRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelTestResult:
    """Probe Max бот: /me, webhook subscriptions, short /updates, poller status."""
    from app.channel_events import record_channel_event
    from app.integrations.credentials_cache import decrypt_cached
    from app.integrations.maxbot import client as max_client
    from app.integrations.maxbot.poller import poller as maxbot_poller
    from app.security import decrypt_secret

    opts = body or ChannelTestRequest()
    channel = await _load_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    await ensure_channel_access(user, channel_id, db)

    if channel.transport != ChannelTransport.MAXBOT.value:
        raise HTTPException(
            status_code=400,
            detail="Проверка подключения пока доступна только для MAX · бот",
        )
    if not channel.credentials_enc:
        raise HTTPException(status_code=400, detail="У канала нет сохранённого токена")

    try:
        token = decrypt_cached(channel.id, channel.credentials_enc, decrypt=decrypt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Токен повреждён: {exc}") from exc

    bot: dict | None = None
    error: str | None = None
    webhook_urls: list[str] = []
    cleared: list[str] = []
    updates_pending = 0
    update_types: list[str] = []
    hint: str | None = None

    try:
        bot = await max_client.get_me(token)
    except IntegrationError as exc:
        error = str(exc)
        await record_channel_event(
            channel.id,
            kind="test",
            message=f"Тест: /me ошибка — {exc}",
            level="error",
        )
        return ChannelTestResult(
            ok=False,
            transport=channel.transport,
            identity=channel.identity,
            poller_running=maxbot_poller.is_running,
            poll_marker=channel.poll_marker,
            last_error=channel.last_error,
            error=error,
            hint="Токен отклонён Max API. Переподключите бота с новым токеном.",
        )

    try:
        subs = await max_client.get_subscriptions(token)
        webhook_urls = [str(s.get("url") or "") for s in subs if s.get("url")]
    except IntegrationError as exc:
        logger.warning("Channel %s subscriptions check failed: %s", channel_id, exc)

    if webhook_urls and opts.clear_webhooks:
        try:
            cleared = await max_client.clear_subscriptions(token)
            webhook_urls = []
        except IntegrationError as exc:
            error = f"Не удалось снять webhook: {exc}"
            hint = (
                "У бота активны webhook-подписки — Max отключает long-poll. "
                "Снимите их вручную или повторите тест."
            )

    if not error:
        try:
            payload = await max_client.get_updates(
                token,
                marker=channel.poll_marker,
                timeout=1,
                limit=10,
            )
            raw_updates = payload.get("updates") or []
            updates_pending = len(raw_updates) if isinstance(raw_updates, list) else 0
            update_types = [
                str(u.get("update_type") or u.get("updateType") or "?")
                for u in (raw_updates if isinstance(raw_updates, list) else [])
                if isinstance(u, dict)
            ]
            # Do not advance poll_marker here — leave that to the poller.
        except IntegrationError as exc:
            error = str(exc)
            if webhook_urls:
                hint = (
                    "Long-poll недоступен из‑за активных webhook. "
                    "Включите clear_webhooks или снимите подписки."
                )

    if not hint and not error:
        if not maxbot_poller.is_running:
            hint = "Поллер не запущен на этом инстансе (проверьте background leader)."
        elif updates_pending:
            hint = (
                f"Есть {updates_pending} апдейт(ов) в очереди — поллер подхватит их в ближайшем цикле."
            )
        else:
            hint = (
                "Токен и long-poll в порядке. Напишите боту в Max (кнопка «Старт»), "
                "диалог появится в CRM. Если сообщений нет — убедитесь, что токен "
                "не используется другим сервисом."
            )

    ok = error is None and bot is not None
    detail_parts = [
        f"poller={'on' if maxbot_poller.is_running else 'off'}",
        f"marker={channel.poll_marker}",
        f"pending={updates_pending}",
    ]
    if cleared:
        detail_parts.append(f"cleared_hooks={len(cleared)}")
    if webhook_urls:
        detail_parts.append(f"hooks={','.join(webhook_urls)}")
    if update_types:
        detail_parts.append(f"types={','.join(update_types)}")

    await record_channel_event(
        channel.id,
        kind="test",
        message=("Тест OK: " + (hint or "подключение в порядке")) if ok else f"Тест: {error}",
        detail="; ".join(detail_parts),
        level="info" if ok else "error",
    )

    return ChannelTestResult(
        ok=ok,
        transport=channel.transport,
        identity=channel.identity,
        bot=bot,
        poller_running=maxbot_poller.is_running,
        poll_marker=channel.poll_marker,
        updates_pending=updates_pending,
        update_types=update_types,
        webhook_subscriptions=webhook_urls,
        webhooks_cleared=cleared,
        hint=hint,
        error=error,
        last_error=channel.last_error,
    )


@router.post("/telegram", response_model=ChannelConnectResult)
async def connect_telegram(
    body: TelegramConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelConnectResult:
    adapter = get_adapter(ChannelTransport.TELEGRAM)
    try:
        channel, bot_info = await adapter.connect(
            db,
            credentials={"token": body.token.strip()},
            created_by_id=user.id,
            name=body.name,
        )
        channel.department_id = await _resolve_department_id(db, body.department_id)
        await db.commit()
        channel = await _load_channel(db, channel.id)
        assert channel is not None
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ChannelConnectResult(channel=to_channel_out(channel), bot=bot_info)


@router.post("/max/qr/start", response_model=MaxQrStartResponse)
async def start_max_qr(
    body: MaxQrStartRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> MaxQrStartResponse:
    dept_id = await _resolve_department_id(db, body.department_id)
    channel = Channel(
        name=body.name or "MAX аккаунт",
        transport=ChannelTransport.MAX.value,
        status=ChannelStatus.QR_PENDING.value,
        identity="ожидает скана QR",
        created_by_id=user.id,
        connected_at=None,
        department_id=dept_id,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    try:
        state = await max_runtime.start_qr_connect(channel.id)
    except IntegrationError as exc:
        channel.status = ChannelStatus.ERROR.value
        channel.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    channel = await _load_channel(db, channel.id)
    assert channel is not None
    if not state.qr_url:
        raise HTTPException(status_code=502, detail="QR URL was not received from Max")

    return MaxQrStartResponse(
        channel=to_channel_out(channel),
        qr_url=state.qr_url,
        status=state.status,
    )


@router.post("/tgapi/qr/start", response_model=MaxQrStartResponse)
async def start_telegram_qr(
    body: MaxQrStartRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> MaxQrStartResponse:
    from app.integrations.telegram_proxy import normalize_proxy_url

    proxy_raw = (body.proxy or "").strip() or None
    if proxy_raw:
        try:
            proxy_raw = normalize_proxy_url(proxy_raw)
        except IntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    dept_id = await _resolve_department_id(db, body.department_id)
    channel = Channel(
        name=body.name or "Telegram аккаунт",
        transport=ChannelTransport.TGAPI.value,
        status=ChannelStatus.QR_PENDING.value,
        identity="ожидает скана QR",
        created_by_id=user.id,
        connected_at=None,
        department_id=dept_id,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    try:
        state = await telegram_user_runtime.start_qr_connect(
            channel.id, proxy=proxy_raw
        )
    except IntegrationError as exc:
        channel.status = ChannelStatus.ERROR.value
        channel.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    channel = await _load_channel(db, channel.id)
    assert channel is not None
    if not state.qr_url:
        raise HTTPException(status_code=502, detail="QR URL was not received from Telegram")

    return MaxQrStartResponse(
        channel=to_channel_out(channel),
        qr_url=state.qr_url,
        status=state.status,
    )


def _qr_runtime_for(channel: Channel):
    if channel.transport == ChannelTransport.MAX.value:
        return max_runtime
    if channel.transport == ChannelTransport.TGAPI.value:
        return telegram_user_runtime
    return None


@router.get("/{channel_id}/qr/status", response_model=MaxQrStatusResponse)
async def qr_status(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHANNELS)),
) -> MaxQrStatusResponse:
    channel = await _load_channel(db, channel_id)
    rt = _qr_runtime_for(channel) if channel is not None else None
    if channel is None or rt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await ensure_channel_access(user, channel_id, db)

    state = rt.get_state(channel_id)
    return MaxQrStatusResponse(
        channel_id=channel_id,
        status=state.status if state else channel.status,
        qr_url=state.qr_url if state else None,
        identity=state.identity if state else channel.identity,
        hint=state.hint if state else None,
        error=state.error if state else channel.last_error,
        channel=to_channel_out(channel),
    )


@router.post("/{channel_id}/qr/2fa", response_model=MaxQrStatusResponse)
async def qr_2fa(
    channel_id: int,
    body: MaxQr2FARequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> MaxQrStatusResponse:
    channel = await _load_channel(db, channel_id)
    rt = _qr_runtime_for(channel) if channel is not None else None
    if channel is None or rt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    try:
        await rt.submit_2fa(channel_id, body.password)
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    state = rt.get_state(channel_id)
    channel = await _load_channel(db, channel_id)
    assert channel is not None
    return MaxQrStatusResponse(
        channel_id=channel_id,
        status=state.status if state else channel.status,
        qr_url=state.qr_url if state else None,
        identity=state.identity if state else channel.identity,
        hint=state.hint if state else None,
        error=state.error if state else channel.last_error,
        channel=to_channel_out(channel),
    )


@router.post("/{channel_id}/reconnect", response_model=ChannelOut)
async def reconnect_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelOut:
    """Manual session restore for personal MAX / Telegram accounts (no QR wipe)."""
    channel = await _load_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.credentials_enc:
        raise HTTPException(
            status_code=400,
            detail="Нет сохранённой сессии — подключите канал заново через QR",
        )
    transport = channel.transport
    try:
        if transport == ChannelTransport.MAX.value:
            await max_runtime.manual_reconnect(channel_id)
        elif transport == ChannelTransport.TGAPI.value:
            await telegram_user_runtime.manual_reconnect(channel_id)
        else:
            raise HTTPException(
                status_code=400,
                detail="Ручное переподключение доступно только для MAX · аккаунт и Telegram · аккаунт",
            )
    except IntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    loaded = await _load_channel(db, channel_id)
    assert loaded is not None
    return to_channel_out(loaded)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> None:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    transport = channel.transport

    # ORM default would SET NULL on dialogs.channel_id (NOT NULL) → IntegrityError.
    # Break appeal circular FK, then remove dialogs (messages/appeals cascade in DB).
    await db.execute(
        update(Dialog)
        .where(Dialog.channel_id == channel_id)
        .values(current_appeal_id=None)
    )
    await db.execute(delete(Dialog).where(Dialog.channel_id == channel_id))
    await db.delete(channel)
    await db.commit()
    # After DB delete so reconnect/restore sees a missing row and gives up.
    try:
        await get_adapter(transport).on_channel_deleted(channel_id)
    except Exception:
        logger.exception("Failed to stop worker for deleted channel %s", channel_id)
