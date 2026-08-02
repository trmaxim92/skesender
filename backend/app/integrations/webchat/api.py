"""Public API for the website chat widget (no cabinet JWT)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.appeals import ensure_open_appeal
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.dialogs import bump_unread, get_or_create_dialog, try_insert_message
from app.integrations.webchat.visitor_hub import visitor_hub
from app.models import (
    Channel,
    ChannelStatus,
    ChannelTransport,
    ChatMessage,
    Dialog,
    MessageDirection,
    MessageStatus,
    utcnow,
)
from app.realtime.publish import emit_event, message_created_event
from app.schemas import WidgetMessageCreate, WidgetMessageOut, WidgetSessionOut, WidgetSessionRequest
from app.security import ALGORITHM

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/widget", tags=["widget"])

_VISITOR_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")
WIDGET_TOKEN_TYPE = "webchat_visitor"


def _create_visitor_token(*, channel_id: int, dialog_id: int, visitor_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=30)
    payload = {
        "typ": WIDGET_TOKEN_TYPE,
        "channel_id": channel_id,
        "dialog_id": dialog_id,
        "visitor_id": visitor_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _decode_visitor_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != WIDGET_TOKEN_TYPE:
        return None
    return payload


def _origin_allowed(channel: Channel, origin: str | None) -> bool:
    """Empty allow-list = all origins; otherwise exact match (scheme+host[+port])."""
    if not channel.meta_json:
        return True
    try:
        meta = json.loads(channel.meta_json)
    except Exception:
        return True
    allowed = meta.get("allowed_origins") or []
    if not isinstance(allowed, list) or not allowed:
        return True
    if not origin:
        return False
    normalized = origin.rstrip("/")
    allowed_norm = {str(o).strip().rstrip("/") for o in allowed if str(o).strip()}
    return normalized in allowed_norm


async def _load_webchat_channel(db: AsyncSession, public_key: str) -> Channel | None:
    result = await db.execute(
        select(Channel).where(
            Channel.transport == ChannelTransport.WEBCHAT.value,
            Channel.external_id == public_key.strip(),
        )
    )
    return result.scalar_one_or_none()


async def _visitor_context(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> tuple[Channel, Dialog, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Требуется visitor token")
    token = authorization.split(" ", 1)[1].strip()
    payload = _decode_visitor_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный visitor token")
    channel_id = int(payload["channel_id"])
    dialog_id = int(payload["dialog_id"])
    visitor_id = str(payload["visitor_id"])

    channel = await db.get(Channel, channel_id)
    if channel is None or channel.transport != ChannelTransport.WEBCHAT.value:
        raise HTTPException(status_code=404, detail="Канал не найден")
    dialog = await db.get(Dialog, dialog_id)
    if dialog is None or dialog.channel_id != channel.id:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    if dialog.external_chat_id != visitor_id:
        raise HTTPException(status_code=403, detail="Сессия не совпадает с диалогом")
    return channel, dialog, visitor_id


def _message_out(msg: ChatMessage) -> WidgetMessageOut:
    return WidgetMessageOut(
        id=msg.id,
        external_id=msg.external_id,
        direction=MessageDirection(msg.direction),
        text="" if msg.deleted_at else (msg.text or ""),
        created_at=msg.created_at,
    )


@router.post("/session", response_model=WidgetSessionOut)
async def create_widget_session(
    body: WidgetSessionRequest,
    db: AsyncSession = Depends(get_db),
    origin: str | None = Header(default=None, alias="Origin"),
) -> WidgetSessionOut:
    channel = await _load_webchat_channel(db, body.public_key)
    if channel is None:
        raise HTTPException(status_code=404, detail="Виджет не найден")
    if origin and not _origin_allowed(channel, origin.rstrip("/")):
        raise HTTPException(status_code=403, detail="Origin не разрешён для этого виджета")

    visitor_id = (body.visitor_id or "").strip()
    if visitor_id:
        if not _VISITOR_ID_RE.match(visitor_id):
            raise HTTPException(status_code=400, detail="Некорректный visitor_id")
    else:
        visitor_id = f"v_{secrets.token_urlsafe(12)}"

    contact_name = (body.contact_name or "").strip() or "Посетитель сайта"
    dialog = await get_or_create_dialog(
        db,
        channel=channel,
        external_chat_id=visitor_id,
        contact_external_id=visitor_id,
        contact_name=contact_name,
        contact_username=None,
    )
    await ensure_open_appeal(db, dialog)
    await db.commit()

    token = _create_visitor_token(
        channel_id=channel.id,
        dialog_id=dialog.id,
        visitor_id=visitor_id,
    )
    return WidgetSessionOut(
        visitor_token=token,
        visitor_id=visitor_id,
        dialog_id=dialog.id,
        channel_name=channel.name,
        channel_online=channel.status == ChannelStatus.ONLINE.value,
    )


@router.get("/messages", response_model=list[WidgetMessageOut])
async def list_widget_messages(
    ctx: tuple[Channel, Dialog, str] = Depends(_visitor_context),
    db: AsyncSession = Depends(get_db),
) -> list[WidgetMessageOut]:
    _channel, dialog, _visitor = ctx
    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.dialog_id == dialog.id,
            ChatMessage.is_internal.is_(False),
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(200)
    )
    return [_message_out(m) for m in result.scalars().all()]


@router.post("/messages", response_model=WidgetMessageOut)
async def post_widget_message(
    body: WidgetMessageCreate,
    ctx: tuple[Channel, Dialog, str] = Depends(_visitor_context),
    db: AsyncSession = Depends(get_db),
) -> WidgetMessageOut:
    channel, dialog, visitor_id = ctx
    if channel.status != ChannelStatus.ONLINE.value:
        raise HTTPException(status_code=403, detail="Виджет временно недоступен")

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    # Refresh dialog with relations for events
    result = await db.execute(
        select(Dialog)
        .options(selectinload(Dialog.current_appeal), selectinload(Dialog.channel))
        .where(Dialog.id == dialog.id)
    )
    dialog = result.scalar_one()
    appeal = await ensure_open_appeal(db, dialog)

    external_id = f"in-{secrets.token_hex(8)}"
    now = utcnow()
    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal.id,
        external_id=external_id,
        direction=MessageDirection.IN.value,
        text=text,
        status=MessageStatus.DELIVERED.value,
        created_at=now,
    )
    if await try_insert_message(db, msg) is None:
        raise HTTPException(status_code=409, detail="Сообщение уже существует")

    dialog.last_message = text
    dialog.last_direction = MessageDirection.IN.value
    dialog.last_status = msg.status
    dialog.last_at = now
    await bump_unread(db, dialog)
    await db.commit()

    result = await db.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.attachments))
        .where(ChatMessage.id == msg.id)
    )
    msg = result.scalar_one()
    result = await db.execute(
        select(Dialog)
        .options(selectinload(Dialog.current_appeal), selectinload(Dialog.channel))
        .where(Dialog.id == dialog.id)
    )
    dialog = result.scalar_one()
    await emit_event(message_created_event(dialog, msg, ChannelTransport.WEBCHAT.value))

    out = _message_out(msg)
    await visitor_hub.publish(
        dialog.id,
        {
            "type": "message",
            "message": {
                "id": out.id,
                "external_id": out.external_id,
                "direction": out.direction.value,
                "text": out.text,
                "created_at": out.created_at.isoformat(),
            },
        },
    )
    return out


@router.websocket("/ws")
async def widget_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=15)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=1008)
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.close(code=1008)
        return
    if not isinstance(data, dict) or data.get("type") != "auth":
        await websocket.close(code=1008)
        return
    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        await websocket.close(code=1008)
        return

    payload = _decode_visitor_token(token.strip())
    if not payload:
        await websocket.close(code=1008)
        return
    dialog_id = int(payload["dialog_id"])
    channel_id = int(payload["channel_id"])

    async with SessionLocal() as session:
        channel = await session.get(Channel, channel_id)
        dialog = await session.get(Dialog, dialog_id)
        if (
            channel is None
            or dialog is None
            or channel.transport != ChannelTransport.WEBCHAT.value
            or dialog.channel_id != channel.id
        ):
            await websocket.close(code=1008)
            return

    await visitor_hub.connect(dialog_id, websocket)
    try:
        await websocket.send_json({"type": "ready", "dialog_id": dialog_id})
        while True:
            # Keepalive / ignore client pings
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        visitor_hub.disconnect(dialog_id, websocket)
