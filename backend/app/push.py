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


def _vapid_signer() -> Vapid:
    """pywebpush expects a Vapid instance or raw/base64 key — PEM must use from_pem."""
    keys = get_vapid_keys()
    private = keys["privateKey"].strip()
    if private.startswith("-----BEGIN"):
        pem = private.encode("ascii") if isinstance(private, str) else private
        return Vapid.from_pem(pem)
    return Vapid.from_string(private_key=private)


def _send_one(subscription: dict[str, Any], payload: dict[str, Any]) -> None:
    keys = get_vapid_keys()
    webpush(
        subscription_info=subscription,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=_vapid_signer(),
        vapid_claims={"sub": keys["mailto"]},
        # Long TTL + high urgency so FCM/APNs can wake a locked phone.
        ttl=86_400,
        timeout=8,
        headers={
            "Urgency": "high",
        },
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


def _is_mobile_ua(ua: str | None) -> bool:
    s = (ua or "").lower()
    return any(x in s for x in ("android", "iphone", "ipad", "mobile"))


def _sort_mobile_first(rows: list[PushSubscription]) -> list[PushSubscription]:
    # Prefer phone endpoints so a slow desktop FCM call doesn't delay the wake.
    return sorted(rows, key=lambda r: (0 if _is_mobile_ua(r.user_agent) else 1, r.id))


async def _deliver_rows(
    session: AsyncSession,
    rows: list[PushSubscription],
    payload: dict[str, Any],
) -> int:
    """Send in parallel; drop 404/410 subscriptions."""

    async def _one(row: PushSubscription) -> str:
        sub = {
            "endpoint": row.endpoint,
            "keys": {"p256dh": row.p256dh, "auth": row.auth},
        }
        try:
            await asyncio.to_thread(_send_one, sub, payload)
            row.last_seen_at = utcnow()
            return "ok"
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                return "stale"
            logger.warning(
                "Web Push failed user=%s status=%s: %s",
                row.user_id,
                status_code,
                exc,
            )
            return "fail"
        except Exception:
            logger.exception("Web Push unexpected error user=%s", row.user_id)
            return "fail"

    results = await asyncio.gather(*(_one(r) for r in rows))
    sent = 0
    for row, status in zip(rows, results, strict=True):
        if status == "ok":
            sent += 1
        elif status == "stale":
            await session.delete(row)
    if any(s == "stale" for s in results):
        await session.flush()
    return sent


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
    rows = _sort_mobile_first(list(result.scalars().all()))
    if not rows:
        return 0
    return await _deliver_rows(session, rows, payload)


async def notify_inbound_message(
    *,
    dialog_id: int,
    contact_name: str,
    text: str,
    assignee_id: int | None = None,
    message_id: int | None = None,
) -> None:
    """Fire-and-forget from emit_event — opens its own DB session."""
    started = asyncio.get_running_loop().time()
    try:
        async with SessionLocal() as session:
            if assignee_id is not None:
                user_ids = [int(assignee_id)]
            else:
                dialog = await session.get(Dialog, dialog_id)
                if dialog is None:
                    return
                user_ids = await resolve_notify_user_ids(session, dialog)
            if not user_ids:
                return
            body = (text or "").strip() or "Новое сообщение"
            if len(body) > 120:
                body = body[:119] + "…"
            # Unique tag per message — same-tag collapse on Android can look like a long delay.
            tag = (
                f"oe-chat-{dialog_id}-{message_id}"
                if message_id is not None
                else f"oe-chat-{dialog_id}-{int(started * 1000) % 1_000_000}"
            )
            payload = {
                "title": (contact_name or "Клиент").strip() or "Клиент",
                "body": body,
                "dialogId": str(dialog_id),
                "tag": tag,
                "kind": "message",
                "requireInteraction": True,
            }
            result = await session.execute(
                select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
            )
            rows = _sort_mobile_first(list(result.scalars().all()))
            n = await _deliver_rows(session, rows, payload) if rows else 0
            await session.commit()
            elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
            logger.info(
                "Web Push inbound dialog=%s recipients=%s sent=%s in %sms",
                dialog_id,
                user_ids,
                n,
                elapsed_ms,
            )
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
                "requireInteraction": True,
            }
            n = await send_push_to_users(session, [assignee_id], payload)
            await session.commit()
            if n:
                logger.info("Web Push assign dialog=%s user=%s sent=%s", dialog_id, assignee_id, n)
    except Exception:
        logger.exception("Web Push assign notify failed dialog=%s", dialog_id)
