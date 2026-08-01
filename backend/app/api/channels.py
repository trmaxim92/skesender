from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.departments import ensure_default_department
from app.deps import get_current_user
from app.integrations.base import IntegrationError
from app.integrations.max_personal.runtime import runtime as max_runtime
from app.integrations.telegram_user.runtime import runtime as telegram_user_runtime
from app.integrations.registry import get_adapter
from app.models import Channel, ChannelStatus, ChannelTransport, Department, Dialog, User
from app.rbac import (
    ACTION_MANAGE_CHANNELS,
    ACTION_MANAGE_USERS,
    SECTION_CHANNELS,
    SECTION_MAILING,
    accessible_channel_ids,
    ensure_channel_access,
    load_user_rbac,
    require_permission,
    user_can,
)
from app.schemas import (
    ChannelConnectResult,
    ChannelOut,
    ChannelUpdateRequest,
    MaxBotConnectRequest,
    MaxQr2FARequest,
    MaxQrStartRequest,
    MaxQrStartResponse,
    MaxQrStatusResponse,
    TelegramConnectRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])


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
    if not (
        user_can(loaded, SECTION_CHANNELS)
        or user_can(loaded, ACTION_MANAGE_USERS)
        or user_can(loaded, SECTION_MAILING)
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
    await db.commit()
    loaded = await _load_channel(db, channel_id)
    assert loaded is not None
    return to_channel_out(loaded)


@router.post("/maxbot", response_model=ChannelConnectResult)
async def connect_maxbot(
    body: MaxBotConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_MANAGE_CHANNELS)),
) -> ChannelConnectResult:
    adapter = get_adapter(ChannelTransport.MAXBOT)
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
        state = await telegram_user_runtime.start_qr_connect(channel.id)
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
    await db.delete(channel)
    await db.commit()
    # After DB delete so reconnect/restore sees a missing row and gives up.
    try:
        await get_adapter(transport).on_channel_deleted(channel_id)
    except Exception:
        logger.exception("Failed to stop worker for deleted channel %s", channel_id)
