"""Web Push (VAPID) — phone notification shade while the CRM is backgrounded."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.departments import ensure_department_access
from app.models import Dialog, PushSubscription, User, utcnow
from app.rbac import SECTION_CHATS, ensure_channel_access, load_user_rbac, user_can

logger = logging.getLogger(__name__)

_keys_cache: dict[str, str] | None = None


def _vapid_store_path() -> Path:
    return Path(get_settings().max_personal_data_dir).resolve().parent / "vapid.json"


def _encode_public_key(vapid: Vapid) -> str:
    raw = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def get_vapid_keys() -> dict[str, str]:
    """Return {publicKey, privateKey, mailto}. Auto-generate once if missing."""
    global _keys_cache
    if _keys_cache is not None:
        return _keys_cache

    cfg = get_settings()
    if (cfg.vapid_public_key or "").strip() and (cfg.vapid_private_key or "").strip():
        _keys_cache = {
            "publicKey": cfg.vapid_public_key.strip(),
            "privateKey": cfg.vapid_private_key.strip(),
            "mailto": (cfg.vapid_mailto or "mailto:admin@skysender.local").strip(),
        }
        return _keys_cache

    path = _vapid_store_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        _keys_cache = {
            "publicKey": str(data["publicKey"]),
            "privateKey": str(data["privateKey"]),
            "mailto": str(data.get("mailto") or cfg.vapid_mailto),
        }
        return _keys_cache

    vapid = Vapid()
    vapid.generate_keys()
    private_pem = vapid.private_pem()
    if isinstance(private_pem, bytes):
        private_pem = private_pem.decode("ascii")
    data = {
        "publicKey": _encode_public_key(vapid),
        "privateKey": private_pem,
        "mailto": (cfg.vapid_mailto or "mailto:admin@skysender.local").strip(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Generated Web Push VAPID keys at %s", path)
    _keys_cache = data
    return _keys_cache


def public_vapid_key() -> str:
    return get_vapid_keys()["publicKey"]


def _send_one(subscription: dict[str, Any], payload: dict[str, Any]) -> None:
    keys = get_vapid_keys()
    webpush(
        subscription_info=subscription,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=keys["privateKey"],
        vapid_claims={"sub": keys["mailto"]},
        ttl=60,
        timeout=10,
    )


async def upsert_subscription(
    session: AsyncSession,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> PushSubscription:
    result = await session.execute(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
        )
        session.add(row)
    else:
        row.user_id = user_id
        row.p256dh = p256dh
        row.auth = auth
        row.user_agent = user_agent
        row.last_seen_at = utcnow()
    await session.flush()
    return row


async def delete_subscription(session: AsyncSession, *, user_id: int, endpoint: str) -> bool:
    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    return True


async def _user_can_receive_dialog(session: AsyncSession, user: User, dialog: Dialog) -> bool:
    if not user.is_active:
        return False
    loaded = await load_user_rbac(session, user)
    if not user_can(loaded, SECTION_CHATS):
        return False
    try:
        await ensure_channel_access(loaded, dialog.channel_id, session)
        await ensure_department_access(loaded, dialog.department_id, session)
    except HTTPException:
        return False
    return True


async def resolve_notify_user_ids(session: AsyncSession, dialog: Dialog) -> list[int]:
    """Who should get a shade notification for this dialog."""
    if dialog.assignee_id is not None:
        user = await session.get(User, dialog.assignee_id)
        if user is not None and await _user_can_receive_dialog(session, user, dialog):
            return [user.id]
        return []

    result = await session.execute(select(PushSubscription.user_id).distinct())
    candidate_ids = list(result.scalars().all())
    out: list[int] = []
    for uid in candidate_ids:
        user = await session.get(User, uid)
        if user is None:
            continue
        if await _user_can_receive_dialog(session, user, dialog):
            out.append(uid)
    return out


async def send_push_to_users(
    session: AsyncSession,
    user_ids: list[int],
    payload: dict[str, Any],
) -> int:
    if not user_ids:
        return 0
    result = await session.execute(
        select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0

    sent = 0
    stale: list[PushSubscription] = []
    for row in rows:
        sub = {
            "endpoint": row.endpoint,
            "keys": {"p256dh": row.p256dh, "auth": row.auth},
        }
        try:
            await asyncio.to_thread(_send_one, sub, payload)
            row.last_seen_at = utcnow()
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                stale.append(row)
            else:
                logger.warning(
                    "Web Push failed user=%s status=%s: %s",
                    row.user_id,
                    status_code,
                    exc,
                )
        except Exception:
            logger.exception("Web Push unexpected error user=%s", row.user_id)

    for row in stale:
        await session.delete(row)
    if stale:
        await session.flush()
    return sent


async def notify_inbound_message(
    *,
    dialog_id: int,
    contact_name: str,
    text: str,
) -> None:
    """Fire-and-forget from emit_event — opens its own DB session."""
    try:
        async with SessionLocal() as session:
            dialog = await session.get(Dialog, dialog_id)
            if dialog is None:
                return
            user_ids = await resolve_notify_user_ids(session, dialog)
            body = (text or "").strip() or "Новое сообщение"
            if len(body) > 120:
                body = body[:119] + "…"
            payload = {
                "title": (contact_name or "Клиент").strip() or "Клиент",
                "body": body,
                "dialogId": str(dialog_id),
                "tag": f"oe-chat-{dialog_id}",
                "kind": "message",
            }
            n = await send_push_to_users(session, user_ids, payload)
            await session.commit()
            if n:
                logger.info("Web Push inbound dialog=%s recipients=%s sent=%s", dialog_id, user_ids, n)
    except Exception:
        logger.exception("Web Push inbound notify failed dialog=%s", dialog_id)


async def notify_chat_assigned(
    *,
    dialog_id: int,
    assignee_id: int,
    contact_name: str,
    from_name: str | None,
) -> None:
    try:
        async with SessionLocal() as session:
            dialog = await session.get(Dialog, dialog_id)
            if dialog is None:
                return
            body = (
                f"{from_name} передал(а) вам обращение"
                if (from_name or "").strip()
                else "Вам передали обращение"
            )
            payload = {
                "title": (contact_name or "Клиент").strip() or "Клиент",
                "body": body,
                "dialogId": str(dialog_id),
                "tag": f"oe-assign-{dialog_id}",
                "kind": "assign",
            }
            n = await send_push_to_users(session, [assignee_id], payload)
            await session.commit()
            if n:
                logger.info("Web Push assign dialog=%s user=%s sent=%s", dialog_id, assignee_id, n)
    except Exception:
        logger.exception("Web Push assign notify failed dialog=%s", dialog_id)
