from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db import SessionLocal
from app.departments import accessible_department_ids
from app.models import User
from app.rbac import accessible_channel_ids, load_user_rbac
from app.realtime.hub import hub
from app.security import decode_access_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])


async def _auth_context(token: str | None) -> tuple[int, str, list[int] | None, list[int] | None] | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == payload["sub"]))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        loaded = await load_user_rbac(session, user)
        channel_ids = await accessible_channel_ids(loaded, session)
        department_ids = await accessible_department_ids(loaded, session)
        return loaded.id, loaded.email, channel_ids, department_ids


async def _read_auth_token(websocket: WebSocket) -> str | None:
    """Auth via first JSON frame: {"type":"auth","token":"..."}.

    Query ?token= is no longer accepted — keeps JWTs out of proxy/access logs.
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=15)
    except asyncio.TimeoutError:
        return None
    except WebSocketDisconnect:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("type") != "auth":
        return None
    token = data.get("token")
    return token if isinstance(token, str) and token.strip() else None


@router.websocket("/ws/chats")
async def ws_chats(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        token = await _read_auth_token(websocket)
        ctx = await _auth_context(token)
    except Exception:
        logger.exception("WS auth lookup failed")
        await websocket.close(code=1011)
        return

    if ctx is None:
        logger.warning("WS rejected: invalid or missing auth frame")
        await websocket.close(code=1008)
        return

    user_id, email, channel_ids, department_ids = ctx
    await hub.connect(
        websocket,
        user_id=user_id,
        channel_ids=channel_ids,
        department_ids=department_ids,
        accepted=True,
    )
    logger.info("WS chats connected user=%s", email)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=50)
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS chats connection error user=%s", email)
    finally:
        await hub.disconnect(websocket)
