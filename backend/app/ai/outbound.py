"""Send AI-generated outbound text via channel adapters (no human User)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.appeals import get_current_appeal
from app.dialogs import clear_unread_after_outbound
from app.integrations.base import IntegrationError
from app.integrations.registry import get_adapter
from app.models import (
    AppealStatus,
    Channel,
    ChatMessage,
    Dialog,
    MessageDirection,
    MessageStatus,
    utcnow,
)
from app.realtime.publish import emit_event, message_created_event
from app.serializers import message_preview_text

logger = logging.getLogger(__name__)


async def send_ai_text(
    db: AsyncSession,
    *,
    dialog: Dialog,
    channel: Channel,
    text: str,
    reply_to_message_id: int | None = None,
) -> ChatMessage:
    caption = (text or "").strip()
    if not caption:
        raise IntegrationError("Empty AI reply")

    current = await get_current_appeal(db, dialog)
    if current is None or current.status != AppealStatus.OPEN.value:
        raise IntegrationError("Appeal closed — AI cannot reply")

    reply_external_id: str | None = None
    if reply_to_message_id is not None:
        target = await db.get(ChatMessage, reply_to_message_id)
        if target is not None and target.dialog_id == dialog.id:
            reply_external_id = target.external_id

    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=current.id,
        external_id=None,
        direction=MessageDirection.OUT.value,
        text=caption,
        status=MessageStatus.SENT.value,
        is_ai=True,
        operator_id=None,
        operator_name="ИИ",
        reply_to_message_id=reply_to_message_id,
        created_at=utcnow(),
    )
    db.add(msg)
    await db.flush()
    msg_id = msg.id
    await db.commit()

    adapter = get_adapter(channel.transport)

    async def _send():
        return await adapter.send_text(
            channel,
            dialog,
            caption,
            reply_to_external_id=reply_external_id,
        )

    try:
        send_result = await _send()
    except Exception as exc:
        failed = await db.get(ChatMessage, msg_id)
        if failed is not None:
            failed.status = MessageStatus.FAILED.value
            failed.delivery_error = str(exc)[:2000]
            await db.commit()
        raise

    msg = await db.get(ChatMessage, msg_id)
    if msg is None:
        raise IntegrationError("AI draft disappeared")
    if send_result.external_id:
        msg.external_id = str(send_result.external_id)
    msg.status = MessageStatus.SENT.value
    msg.delivery_error = None
    await db.flush()

    preview = message_preview_text(msg.text or "", list(msg.attachments or []))
    await clear_unread_after_outbound(db, dialog, outbound_at=msg.created_at)
    if not (
        dialog.last_direction == MessageDirection.IN.value
        and dialog.last_at
        and dialog.last_at > msg.created_at
    ):
        dialog.last_message = preview or caption
        dialog.last_direction = MessageDirection.OUT.value
        dialog.last_status = msg.status
        dialog.last_at = msg.created_at

    await db.commit()

    result = await db.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.attachments), selectinload(ChatMessage.reply_to))
        .where(ChatMessage.id == msg_id)
    )
    loaded = result.scalar_one()
    dialog_loaded = await db.get(Dialog, dialog.id)
    if dialog_loaded is not None:
        await emit_event(message_created_event(dialog_loaded, loaded, channel.transport))
    return loaded
