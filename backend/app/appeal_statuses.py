"""Appeal workflow status catalog — configurable labels for contact/chat appeals."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments import slugify
from app.models import AppealStatus, AppealStatusDef, AppealStatusSlug


DEFAULT_APPEAL_STATUSES: tuple[dict, ...] = (
    {
        "name": "Новое",
        "slug": AppealStatusSlug.NEW.value,
        "color": "#1a6dff",
        "sort_order": 10,
        "is_system": True,
        "is_terminal": False,
        "needs_callback": False,
        "counts_as_open": True,
    },
    {
        "name": "В работе",
        "slug": AppealStatusSlug.IN_WORK.value,
        "color": "#f79009",
        "sort_order": 20,
        "is_system": True,
        "is_terminal": False,
        "needs_callback": False,
        "counts_as_open": True,
    },
    {
        "name": "Нет ответа",
        "slug": AppealStatusSlug.NO_ANSWER.value,
        "color": "#667085",
        "sort_order": 30,
        "is_system": True,
        "is_terminal": False,
        "needs_callback": True,
        "counts_as_open": True,
    },
    {
        "name": "Перезвонить",
        "slug": AppealStatusSlug.CALLBACK.value,
        "color": "#f97316",
        "sort_order": 40,
        "is_system": True,
        "is_terminal": False,
        "needs_callback": True,
        "counts_as_open": True,
    },
    {
        "name": "Отказ",
        "slug": AppealStatusSlug.REJECTED.value,
        "color": "#f04438",
        "sort_order": 50,
        "is_system": True,
        "is_terminal": True,
        "needs_callback": False,
        "counts_as_open": False,
    },
    {
        "name": "Согласие",
        "slug": AppealStatusSlug.AGREED.value,
        "color": "#12b76a",
        "sort_order": 60,
        "is_system": True,
        "is_terminal": False,
        "needs_callback": False,
        "counts_as_open": True,
    },
    {
        "name": "Закрыто",
        "slug": AppealStatusSlug.CLOSED.value,
        "color": "#9ca3af",
        "sort_order": 70,
        "is_system": True,
        "is_terminal": True,
        "needs_callback": False,
        "counts_as_open": False,
    },
)


async def seed_appeal_statuses(session: AsyncSession) -> dict[str, AppealStatusDef]:
    by_slug: dict[str, AppealStatusDef] = {}
    result = await session.execute(select(AppealStatusDef))
    for row in result.scalars().all():
        by_slug[row.slug] = row
    for spec in DEFAULT_APPEAL_STATUSES:
        existing = by_slug.get(spec["slug"])
        if existing is None:
            row = AppealStatusDef(**spec)
            session.add(row)
            await session.flush()
            by_slug[row.slug] = row
        else:
            if not existing.is_system:
                existing.is_system = True
    await session.flush()
    return by_slug


async def get_appeal_status_by_slug(
    session: AsyncSession, slug: str
) -> AppealStatusDef | None:
    result = await session.execute(
        select(AppealStatusDef).where(AppealStatusDef.slug == slug)
    )
    return result.scalar_one_or_none()


async def get_default_open_status(session: AsyncSession) -> AppealStatusDef:
    row = await get_appeal_status_by_slug(session, AppealStatusSlug.NEW.value)
    if row is None:
        by_slug = await seed_appeal_statuses(session)
        row = by_slug.get(AppealStatusSlug.NEW.value)
    if row is None:
        raise RuntimeError("Appeal status «new» is missing")
    return row


async def get_default_closed_status(session: AsyncSession) -> AppealStatusDef:
    row = await get_appeal_status_by_slug(session, AppealStatusSlug.CLOSED.value)
    if row is None:
        by_slug = await seed_appeal_statuses(session)
        row = by_slug.get(AppealStatusSlug.CLOSED.value)
    if row is None:
        raise RuntimeError("Appeal status «closed» is missing")
    return row


async def ensure_unique_appeal_status_slug(
    session: AsyncSession, name: str, *, exclude_id: int | None = None
) -> str:
    base = slugify(name) or "status"
    candidate = base
    n = 2
    while True:
        stmt = select(AppealStatusDef).where(AppealStatusDef.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(AppealStatusDef.id != exclude_id)
        conflict = (await session.execute(stmt)).scalar_one_or_none()
        if conflict is None:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


def apply_status_def_to_appeal(appeal, status_def: AppealStatusDef, *, closed_by_id: int | None = None) -> None:
    """Sync legacy open/closed field from catalog flags."""
    from app.models import utcnow

    appeal.status_id = status_def.id
    appeal.status_def = status_def
    if status_def.is_terminal or not status_def.counts_as_open:
        appeal.status = AppealStatus.CLOSED.value
        if appeal.closed_at is None:
            appeal.closed_at = utcnow()
        if closed_by_id is not None:
            appeal.closed_by_id = closed_by_id
    else:
        appeal.status = AppealStatus.OPEN.value
        appeal.closed_at = None
        appeal.closed_by_id = None
