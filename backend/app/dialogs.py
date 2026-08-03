"""Dialog helpers shared by inbox adapters."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChatMessage, Dialog, utcnow


async def get_or_create_dialog(
    session: AsyncSession,
    *,
    channel: Channel,
    external_chat_id: str,
    contact_external_id: str | None,
    contact_name: str,
    contact_username: str | None,
    contact_avatar_url: str | None = None,
) -> Dialog:
    result = await session.execute(
        select(Dialog).where(
            Dialog.channel_id == channel.id,
            Dialog.external_chat_id == external_chat_id,
        )
    )
    dialog = result.scalar_one_or_none()
    if dialog:
        if dialog.department_id is None and channel.department_id is not None:
            dialog.department_id = channel.department_id
        if contact_username and not dialog.contact_username:
            dialog.contact_username = contact_username
        if contact_name and (
            not dialog.contact_name
            or dialog.contact_name.startswith("User ")
            or dialog.contact_name.startswith("Chat ")
        ):
            dialog.contact_name = contact_name
        if contact_avatar_url and not dialog.contact_avatar_url:
            dialog.contact_avatar_url = contact_avatar_url
        return dialog

    dialog = Dialog(
        channel_id=channel.id,
        external_chat_id=external_chat_id,
        contact_external_id=contact_external_id,
        contact_name=contact_name or "Клиент",
        contact_username=contact_username,
        contact_avatar_url=contact_avatar_url,
        department_id=channel.department_id,
        last_message="",
        last_at=utcnow(),
        unread=0,
    )
    try:
        async with session.begin_nested():
            session.add(dialog)
            await session.flush()
    except IntegrityError:
        result = await session.execute(
            select(Dialog).where(
                Dialog.channel_id == channel.id,
                Dialog.external_chat_id == external_chat_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        return existing
    return dialog


async def bump_unread(session: AsyncSession, dialog: Dialog) -> int:
    """Atomically increment dialog.unread; syncs ORM attribute for event payloads."""
    result = await session.execute(
        update(Dialog)
        .where(Dialog.id == dialog.id)
        .values(unread=Dialog.unread + 1)
        .returning(Dialog.unread)
    )
    value = int(result.scalar_one())
    dialog.unread = value
    return value


async def clear_unread(session: AsyncSession, dialog: Dialog) -> bool:
    """Atomically set unread=0. Returns True if a non-zero counter was cleared."""
    result = await session.execute(
        update(Dialog)
        .where(Dialog.id == dialog.id, Dialog.unread > 0)
        .values(unread=0)
        .returning(Dialog.id)
    )
    cleared = result.scalar_one_or_none() is not None
    dialog.unread = 0
    return cleared


async def try_insert_message(session: AsyncSession, msg: ChatMessage) -> ChatMessage | None:
    """Insert inbound/outbound row; return None on unique (channel_id, external_id) race.

    Uses a nested transaction so a duplicate does not abort the outer poller session.
    """
    try:
        async with session.begin_nested():
            session.add(msg)
            await session.flush()
        return msg
    except IntegrityError:
        if not msg.external_id:
            raise
        return None
