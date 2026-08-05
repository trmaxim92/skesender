from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.appeals import ensure_open_appeal
from app.config import get_settings
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
from app.storage.attachments import save_bytes

try:
    from pymax.types.domain.attachments.audio import AudioAttachment
    from pymax.types.domain.attachments.file import FileAttachment
    from pymax.types.domain.attachments.photo import PhotoAttachment
    from pymax.types.domain.attachments.share import ShareAttachment
    from pymax.types.domain.attachments.sticker import StickerAttachment
    from pymax.types.domain.attachments.video import VideoAttachment
except Exception:  # pragma: no cover
    AudioAttachment = ()  # type: ignore[misc, assignment]
    FileAttachment = ()  # type: ignore[misc, assignment]
    PhotoAttachment = ()  # type: ignore[misc, assignment]
    ShareAttachment = ()  # type: ignore[misc, assignment]
    StickerAttachment = ()  # type: ignore[misc, assignment]
    VideoAttachment = ()  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)


def _is_group_chat(chat_id: int) -> bool:
    return int(chat_id) < 0


def _name_from_pymax_user(user: Any) -> tuple[str | None, str | None]:
    if user is None:
        return None, None
    names = getattr(user, "names", None) or []
    for n in names:
        first = (getattr(n, "first_name", None) or "").strip()
        last = (getattr(n, "last_name", None) or "").strip()
        full = f"{first} {last}".strip()
        if full:
            return full, None
        plain = (getattr(n, "name", None) or "").strip()
        if plain:
            return plain, None
    phone = _phone_from_pymax_user(user)
    if phone:
        return phone, None
    uid = getattr(user, "id", None)
    if uid is not None:
        return f"User {uid}", None
    return None, None


def _phone_from_pymax_user(user: Any) -> str | None:
    if user is None:
        return None
    raw = getattr(user, "phone", None)
    if raw is None:
        return None
    phone = str(raw).strip()
    if not phone:
        return None
    if phone.isdigit():
        return f"+{phone}"
    return phone


def _avatar_from_obj(obj: Any) -> str | None:
    if obj is None:
        return None
    for key in ("base_url", "base_icon_url", "base_raw_url", "base_raw_icon_url", "photo_url", "avatar_url"):
        value = getattr(obj, key, None)
        if value:
            return str(value)
    return None


async def _resolve_contact_profile(
    client: Any | None, sender_id: int | None, chat_id: int
) -> tuple[str, str | None, str | None, str | None]:
    if client is not None and _is_group_chat(chat_id):
        try:
            chat = await client.get_chat(int(chat_id))
            title = (getattr(chat, "title", None) or "").strip()
            avatar = _avatar_from_obj(chat)
            if title:
                return title, None, avatar, None
            if avatar:
                return f"Chat {chat_id}", None, avatar, None
        except Exception:
            logger.debug("Failed to resolve pymax chat title chat_id=%s", chat_id, exc_info=True)
    if client is not None and sender_id is not None:
        try:
            user = client.get_cached_user(int(sender_id))
            if user is None:
                user = await client.get_user(int(sender_id))
            resolved_name, resolved_username = _name_from_pymax_user(user)
            avatar = _avatar_from_obj(user)
            phone = _phone_from_pymax_user(user)
            if resolved_name:
                return resolved_name, resolved_username, avatar, phone
        except Exception:
            logger.debug(
                "Failed to resolve pymax user profile sender_id=%s",
                sender_id,
                exc_info=True,
            )
    if client is not None and sender_id is None:
        try:
            chat = await client.get_chat(int(chat_id))
            title = (getattr(chat, "title", None) or "").strip()
            avatar = _avatar_from_obj(chat)
            if title:
                return title, None, avatar, None
        except Exception:
            logger.debug("Failed to resolve pymax chat title chat_id=%s", chat_id, exc_info=True)
    if sender_id is not None:
        return f"User {sender_id}", None, None, None
    return f"Chat {chat_id}", None, None, None


async def backfill_dialog_names(session: AsyncSession, *, channel: Channel, client: Any) -> int:
    """Replace placeholder User/Chat names using live PyMax profiles."""
    result = await session.execute(select(Dialog).where(Dialog.channel_id == channel.id))
    dialogs = list(result.scalars().all())
    updated = 0
    for dialog in dialogs:
        name = (dialog.contact_name or "").strip()
        chat_id = int(dialog.external_chat_id) if dialog.external_chat_id.lstrip("-").isdigit() else 0
        if not (
            _is_group_chat(chat_id)
            or name.startswith("User ")
            or name.startswith("Chat ")
            or not dialog.contact_avatar_url
        ):
            continue
        candidates: list[int | None] = []
        if _is_group_chat(chat_id):
            candidates.append(None)
        if dialog.contact_external_id and dialog.contact_external_id.lstrip("-").isdigit():
            candidates.append(int(dialog.contact_external_id))
        if chat_id > 0:
            candidates.append(chat_id)
        candidates.append(None)

        resolved = name
        username = dialog.contact_username
        avatar = dialog.contact_avatar_url
        phone = dialog.contact_phone
        changed = False
        for sender_id in candidates:
            candidate, cand_username, cand_avatar, cand_phone = await _resolve_contact_profile(
                client, sender_id, chat_id or 0
            )
            if cand_avatar and not avatar:
                avatar = cand_avatar
                changed = True
            if cand_phone and not phone:
                phone = cand_phone
                changed = True
            if candidate and not (
                candidate.startswith("User ") or candidate.startswith("Chat ")
            ):
                if candidate != resolved:
                    resolved = candidate
                    changed = True
                if cand_username and cand_username != username:
                    username = cand_username
                    changed = True
                if cand_avatar and cand_avatar != dialog.contact_avatar_url:
                    avatar = cand_avatar
                    changed = True
                if cand_phone and not dialog.contact_phone:
                    phone = cand_phone
                    changed = True
                break

        if changed:
            dialog.contact_name = resolved
            dialog.contact_username = username
            dialog.contact_avatar_url = avatar
            if phone and not dialog.contact_phone:
                dialog.contact_phone = phone
            updated += 1
    if updated:
        await session.flush()
    return updated


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
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return utcnow()


async def apply_read_mark(
    session: AsyncSession,
    *,
    channel: Channel,
    chat_id: int,
    mark: int,
    set_as_unread: bool = False,
) -> list[ChatMessage]:
    """Mark outbound messages as read using Max personal read cursor."""
    if set_as_unread:
        return []

    result = await session.execute(
        select(Dialog).where(
            Dialog.channel_id == channel.id,
            Dialog.external_chat_id == str(chat_id),
        )
    )
    dialog = result.scalar_one_or_none()
    if dialog is None:
        return []

    cutoff: datetime | None = None
    cursor = await session.execute(
        select(ChatMessage).where(
            ChatMessage.channel_id == channel.id,
            ChatMessage.external_id == str(mark),
        )
    )
    cursor_msg = cursor.scalar_one_or_none()
    if cursor_msg is not None:
        cutoff = cursor_msg.created_at
    else:
        cutoff = _ts_to_dt(mark)

    # Small skew so clock drift between our created_at and Max mark still matches.
    cutoff = cutoff + timedelta(seconds=5)

    rows = await session.execute(
        select(ChatMessage)
        .options(
            selectinload(ChatMessage.attachments),
            selectinload(ChatMessage.reply_to).selectinload(ChatMessage.attachments),
        )
        .where(
            ChatMessage.dialog_id == dialog.id,
            ChatMessage.direction == MessageDirection.OUT.value,
            ChatMessage.deleted_at.is_(None),
            ChatMessage.status != MessageStatus.READ.value,
            ChatMessage.created_at <= cutoff,
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    updated = list(rows.scalars().all())
    for msg in updated:
        msg.status = MessageStatus.READ.value
    if updated:
        await session.flush()
        latest = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.dialog_id == dialog.id, ChatMessage.deleted_at.is_(None))
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        last_msg = latest.scalar_one_or_none()
        if last_msg is not None:
            dialog.last_direction = last_msg.direction
            dialog.last_status = last_msg.status
    return updated


async def ingest_pymax_message(
    session: AsyncSession,
    *,
    channel: Channel,
    chat_id: int,
    message_id: int | None,
    sender_id: int | None,
    text: str,
    timestamp: Any,
    my_user_id: int | None,
    attaches: list[Any] | None = None,
    client: Any | None = None,
    reply_to_external_id: str | None = None,
) -> ChatMessage | None:
    direction = (
        MessageDirection.OUT.value
        if my_user_id is not None and sender_id == my_user_id
        else MessageDirection.IN.value
    )
    contact_id = str(sender_id) if sender_id is not None else str(chat_id)
    contact_name, contact_username, contact_avatar_url, contact_phone = await _resolve_contact_profile(
        client, sender_id, chat_id
    )

    dialog = await get_or_create_dialog(
        session,
        channel=channel,
        external_chat_id=str(chat_id),
        contact_external_id=contact_id,
        contact_name=contact_name,
        contact_username=contact_username,
        contact_avatar_url=contact_avatar_url,
        contact_phone=contact_phone,
    )

    if message_id is not None:
        exists = await session.execute(
            select(ChatMessage).where(
                ChatMessage.channel_id == channel.id,
                ChatMessage.external_id == str(message_id),
            )
        )
        if exists.scalar_one_or_none():
            return None

    appeal = await ensure_open_appeal(session, dialog)

    created_at = _ts_to_dt(timestamp)
    reply_to_id = await _resolve_reply_to_id(session, channel.id, reply_to_external_id)
    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal.id,
        external_id=str(message_id) if message_id is not None else None,
        direction=direction,
        text=(text or "").strip(),
        status=MessageStatus.DELIVERED.value,
        reply_to_message_id=reply_to_id,
        raw_json=json.dumps(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "sender_id": sender_id,
                "text": text,
                "reply_to": reply_to_external_id,
                "attach_types": [
                    _attach_type_name(a) or type(a).__name__ for a in (attaches or [])
                ],
            },
            ensure_ascii=False,
        ),
        created_at=created_at,
    )
    if await try_insert_message(session, msg) is None:
        return None

    attaches_list = list(attaches or [])
    stored = await _persist_pymax_attachments(
        session,
        msg,
        attaches_list,
        client=client,
        chat_id=chat_id,
        message_id=message_id,
    )
    # Live events sometimes arrive without resolved media payload — refetch once.
    if (
        not stored
        and not (text or "").strip()
        and client is not None
        and message_id is not None
    ):
        try:
            full = await client.get_message(int(chat_id), int(message_id))
            refetch = list(getattr(full, "attaches", None) or []) if full else []
            if refetch:
                logger.info(
                    "Refetched %s attaches for max message chat=%s id=%s",
                    len(refetch),
                    chat_id,
                    message_id,
                )
                stored = await _persist_pymax_attachments(
                    session,
                    msg,
                    refetch,
                    client=client,
                    chat_id=chat_id,
                    message_id=message_id,
                )
        except Exception:
            logger.exception(
                "Failed to refetch max message attaches chat=%s id=%s",
                chat_id,
                message_id,
            )
    if not msg.text:
        msg.text = message_preview_text("", stored) or "[медиа]"

    dialog.last_message = message_preview_text(msg.text, stored)
    dialog.last_direction = direction
    dialog.last_status = msg.status
    dialog.last_at = created_at
    if direction == MessageDirection.IN.value:
        await bump_unread(session, dialog)
        if _is_group_chat(chat_id):
            if (
                not dialog.contact_name
                or dialog.contact_name.startswith("User ")
                or dialog.contact_name.startswith("Chat ")
            ):
                dialog.contact_name = contact_name
            if contact_avatar_url and not dialog.contact_avatar_url:
                dialog.contact_avatar_url = contact_avatar_url
        else:
            dialog.contact_name = contact_name
            dialog.contact_username = contact_username
            if contact_avatar_url:
                dialog.contact_avatar_url = contact_avatar_url
            if sender_id is not None:
                dialog.contact_external_id = str(sender_id)
            if contact_phone and not dialog.contact_phone:
                dialog.contact_phone = contact_phone

    await session.refresh(msg, attribute_names=["attachments", "reply_to"])
    return msg


async def _persist_pymax_attachments(
    session: AsyncSession,
    msg: ChatMessage,
    attaches: list[Any],
    *,
    client: Any | None,
    chat_id: int,
    message_id: int | None,
) -> list[MessageAttachment]:
    stored: list[MessageAttachment] = []
    for attach in attaches:
        kind, file_name, remote_url, provider_id, mime = await _resolve_pymax_attach(
            attach,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
        )
        if kind is None:
            logger.info(
                "Skip unsupported max attach type=%s class=%s msg=%s",
                _attach_type_name(attach),
                type(attach).__name__,
                msg.id,
            )
            continue

        relative = None
        size = None
        if remote_url:
            try:
                data = await _download(remote_url)
                relative, safe_name, resolved_mime, size = save_bytes(
                    data=data,
                    file_name=file_name,
                    message_id=msg.id,
                    mime_type=mime,
                )
                file_name = safe_name
                mime = resolved_mime
            except Exception:
                logger.exception("Failed to download pymax attachment url=%s", remote_url)

        att = MessageAttachment(
            message_id=msg.id,
            kind=kind.value,
            file_name=file_name,
            mime_type=mime,
            size_bytes=size,
            storage_path=relative,
            remote_url=remote_url,
            provider_file_id=str(provider_id) if provider_id is not None else None,
        )
        session.add(att)
        stored.append(att)
    await session.flush()
    return stored


def _attach_type_name(attach: Any) -> str:
    raw = getattr(attach, "type", None)
    if raw is None and isinstance(attach, dict):
        raw = attach.get("_type") or attach.get("type")
    if raw is None:
        return ""
    return str(getattr(raw, "value", raw) or "").upper()


def _clean_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


async def _resolve_pymax_attach(
    attach: Any,
    *,
    client: Any | None,
    chat_id: int,
    message_id: int | None,
) -> tuple[AttachmentKind | None, str, str | None, Any, str | None]:
    type_name = _attach_type_name(attach)

    if isinstance(attach, PhotoAttachment) or type_name == "PHOTO":
        return (
            AttachmentKind.IMAGE,
            f"photo_{getattr(attach, 'photo_id', 'img')}.jpg",
            _clean_url(getattr(attach, "base_url", None)),
            getattr(attach, "photo_id", None),
            "image/jpeg",
        )
    if isinstance(attach, VideoAttachment) or type_name == "VIDEO":
        url = None
        video_id = getattr(attach, "video_id", None)
        if client is not None and message_id is not None and video_id is not None:
            try:
                req = await client.get_video_by_id(chat_id, message_id, int(video_id))
                url = getattr(req, "url", None) if req else None
            except Exception:
                logger.exception("get_video_by_id failed")
        return (
            AttachmentKind.VIDEO,
            f"video_{video_id or 'clip'}.mp4",
            _clean_url(url),
            video_id,
            "video/mp4",
        )
    if isinstance(attach, FileAttachment) or type_name == "FILE":
        url = None
        file_id = getattr(attach, "file_id", None)
        if client is not None and message_id is not None and file_id is not None:
            try:
                req = await client.get_file_by_id(chat_id, message_id, int(file_id))
                url = getattr(req, "url", None) if req else None
            except Exception:
                logger.exception("get_file_by_id failed")
        name = getattr(attach, "name", None) or f"file_{file_id or 'doc'}"
        return (
            AttachmentKind.FILE,
            str(name),
            _clean_url(url),
            file_id,
            None,
        )
    if isinstance(attach, AudioAttachment) or type_name == "AUDIO":
        return (
            AttachmentKind.AUDIO,
            f"voice_{getattr(attach, 'audio_id', 'track')}.ogg",
            _clean_url(getattr(attach, "url", None)),
            getattr(attach, "audio_id", None),
            "audio/ogg",
        )
    if isinstance(attach, StickerAttachment) or type_name == "STICKER":
        sticker_id = getattr(attach, "sticker_id", None)
        url = _clean_url(getattr(attach, "url", None)) or _clean_url(
            getattr(attach, "lottie_url", None)
        )
        return (
            AttachmentKind.IMAGE,
            f"sticker_{sticker_id or 'pack'}.webp",
            url,
            sticker_id,
            "image/webp",
        )
    if isinstance(attach, ShareAttachment) or type_name == "SHARE":
        image = getattr(attach, "image", None) or {}
        image_url = None
        if isinstance(image, dict):
            image_url = (
                image.get("url")
                or image.get("baseUrl")
                or image.get("base_url")
                or image.get("photoUrl")
            )
        title = getattr(attach, "title", None) or getattr(attach, "url", None) or "link"
        if image_url:
            return (
                AttachmentKind.IMAGE,
                f"share_{getattr(attach, 'url', 'preview')}.jpg",
                _clean_url(image_url),
                None,
                "image/jpeg",
            )
        return (
            AttachmentKind.FILE,
            str(title)[:200],
            _clean_url(getattr(attach, "url", None)),
            None,
            "text/uri-list",
        )
    return None, "file", None, None, None


async def repair_message_media(
    session: AsyncSession,
    *,
    msg: ChatMessage,
    channel: Channel,
    client: Any,
) -> list[MessageAttachment]:
    """Fetch full MAX message and persist missing attachments."""
    if not msg.external_id:
        return []
    existing = list(msg.attachments or [])
    if existing:
        return existing
    dialog = await session.get(Dialog, msg.dialog_id)
    if dialog is None or not dialog.external_chat_id:
        return []
    chat_id = int(dialog.external_chat_id)
    message_id = int(msg.external_id)
    attaches = await _fetch_message_attaches(client, chat_id, message_id)
    if not attaches:
        return []
    stored = await _persist_pymax_attachments(
        session,
        msg,
        attaches,
        client=client,
        chat_id=chat_id,
        message_id=message_id,
    )
    if stored and (not msg.text or msg.text == "[медиа]"):
        msg.text = message_preview_text("", stored) or msg.text or "[медиа]"
    await session.refresh(msg, attribute_names=["attachments"])
    return stored


async def _fetch_message_attaches(client: Any, chat_id: int, message_id: int) -> list[Any]:
    """Best-effort: get_message → get_messages → recent history scan."""
    try:
        full = await client.get_message(chat_id, message_id)
        attaches = list(getattr(full, "attaches", None) or []) if full else []
        if attaches:
            return attaches
    except Exception:
        logger.exception("get_message failed chat=%s id=%s", chat_id, message_id)

    try:
        many = await client.get_messages(chat_id, [message_id])
        for item in many or []:
            if int(getattr(item, "id", 0) or 0) != message_id:
                continue
            attaches = list(getattr(item, "attaches", None) or [])
            if attaches:
                return attaches
    except Exception:
        logger.exception("get_messages failed chat=%s id=%s", chat_id, message_id)

    try:
        hist = await client.fetch_history(chat_id, backward=50)
        for item in hist or []:
            if int(getattr(item, "id", 0) or 0) != message_id:
                continue
            attaches = list(getattr(item, "attaches", None) or [])
            logger.info(
                "History hit for max message chat=%s id=%s attaches=%s text=%r",
                chat_id,
                message_id,
                len(attaches),
                getattr(item, "text", None),
            )
            return attaches
    except Exception:
        logger.exception("fetch_history failed chat=%s id=%s", chat_id, message_id)

    return []


async def _download(url: str) -> bytes:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20.0, verify=settings.max_api_verify_ssl, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise RuntimeError(f"download failed: {response.status_code}")
    return response.content


async def load_message_with_attachments(session: AsyncSession, message_id: int) -> ChatMessage | None:
    result = await session.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.attachments))
        .where(ChatMessage.id == message_id)
    )
    return result.scalar_one_or_none()







