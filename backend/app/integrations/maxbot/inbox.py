from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.appeals import ensure_open_appeal
from app.dialogs import bump_unread, get_or_create_dialog, try_insert_message
from app.integrations.maxbot import client as max_client
from app.models import (
    AttachmentKind,
    Channel,
    ChatMessage,
    Dialog,
    MessageAttachment,
    MessageDirection,
    MessageStatus,
    utcnow,
)
from app.serializers import message_preview_text
from app.storage.attachments import guess_kind, save_bytes

logger = logging.getLogger(__name__)


async def _resolve_reply_to_id(
    session: AsyncSession, channel_id: int, external_id: str | None
) -> int | None:
    if not external_id:
        return None
    result = await session.execute(
        select(ChatMessage.id).where(
            ChatMessage.channel_id == channel_id,
            ChatMessage.external_id == str(external_id),
        )
    )
    return result.scalar_one_or_none()


def _reply_mid_from_payload(message: dict[str, Any], body: dict[str, Any]) -> str | None:
    link = body.get("link") or message.get("link")
    if not isinstance(link, dict):
        return None
    link_type = str(link.get("type") or "").lower()
    if link_type not in {"reply", "replied"}:
        return None
    mid = link.get("mid") or link.get("message_id") or link.get("messageId")
    return str(mid) if mid is not None else None


def _ts_to_dt(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return utcnow()


def _user_avatar(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    for key in ("photo_url", "avatar_url", "image_url", "full_avatar_url"):
        value = user.get(key)
        if value:
            return str(value)
    return None


def _user_name(user: dict[str, Any] | None) -> str:
    if not user:
        return "Клиент"
    first = user.get("first_name") or user.get("name") or ""
    last = user.get("last_name") or ""
    full = f"{first} {last}".strip()
    if full:
        return full
    username = user.get("username")
    if username:
        return f"@{username}"
    uid = user.get("user_id") or user.get("id")
    return f"User {uid}" if uid is not None else "Клиент"


async def process_update(
    session: AsyncSession, channel: Channel, update: dict[str, Any]
) -> ChatMessage | None:
    update_type = update.get("update_type") or update.get("updateType")
    if update_type == "message_created":
        return await _handle_message_created(session, channel, update)
    if update_type in {"bot_started", "message_callback"}:
        await _handle_bot_started(session, channel, update)
        return None
    logger.debug("Skip update_type=%s channel=%s", update_type, channel.id)
    return None


async def _handle_bot_started(session: AsyncSession, channel: Channel, update: dict[str, Any]) -> None:
    user = update.get("user") if isinstance(update.get("user"), dict) else None
    chat_id = update.get("chat_id") or update.get("chatId")
    if chat_id is None and user:
        chat_id = user.get("user_id") or user.get("id")
    if chat_id is None:
        return
    await get_or_create_dialog(
        session,
        channel=channel,
        external_chat_id=str(chat_id),
        contact_external_id=str(user.get("user_id") or user.get("id") or chat_id) if user else str(chat_id),
        contact_name=_user_name(user),
        contact_username=(user or {}).get("username"),
        contact_avatar_url=_user_avatar(user),
    )


async def _handle_message_created(
    session: AsyncSession, channel: Channel, update: dict[str, Any]
) -> ChatMessage | None:
    message = update.get("message")
    if not isinstance(message, dict):
        logger.warning("message_created without message payload: %s", update)
        return None

    sender = message.get("sender") if isinstance(message.get("sender"), dict) else None
    recipient = message.get("recipient") if isinstance(message.get("recipient"), dict) else {}
    body = message.get("body") if isinstance(message.get("body"), dict) else {}

    text = (body.get("text") or message.get("text") or "").strip()
    mid = body.get("mid") or body.get("seq") or message.get("id") or message.get("mid")
    raw_attachments = body.get("attachments") or message.get("attachments") or []

    chat_id = recipient.get("chat_id") or recipient.get("chatId") or update.get("chat_id")
    user_id = None
    if sender and not sender.get("is_bot"):
        user_id = sender.get("user_id") or sender.get("id")
    if user_id is None:
        user_id = recipient.get("user_id") or recipient.get("userId")

    external_chat_id = str(chat_id if chat_id is not None else user_id)
    if external_chat_id == "None":
        logger.warning("Cannot resolve chat for update: %s", update)
        return None

    contact_id = str(user_id) if user_id is not None else external_chat_id
    is_from_bot = bool(sender and sender.get("is_bot"))
    direction = MessageDirection.OUT.value if is_from_bot else MessageDirection.IN.value

    dialog = await get_or_create_dialog(
        session,
        channel=channel,
        external_chat_id=external_chat_id,
        contact_external_id=contact_id,
        contact_name=_user_name(sender) if not is_from_bot else _dialog_name_fallback(recipient),
        contact_username=(sender or {}).get("username") if not is_from_bot else None,
        contact_avatar_url=_user_avatar(sender) if not is_from_bot else None,
    )

    if mid is not None:
        exists = await session.execute(
            select(ChatMessage).where(
                ChatMessage.channel_id == channel.id,
                ChatMessage.external_id == str(mid),
            )
        )
        if exists.scalar_one_or_none():
            return None

    appeal = await ensure_open_appeal(session, dialog)

    created_at = _ts_to_dt(message.get("timestamp") or update.get("timestamp"))
    reply_to_id = await _resolve_reply_to_id(
        session, channel.id, _reply_mid_from_payload(message, body)
    )
    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal.id,
        external_id=str(mid) if mid is not None else None,
        direction=direction,
        text=text,
        status=MessageStatus.DELIVERED.value,
        reply_to_message_id=reply_to_id,
        raw_json=json.dumps(update, ensure_ascii=False),
        created_at=created_at,
    )
    if await try_insert_message(session, msg) is None:
        return None

    stored = await _persist_bot_attachments(session, msg, raw_attachments if isinstance(raw_attachments, list) else [])
    if not msg.text:
        msg.text = message_preview_text("", stored) or "[медиа]"

    dialog.last_message = message_preview_text(msg.text, stored)
    dialog.last_direction = direction
    dialog.last_status = msg.status
    dialog.last_at = created_at
    if direction == MessageDirection.IN.value:
        await bump_unread(session, dialog)
        if sender:
            dialog.contact_name = _user_name(sender)
            dialog.contact_username = sender.get("username")
            avatar = _user_avatar(sender)
            if avatar:
                dialog.contact_avatar_url = avatar
            if user_id is not None:
                dialog.contact_external_id = str(user_id)

    await session.refresh(msg, attribute_names=["attachments", "reply_to"])
    return msg


async def _persist_bot_attachments(
    session: AsyncSession,
    msg: ChatMessage,
    raw_attachments: list[Any],
) -> list[MessageAttachment]:
    stored: list[MessageAttachment] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        att_type = str(item.get("type") or "").lower()
        if att_type in {"inline_keyboard", "share", "sticker", "contact", "location"}:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        url = payload.get("url") or item.get("url")
        file_name = (
            payload.get("file_name")
            or payload.get("filename")
            or payload.get("name")
            or item.get("filename")
            or ("voice.ogg" if att_type in {"audio", "voice"} else f"{att_type or 'file'}")
        )
        mime = payload.get("mime_type") or payload.get("content_type")
        if att_type in {"audio", "voice"} and not mime:
            mime = "audio/ogg"
        kind = _map_bot_kind(att_type, mime, str(file_name))
        relative = None
        size = payload.get("size")
        remote_url = str(url) if url else None

        if remote_url:
            try:
                data = await max_client.download_url(remote_url)
                relative, safe_name, resolved_mime, size = save_bytes(
                    data=data,
                    file_name=str(file_name),
                    message_id=msg.id,
                    mime_type=mime,
                )
                file_name = safe_name
                mime = resolved_mime
            except Exception:
                logger.exception("Failed to download maxbot attachment url=%s", remote_url)

        att = MessageAttachment(
            message_id=msg.id,
            kind=kind.value,
            file_name=str(file_name),
            mime_type=mime,
            size_bytes=int(size) if isinstance(size, int) else None,
            storage_path=relative,
            remote_url=remote_url,
            provider_file_id=str(payload.get("token") or payload.get("fileId") or "") or None,
        )
        session.add(att)
        stored.append(att)
    await session.flush()
    return stored


def _map_bot_kind(att_type: str, mime: str | None, filename: str) -> AttachmentKind:
    if att_type in {"image", "photo"}:
        return AttachmentKind.IMAGE
    if att_type == "video":
        return AttachmentKind.VIDEO
    if att_type in {"audio", "voice"}:
        return AttachmentKind.AUDIO
    if att_type == "file":
        return AttachmentKind.FILE
    return guess_kind(mime, filename)


def _dialog_name_fallback(recipient: dict[str, Any]) -> str:
    return f"Chat {recipient.get('chat_id') or recipient.get('user_id') or ''}".strip()


async def load_message_with_attachments(session: AsyncSession, message_id: int) -> ChatMessage | None:
    result = await session.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.attachments))
        .where(ChatMessage.id == message_id)
    )
    return result.scalar_one_or_none()
