from __future__ import annotations

from sqlalchemy import inspect as sa_inspect

from app.models import ChatMessage, MessageAttachment
from app.schemas import AttachmentOut, MessageOut, ReplyPreview
from app.storage.attachments import preview_label


def attachment_to_out(att: MessageAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=att.id,
        kind=att.kind,  # type: ignore[arg-type]
        file_name=att.file_name,
        mime_type=att.mime_type,
        size_bytes=att.size_bytes,
        url=f"/api/chats/attachments/{att.id}",
    )


def _reply_preview(message: ChatMessage) -> ReplyPreview | None:
    if not message.reply_to_message_id:
        return None
    state = sa_inspect(message)
    if "reply_to" in state.unloaded:
        return ReplyPreview(
            id=message.reply_to_message_id,
            text="",
            direction="in",  # type: ignore[arg-type]
            operator_name=None,
        )
    target = message.reply_to
    if target is None:
        return ReplyPreview(
            id=message.reply_to_message_id,
            text="",
            direction="in",  # type: ignore[arg-type]
            operator_name=None,
        )
    preview = (target.text or "").strip()
    if not preview and target.attachments:
        first = target.attachments[0]
        preview = preview_label(first.kind, first.file_name)
    if len(preview) > 160:
        preview = preview[:157] + "…"
    return ReplyPreview(
        id=target.id,
        text=preview,
        direction=target.direction,  # type: ignore[arg-type]
        operator_name=target.operator_name,
    )


def message_to_out(message: ChatMessage) -> MessageOut:
    attachments = [attachment_to_out(a) for a in (message.attachments or [])]
    return MessageOut(
        id=message.id,
        dialog_id=message.dialog_id,
        direction=message.direction,  # type: ignore[arg-type]
        text="" if message.deleted_at else message.text,
        status=message.status,  # type: ignore[arg-type]
        operator_name=message.operator_name,
        created_at=message.created_at,
        edited_at=message.edited_at,
        deleted_at=message.deleted_at,
        is_internal=bool(getattr(message, "is_internal", False)),
        appeal_id=message.appeal_id,
        attachments=[] if message.deleted_at else attachments,
        reply_to=None if message.deleted_at else _reply_preview(message),
    )


def message_preview_text(text: str, attachments: list[MessageAttachment] | None = None) -> str:
    cleaned = (text or "").strip()
    if cleaned:
        return cleaned
    if attachments:
        first = attachments[0]
        return preview_label(first.kind, first.file_name)
    return ""
