"""Appeal (обращение) helpers for dialog lifecycle."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Appeal, AppealStatus, Dialog, utcnow


async def ensure_open_appeal(session: AsyncSession, dialog: Dialog) -> Appeal:
    """Return the open appeal for dialog, or open a new one after close/missing.

    Opening a new appeal clears dialog assignee so the first manager who replies
    becomes responsible (chat goes to «Новые»).
    """
    current: Appeal | None = None
    if dialog.current_appeal_id is not None:
        current = await session.get(Appeal, dialog.current_appeal_id)
    if current is not None and current.status == AppealStatus.OPEN.value:
        return current

    max_number = await session.scalar(
        select(func.coalesce(func.max(Appeal.number), 0)).where(Appeal.dialog_id == dialog.id)
    )
    next_number = int(max_number or 0) + 1
    appeal = Appeal(
        dialog_id=dialog.id,
        number=next_number,
        status=AppealStatus.OPEN.value,
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
