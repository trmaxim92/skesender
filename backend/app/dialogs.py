"""Dialog helpers shared by inbox adapters."""

from __future__ import annotations

import re

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChatMessage, Contact, ContactStatus, Dialog, utcnow


def _normalize_phone(raw: str | None) -> str:
    digits = re.sub(r"\D+", "", (raw or "").strip())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


async def ensure_dialog_crm_contact(session: AsyncSession, dialog: Dialog) -> Contact | None:
    """Link dialog to a CRM Contact by phone (create if missing)."""
    if dialog.contact_id is not None:
        return await session.get(Contact, dialog.contact_id)

    phone = _normalize_phone(dialog.contact_phone)
    if len(phone) < 5:
        return None

    # Never treat the channel's own number as the client's phone.
    channel = await session.get(Channel, dialog.channel_id)
    if channel is not None:
        channel_phone = _normalize_phone(channel.identity)
        if len(channel_phone) >= 5 and channel_phone == phone:
            dialog.contact_phone = None
            return None

    existing = (
        await session.execute(select(Contact).where(Contact.phone == phone).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        dialog.contact_id = existing.id
        if dialog.department_id and existing.department_id is None:
            existing.department_id = dialog.department_id
        if dialog.contact_name and (
            not existing.name
            or existing.name == existing.phone
            or existing.name.startswith("User ")
        ):
            existing.name = dialog.contact_name
        return existing

    contact = Contact(
        name=(dialog.contact_name or "").strip() or phone,
        phone=phone,
        status=ContactStatus.NEW.value,
        department_id=dialog.department_id,
    )
    session.add(contact)
    await session.flush()
    dialog.contact_id = contact.id
    return contact


async def get_or_create_dialog(
    session: AsyncSession,
    *,
    channel: Channel,
    external_chat_id: str,
    contact_external_id: str | None,
    contact_name: str,
    contact_username: str | None,
    contact_avatar_url: str | None = None,
    contact_phone: str | None = None,
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
        if contact_phone and not dialog.contact_phone:
            dialog.contact_phone = contact_phone
        try:
            await ensure_dialog_crm_contact(session, dialog)
        except Exception:
            pass
        return dialog

    dialog = Dialog(
        channel_id=channel.id,
        external_chat_id=external_chat_id,
        contact_external_id=contact_external_id,
        contact_name=contact_name or "Клиент",
        contact_username=contact_username,
        contact_avatar_url=contact_avatar_url,
        contact_phone=contact_phone,
        department_id=channel.department_id,
        last_message="",
        last_at=utcnow(),
        unread=0,
    )
    try:
        async with session.begin_nested():
            session.add(dialog)
            await session.flush()
            try:
                await ensure_dialog_crm_contact(session, dialog)
            except Exception:
                pass
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


async def heal_stale_outbound_unread(session: AsyncSession) -> int:
    """Clear unread when the last message is outbound (operator already replied)."""
    result = await session.execute(
        update(Dialog)
        .where(Dialog.unread > 0, Dialog.last_direction == "out")
        .values(unread=0)
        .returning(Dialog.id)
    )
    return len(result.all())


async def claim_if_unassigned(
    session: AsyncSession, dialog: Dialog, user_id: int
) -> bool:
    """First manager to reply on an unassigned appeal becomes responsible.

    Atomic: only one concurrent claim wins. Returns True if this user claimed.
    """
    result = await session.execute(
        update(Dialog)
        .where(Dialog.id == dialog.id, Dialog.assignee_id.is_(None))
        .values(assignee_id=user_id)
        .returning(Dialog.id)
    )
    claimed = result.scalar_one_or_none() is not None
    if claimed:
        dialog.assignee_id = user_id
    return claimed


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
