from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.custom.message import Message as TlMessage
from telethon.tl.types import User, Chat, Channel as TlChannel

from app.appeals import ensure_open_appeal
from app.dialogs import bump_unread, get_or_create_dialog, try_insert_message
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


def message_external_id(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


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


def _user_display(entity: Any) -> tuple[str, str | None]:
    if isinstance(entity, User):
        first = (entity.first_name or "").strip()
        last = (entity.last_name or "").strip()
        full = f"{first} {last}".strip()
        username = entity.username
        if full:
            return full, username
        if username:
            return f"@{username}", username
        return f"User {entity.id}", username
    if isinstance(entity, (Chat, TlChannel)):
        title = (getattr(entity, "title", None) or "").strip()
        return title or f"Chat {getattr(entity, 'id', '')}", getattr(entity, "username", None)
    return "Клиент", None


async def ingest_telethon_message(
    session: AsyncSession,
    *,
    channel: Channel,
    client: Any,
    message: TlMessage,
    my_user_id: int | None,
) -> ChatMessage | None:
    chat_id = message.chat_id
    if chat_id is None:
        return None
    message_id = message.id
    external_id = message_external_id(int(chat_id), int(message_id))

    exists = await session.execute(
        select(ChatMessage).where(
            ChatMessage.channel_id == channel.id,
            ChatMessage.external_id == external_id,
        )
    )
    if exists.scalar_one_or_none():
        return None

    is_out = bool(message.out)
    if my_user_id is not None and message.sender_id is not None:
        is_out = is_out or int(message.sender_id) == int(my_user_id)
    direction = MessageDirection.OUT.value if is_out else MessageDirection.IN.value

    contact_name = "Клиент"
    contact_username = None
    contact_external_id = str(message.sender_id) if message.sender_id is not None else str(chat_id)

    try:
        chat_entity = await message.get_chat()
        sender = await message.get_sender()
        chat_type_private = isinstance(chat_entity, User)
        if chat_type_private:
            contact_name, contact_username = _user_display(sender or chat_entity)
            if sender and getattr(sender, "id", None) is not None:
                contact_external_id = str(sender.id)
            else:
                contact_external_id = str(chat_id)
        else:
            contact_name, contact_username = _user_display(chat_entity)
            contact_external_id = str(chat_id)
    except Exception:
        logger.debug("Failed to resolve telethon peers for chat=%s", chat_id, exc_info=True)
        contact_name = f"Chat {chat_id}"

    dialog = await get_or_create_dialog(
        session,
        channel=channel,
        external_chat_id=str(chat_id),
        contact_external_id=contact_external_id,
        contact_name=contact_name,
        contact_username=contact_username,
    )

    appeal = await ensure_open_appeal(session, dialog)

    text = (message.message or message.text or "").strip()
    reply_external = None
    if message.reply_to and getattr(message.reply_to, "reply_to_msg_id", None):
        reply_external = message_external_id(int(chat_id), int(message.reply_to.reply_to_msg_id))
    reply_to_id = await _resolve_reply_to_id(session, channel.id, reply_external)

    created_at = message.date
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at is None:
        created_at = utcnow()

    raw = {
        "id": message.id,
        "chat_id": chat_id,
        "sender_id": message.sender_id,
        "out": message.out,
        "text": text,
    }
    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal.id,
        external_id=external_id,
        direction=direction,
        text=text,
        status=MessageStatus.DELIVERED.value,
        reply_to_message_id=reply_to_id,
        raw_json=json.dumps(raw, ensure_ascii=False),
        created_at=created_at if isinstance(created_at, datetime) else utcnow(),
    )
    if await try_insert_message(session, msg) is None:
        return None

    stored = await _persist_media(session, msg, message)
    if not msg.text:
        msg.text = message_preview_text("", stored) or "[медиа]"

    dialog.last_message = message_preview_text(msg.text, stored)
    dialog.last_direction = direction
    dialog.last_status = msg.status
    dialog.last_at = msg.created_at
    if direction == MessageDirection.IN.value:
        await bump_unread(session, dialog)
        dialog.contact_name = contact_name or dialog.contact_name
        dialog.contact_username = contact_username
        dialog.contact_external_id = contact_external_id

    await session.refresh(msg, attribute_names=["attachments", "reply_to"])
    return msg


async def _persist_media(
    session: AsyncSession,
    msg: ChatMessage,
    message: TlMessage,
) -> list[MessageAttachment]:
    if not message.media:
        return []
    try:
        data = await message.download_media(file=bytes)
    except Exception:
        logger.exception("Failed to download telethon media message=%s", message.id)
        return []
    if not data:
        return []

    file_name = "file"
    mime = None
    kind = AttachmentKind.FILE
    if message.photo:
        file_name = "photo.jpg"
        mime = "image/jpeg"
        kind = AttachmentKind.IMAGE
    elif message.video:
        file_name = "video.mp4"
        mime = getattr(message.video, "mime_type", None) or "video/mp4"
        kind = AttachmentKind.VIDEO
    elif message.voice:
        file_name = "voice.ogg"
        mime = getattr(message.voice, "mime_type", None) or "audio/ogg"
        kind = AttachmentKind.AUDIO
    elif message.audio:
        file_name = getattr(message.audio, "file_name", None) or "audio"
        mime = getattr(message.audio, "mime_type", None)
        kind = AttachmentKind.AUDIO
    elif message.document:
        file_name = getattr(message.document, "file_name", None) or "document"
        mime = getattr(message.document, "mime_type", None)
        kind = guess_kind(mime, str(file_name))
        # document attributes may hold filename
        for attr in getattr(message.document, "attributes", []) or []:
            name = getattr(attr, "file_name", None)
            if name:
                file_name = name
                break

    relative, safe_name, resolved_mime, size = save_bytes(
        data=data if isinstance(data, (bytes, bytearray)) else bytes(data),
        file_name=str(file_name),
        message_id=msg.id,
        mime_type=mime,
    )
    att = MessageAttachment(
        message_id=msg.id,
        kind=kind.value,
        file_name=safe_name,
        mime_type=resolved_mime,
        size_bytes=size,
        storage_path=relative,
        remote_url=None,
        provider_file_id=None,
    )
    session.add(att)
    await session.flush()
    return [att]
