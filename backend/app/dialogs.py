"""Dialog helpers shared by inbox adapters."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Channel,
    ChannelTransport,
    ChatMessage,
    Contact,
    ContactStatus,
    Dialog,
    MessageDirection,
    utcnow,
)

logger = logging.getLogger(__name__)

_MAX_FAMILY = (ChannelTransport.MAX.value, ChannelTransport.MAXBOT.value)


def _normalize_phone(raw: str | None) -> str:
    digits = re.sub(r"\D+", "", (raw or "").strip())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def format_contact_phone(raw: str | None) -> str | None:
    """Canonical +7… display form, or None if not a real phone."""
    if not raw or is_messenger_phone_key(raw):
        return None
    digits = _normalize_phone(raw)
    if len(digits) < 10:
        return None
    return f"+{digits}"


def messenger_family(transport: str | None) -> str | None:
    t = (transport or "").lower()
    if t in _MAX_FAMILY:
        return "max"
    if t in {ChannelTransport.TELEGRAM.value, ChannelTransport.TGAPI.value}:
        return "telegram"
    return None


def messenger_phone_key(family: str, external_user_id: str) -> str:
    """Synthetic Contact.phone when MAX/Telegram hide the real number."""
    return f"{family}:{external_user_id}"


def is_messenger_phone_key(phone: str | None) -> bool:
    raw = (phone or "").strip()
    if not raw or ":" not in raw:
        return False
    family, _, rest = raw.partition(":")
    return family in {"max", "telegram"} and bool(rest.strip())


def _family_transports(family: str) -> tuple[str, ...]:
    if family == "max":
        return _MAX_FAMILY
    if family == "telegram":
        return (ChannelTransport.TELEGRAM.value, ChannelTransport.TGAPI.value)
    return ()


async def _find_contact_by_messenger_id(
    session: AsyncSession,
    *,
    family: str,
    external_user_id: str,
) -> Contact | None:
    key = messenger_phone_key(family, external_user_id)
    by_key = (
        await session.execute(select(Contact).where(Contact.phone == key).limit(1))
    ).scalar_one_or_none()
    if by_key is not None:
        return by_key

    transports = _family_transports(family)
    if not transports:
        return None
    row = (
        await session.execute(
            select(Dialog.contact_id)
            .join(Channel, Channel.id == Dialog.channel_id)
            .where(
                Dialog.contact_external_id == external_user_id,
                Dialog.contact_id.is_not(None),
                Channel.transport.in_(transports),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return await session.get(Contact, int(row))


def _apply_contact_name(contact: Contact, dialog: Dialog) -> None:
    if dialog.contact_name and (
        not contact.name
        or contact.name == contact.phone
        or is_messenger_phone_key(contact.name)
        or contact.name.startswith("User ")
        or contact.name.startswith("Chat ")
    ):
        contact.name = dialog.contact_name


async def ensure_dialog_crm_contact(session: AsyncSession, dialog: Dialog) -> Contact | None:
    """Link dialog to a CRM Contact by phone and/or messenger user id.

    MAX often hides the phone. We still create/link a contact via
    ``max:{user_id}`` so personal-channel and bot threads stay one card.
    """
    channel = await session.get(Channel, dialog.channel_id)
    family = messenger_family(channel.transport if channel else None)
    external_id = (dialog.contact_external_id or "").strip()
    if external_id and external_id == (dialog.external_chat_id or "").strip():
        # Legacy personal MAX rows stored dialog chat id here — not a user id.
        if family == "max" and not external_id.startswith("-"):
            external_id = ""

    real_phone = format_contact_phone(dialog.contact_phone)
    if real_phone:
        dialog.contact_phone = real_phone
    elif dialog.contact_phone and not is_messenger_phone_key(dialog.contact_phone):
        # Garbage / too short — clear so the client card stays empty.
        dialog.contact_phone = None

    if real_phone and channel is not None:
        channel_phone = _normalize_phone(channel.identity)
        if len(channel_phone) >= 5 and channel_phone == _normalize_phone(real_phone):
            dialog.contact_phone = None
            real_phone = None

    contact: Contact | None = None
    if dialog.contact_id is not None:
        contact = await session.get(Contact, dialog.contact_id)

    if contact is None and real_phone:
        contact = (
            await session.execute(select(Contact).where(Contact.phone == real_phone).limit(1))
        ).scalar_one_or_none()

    if contact is None and family and external_id:
        contact = await _find_contact_by_messenger_id(
            session, family=family, external_user_id=external_id
        )

    if contact is None and not real_phone and not (family and external_id):
        return None

    if contact is None:
        phone_value = real_phone or messenger_phone_key(family or "max", external_id)
        contact = Contact(
            name=(dialog.contact_name or "").strip() or phone_value,
            phone=phone_value,
            status=ContactStatus.NEW.value,
            department_id=dialog.department_id,
        )
        session.add(contact)
        await session.flush()
    else:
        if real_phone and (
            is_messenger_phone_key(contact.phone) or not contact.phone
        ):
            # Upgrade synthetic key → real phone when MAX finally exposes it.
            taken = (
                await session.execute(
                    select(Contact.id).where(
                        Contact.phone == real_phone, Contact.id != contact.id
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if taken is None:
                contact.phone = real_phone
        if dialog.department_id and contact.department_id is None:
            contact.department_id = dialog.department_id
        _apply_contact_name(contact, dialog)

    dialog.contact_id = contact.id
    _apply_contact_name(contact, dialog)
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
    phone = format_contact_phone(contact_phone)
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
        if contact_external_id and (
            not dialog.contact_external_id
            or dialog.contact_external_id == dialog.external_chat_id
        ):
            dialog.contact_external_id = contact_external_id
        if phone and (
            not dialog.contact_phone or is_messenger_phone_key(dialog.contact_phone)
        ):
            dialog.contact_phone = phone
        try:
            await ensure_dialog_crm_contact(session, dialog)
        except Exception:
            logger.exception("ensure_dialog_crm_contact failed dialog=%s", dialog.id)
        return dialog

    dialog = Dialog(
        channel_id=channel.id,
        external_chat_id=external_chat_id,
        contact_external_id=contact_external_id,
        contact_name=contact_name or "Клиент",
        contact_username=contact_username,
        contact_avatar_url=contact_avatar_url,
        contact_phone=phone,
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
                logger.exception(
                    "ensure_dialog_crm_contact failed new dialog channel=%s chat=%s",
                    channel.id,
                    external_chat_id,
                )
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


async def clear_unread_after_outbound(
    session: AsyncSession,
    dialog: Dialog,
    *,
    outbound_at,
) -> bool:
    """Clear unread unless a newer inbound arrived during provider I/O.

    Reload last_* from DB so in-memory dialog is not stale after a concurrent ingest.
    """
    fresh = await session.get(Dialog, dialog.id)
    if fresh is None:
        return False
    dialog.unread = fresh.unread
    dialog.last_direction = fresh.last_direction
    dialog.last_at = fresh.last_at
    dialog.last_message = fresh.last_message
    dialog.last_status = fresh.last_status
    if (
        fresh.last_direction == MessageDirection.IN.value
        and fresh.last_at is not None
        and outbound_at is not None
        and fresh.last_at > outbound_at
    ):
        return False
    return await clear_unread(session, dialog)


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
