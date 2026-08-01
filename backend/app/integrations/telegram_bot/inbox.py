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
from app.integrations.telegram_bot import client as tg_client
from app.integrations.telegram_bot.result import telegram_message_external_id
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
from app.security import decrypt_secret

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


def _ts_to_dt(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return utcnow()


def _user_name(user: dict[str, Any] | None) -> str:
    if not user:
        return "Клиент"
    first = user.get("first_name") or ""
    last = user.get("last_name") or ""
    full = f"{first} {last}".strip()
    if full:
        return full
    username = user.get("username")
    if username:
        return f"@{username}"
    uid = user.get("id")
    return f"User {uid}" if uid is not None else "Клиент"


def _chat_title(chat: dict[str, Any] | None) -> str | None:
    if not chat:
        return None
    title = chat.get("title")
    if title:
        return str(title)
    return None


async def process_update(
    session: AsyncSession, channel: Channel, update: dict[str, Any]
) -> ChatMessage | None:
    message = update.get("message") or update.get("edited_message")
    if isinstance(message, dict):
        return await _handle_message(session, channel, update, message)

    # Start / deep-link without text still opens a dialog via message above.
    # Callback queries ignored for v1.
    logger.debug("Skip telegram update channel=%s keys=%s", channel.id, list(update.keys()))
    return None


async def _handle_message(
    session: AsyncSession,
    channel: Channel,
    update: dict[str, Any],
    message: dict[str, Any],
) -> ChatMessage | None:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else None
    chat_id = chat.get("id")
    if chat_id is None:
        logger.warning("Telegram message without chat: %s", update)
        return None

    external_chat_id = str(chat_id)
    bot_id = channel.external_id
    sender_id = str(sender.get("id")) if sender and sender.get("id") is not None else None
    is_from_bot = bool(sender and (sender.get("is_bot") or (bot_id and sender_id == bot_id)))
    direction = MessageDirection.OUT.value if is_from_bot else MessageDirection.IN.value

    contact_name = _chat_title(chat) or (_user_name(sender) if not is_from_bot else f"Chat {chat_id}")
    contact_username = None
    contact_external_id = sender_id or external_chat_id
    if chat.get("type") == "private" and sender and not is_from_bot:
        contact_name = _user_name(sender)
        contact_username = sender.get("username")
        contact_external_id = sender_id or external_chat_id
    elif chat.get("type") != "private":
        contact_external_id = external_chat_id

    dialog = await get_or_create_dialog(
        session,
        channel=channel,
        external_chat_id=external_chat_id,
        contact_external_id=contact_external_id,
        contact_name=contact_name,
        contact_username=contact_username,
    )

    external_id = telegram_message_external_id(message)
    if external_id:
        exists = await session.execute(
            select(ChatMessage).where(
                ChatMessage.channel_id == channel.id,
                ChatMessage.external_id == external_id,
            )
        )
        if exists.scalar_one_or_none():
            # edited_message: update text and surface to UI via message.updated
            if update.get("edited_message"):
                existing = (
                    await session.execute(
                        select(ChatMessage)
                        .options(
                            selectinload(ChatMessage.attachments),
                            selectinload(ChatMessage.reply_to).selectinload(ChatMessage.attachments),
                        )
                        .where(
                            ChatMessage.channel_id == channel.id,
                            ChatMessage.external_id == external_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    new_text = (message.get("text") or message.get("caption") or "").strip()
                    if new_text and new_text != existing.text:
                        existing.text = new_text
                        existing.edited_at = utcnow()
                        latest_id = await session.scalar(
                            select(ChatMessage.id)
                            .where(
                                ChatMessage.dialog_id == dialog.id,
                                ChatMessage.deleted_at.is_(None),
                                ChatMessage.is_internal.is_(False),
                            )
                            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                            .limit(1)
                        )
                        if latest_id == existing.id:
                            dialog.last_message = message_preview_text(
                                new_text, list(existing.attachments or [])
                            )
                            dialog.last_at = _ts_to_dt(
                                message.get("edit_date") or message.get("date")
                            )
                        return existing
                return None
            return None

    appeal = await ensure_open_appeal(session, dialog)

    text = (message.get("text") or message.get("caption") or "").strip()
    reply_msg = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else None
    reply_external = telegram_message_external_id(reply_msg) if reply_msg else None
    reply_to_id = await _resolve_reply_to_id(session, channel.id, reply_external)

    created_at = _ts_to_dt(message.get("date"))
    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal.id,
        external_id=external_id,
        direction=direction,
        text=text,
        status=MessageStatus.DELIVERED.value,
        reply_to_message_id=reply_to_id,
        raw_json=json.dumps(update, ensure_ascii=False),
        created_at=created_at,
    )
    if await try_insert_message(session, msg) is None:
        return None

    token = decrypt_secret(channel.credentials_enc) if channel.credentials_enc else None
    stored = await _persist_attachments(session, msg, message, token)
    if not msg.text:
        msg.text = message_preview_text("", stored) or "[медиа]"

    dialog.last_message = message_preview_text(msg.text, stored)
    dialog.last_direction = direction
    dialog.last_status = msg.status
    dialog.last_at = created_at
    if direction == MessageDirection.IN.value:
        await bump_unread(session, dialog)
        if chat.get("type") == "private" and sender:
            dialog.contact_name = _user_name(sender)
            dialog.contact_username = sender.get("username")
            if sender_id:
                dialog.contact_external_id = sender_id
        elif _chat_title(chat):
            dialog.contact_name = _chat_title(chat) or dialog.contact_name

    await session.refresh(msg, attribute_names=["attachments", "reply_to"])
    return msg


async def _persist_attachments(
    session: AsyncSession,
    msg: ChatMessage,
    message: dict[str, Any],
    token: str | None,
) -> list[MessageAttachment]:
    stored: list[MessageAttachment] = []
    candidates: list[tuple[str, dict[str, Any]]] = []

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        best = max(
            (p for p in photos if isinstance(p, dict)),
            key=lambda p: int(p.get("file_size") or 0),
            default=None,
        )
        if best:
            candidates.append(("photo", best))

    for key in ("document", "video", "audio", "voice", "video_note", "animation"):
        item = message.get(key)
        if isinstance(item, dict):
            candidates.append((key, item))

    for kind_key, payload in candidates:
        file_id = payload.get("file_id")
        if not file_id:
            continue
        file_name = (
            payload.get("file_name")
            or ("voice.ogg" if kind_key == "voice" else None)
            or ("video_note.mp4" if kind_key == "video_note" else None)
            or ("animation.mp4" if kind_key == "animation" else None)
            or ("photo.jpg" if kind_key == "photo" else f"{kind_key}")
        )
        mime = payload.get("mime_type")
        if kind_key == "voice" and not mime:
            mime = "audio/ogg"
        if kind_key == "photo" and not mime:
            mime = "image/jpeg"

        kind = _map_tg_kind(kind_key, mime, str(file_name))
        relative = None
        size = payload.get("file_size")
        remote_url = None

        if token:
            try:
                file_info = await tg_client.get_file(token, str(file_id))
                file_path = file_info.get("file_path")
                if file_path:
                    data = await tg_client.download_file(token, str(file_path))
                    relative, safe_name, resolved_mime, size = save_bytes(
                        data=data,
                        file_name=str(file_name),
                        message_id=msg.id,
                        mime_type=mime,
                    )
                    file_name = safe_name
                    mime = resolved_mime
                    remote_url = f"{tg_client.TELEGRAM_API_BASE}/file/bot***/{file_path}"
            except Exception:
                logger.exception("Failed to download telegram file_id=%s", file_id)

        att = MessageAttachment(
            message_id=msg.id,
            kind=kind.value,
            file_name=str(file_name),
            mime_type=mime,
            size_bytes=int(size) if isinstance(size, int) else None,
            storage_path=relative,
            remote_url=remote_url,
            provider_file_id=str(file_id),
        )
        session.add(att)
        stored.append(att)

    await session.flush()
    return stored


def _map_tg_kind(kind_key: str, mime: str | None, filename: str) -> AttachmentKind:
    if kind_key == "photo":
        return AttachmentKind.IMAGE
    if kind_key in {"video", "video_note", "animation"}:
        return AttachmentKind.VIDEO
    if kind_key in {"audio", "voice"}:
        return AttachmentKind.AUDIO
    return guess_kind(mime, filename)
