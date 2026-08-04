"""Write successful mailing sends into CRM dialogs (best-effort)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.appeals import ensure_open_appeal
from app.dialogs import get_or_create_dialog, try_insert_message
from app.models import (
    Channel,
    ChatMessage,
    MessageDirection,
    MessageStatus,
    utcnow,
)
from app.outbound_start import ResolvedPeer

logger = logging.getLogger(__name__)


async def write_mailing_to_crm(
    session: AsyncSession,
    *,
    channel: Channel,
    peer: ResolvedPeer,
    text: str,
    external_id: str | None,
    campaign_name: str,
) -> None:
    """Create/update dialog + outbound message. Never raises to caller."""
    try:
        dialog = await get_or_create_dialog(
            session,
            channel=channel,
            external_chat_id=peer.external_chat_id,
            contact_external_id=peer.contact_external_id,
            contact_name=peer.contact_name or "Клиент",
            contact_username=peer.contact_username,
        )
        if peer.contact_phone and not dialog.contact_phone:
            dialog.contact_phone = peer.contact_phone
        appeal = await ensure_open_appeal(session, dialog)
        preview = (text or "").strip()
        if len(preview) > 500:
            preview = preview[:497] + "…"
        msg = ChatMessage(
            dialog_id=dialog.id,
            channel_id=channel.id,
            appeal_id=appeal.id,
            external_id=external_id,
            direction=MessageDirection.OUT.value,
            text=preview or "[рассылка]",
            status=MessageStatus.DELIVERED.value if external_id else MessageStatus.SENT.value,
            operator_id=None,
            operator_name=f"Рассылка · {campaign_name}"[:255],
            created_at=utcnow(),
        )
        inserted = await try_insert_message(session, msg)
        if inserted is None:
            return
        dialog.last_message = preview or "[рассылка]"
        dialog.last_direction = MessageDirection.OUT.value
        dialog.last_status = msg.status
        dialog.last_at = utcnow()
        await session.flush()
    except Exception:
        logger.exception(
            "Mailing CRM write failed channel=%s peer=%s",
            channel.id,
            peer.external_chat_id,
        )
