"""Appeal (обращение) helpers for dialog lifecycle and contact outreach."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.appeal_statuses import (
    apply_status_def_to_appeal,
    get_default_closed_status,
    get_default_open_status,
)
from app.models import Appeal, AppealStatus, Contact, Dialog, utcnow


async def ensure_open_appeal(session: AsyncSession, dialog: Dialog) -> Appeal:
    """Return the open appeal for dialog, or open a new one after close/missing.

    Opening a new appeal clears dialog assignee so the first manager who replies
    becomes responsible (chat goes to «Новые»).
    """
    # C11: serialize open-appeal creation per dialog (Postgres advisory xact lock).
    if dialog.id is not None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :k)"),
            {"ns": 0x41505045, "k": int(dialog.id)},  # 'APPE'
        )
        await session.refresh(dialog)

    current: Appeal | None = None
    if dialog.current_appeal_id is not None:
        current = await session.get(
            Appeal,
            dialog.current_appeal_id,
            options=(selectinload(Appeal.status_def),),
        )
    if current is not None and current.status == AppealStatus.OPEN.value:
        if current.status_id is None:
            open_status = await get_default_open_status(session)
            apply_status_def_to_appeal(current, open_status)
            await session.flush()
        return current

    open_status = await get_default_open_status(session)
    max_number = await session.scalar(
        select(func.coalesce(func.max(Appeal.number), 0)).where(Appeal.dialog_id == dialog.id)
    )
    next_number = int(max_number or 0) + 1
    appeal = Appeal(
        dialog_id=dialog.id,
        number=next_number,
        status=AppealStatus.OPEN.value,
        status_id=open_status.id,
        opened_at=utcnow(),
    )
    try:
        async with session.begin_nested():
            session.add(appeal)
            await session.flush()
            dialog.current_appeal_id = appeal.id
            # Новое обращение — снова без ответственного, пока кто-то не ответит первым.
            dialog.assignee_id = None
            await session.flush()
    except IntegrityError:
        # Concurrent open of the same next number — reuse whatever is open now.
        if dialog.current_appeal_id is not None:
            current = await session.get(Appeal, dialog.current_appeal_id)
            if current is not None and current.status == AppealStatus.OPEN.value:
                return current
        result = await session.execute(
            select(Appeal)
            .where(
                Appeal.dialog_id == dialog.id,
                Appeal.status == AppealStatus.OPEN.value,
            )
            .order_by(Appeal.number.desc())
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        dialog.current_appeal_id = existing.id
        return existing
    return appeal


async def ensure_contact_appeal(session: AsyncSession, contact: Contact) -> Appeal:
    """Return open (counts_as_open) appeal for contact, or create a phone-only one."""
    result = await session.execute(
        select(Appeal)
        .options(selectinload(Appeal.status_def))
        .where(
            Appeal.contact_id == contact.id,
            Appeal.status == AppealStatus.OPEN.value,
        )
        .order_by(Appeal.id.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        # Prefer status_def.counts_as_open when available.
        if existing.status_def is None or existing.status_def.counts_as_open:
            if existing.status_id is None:
                open_status = await get_default_open_status(session)
                apply_status_def_to_appeal(existing, open_status)
                await session.flush()
            return existing

    open_status = await get_default_open_status(session)
    max_number = await session.scalar(
        select(func.coalesce(func.max(Appeal.number), 0)).where(Appeal.contact_id == contact.id)
    )
    next_number = int(max_number or 0) + 1
    appeal = Appeal(
        dialog_id=None,
        contact_id=contact.id,
        number=next_number,
        status=AppealStatus.OPEN.value,
        status_id=open_status.id,
        opened_at=utcnow(),
    )
    session.add(appeal)
    await session.flush()
    return appeal


async def close_appeal_with_status(
    session: AsyncSession,
    appeal: Appeal,
    *,
    closed_by_id: int | None = None,
) -> Appeal:
    closed_status = await get_default_closed_status(session)
    apply_status_def_to_appeal(appeal, closed_status, closed_by_id=closed_by_id)
    await session.flush()
    return appeal


async def get_current_appeal(session: AsyncSession, dialog: Dialog) -> Appeal | None:
    if dialog.current_appeal_id is None:
        return None
    return await session.get(Appeal, dialog.current_appeal_id)


async def load_dialog_with_appeal(session: AsyncSession, dialog_id: int) -> Dialog | None:
    result = await session.execute(
        select(Dialog)
        .options(
            selectinload(Dialog.channel),
            selectinload(Dialog.current_appeal),
            selectinload(Dialog.assignee),
        )
        .where(Dialog.id == dialog_id)
    )
    return result.scalar_one_or_none()
