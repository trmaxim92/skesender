"""Presence status helpers — runtime overlay over role permissions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments import slugify
from app.models import PresenceStatus, PresenceStatusSlug, User


DEFAULT_STATUSES: tuple[dict, ...] = (
    {
        "name": "На линии",
        "slug": PresenceStatusSlug.ONLINE.value,
        "color": "#22c55e",
        "sort_order": 10,
        "is_system": True,
        "participates_in_routing": True,
        "can_write_chats": True,
        "on_duty": True,
    },
    {
        "name": "Обучение",
        "slug": PresenceStatusSlug.TRAINING.value,
        "color": "#f97316",
        "sort_order": 20,
        "is_system": True,
        "participates_in_routing": False,
        "can_write_chats": False,
        "on_duty": True,
    },
    {
        "name": "Оффлайн",
        "slug": PresenceStatusSlug.OFFLINE.value,
        "color": "#9ca3af",
        "sort_order": 30,
        "is_system": True,
        "participates_in_routing": False,
        "can_write_chats": False,
        "on_duty": False,
    },
)


async def seed_presence_statuses(session: AsyncSession) -> dict[str, PresenceStatus]:
    by_slug: dict[str, PresenceStatus] = {}
    result = await session.execute(select(PresenceStatus))
    for row in result.scalars().all():
        by_slug[row.slug] = row
    for spec in DEFAULT_STATUSES:
        existing = by_slug.get(spec["slug"])
        if existing is None:
            row = PresenceStatus(**spec)
            session.add(row)
            await session.flush()
            by_slug[row.slug] = row
        else:
            # Keep admin customizations; only ensure system flag for reserved slugs.
            if not existing.is_system:
                existing.is_system = True
    await session.flush()
    return by_slug


async def get_status_by_slug(session: AsyncSession, slug: str) -> PresenceStatus | None:
    result = await session.execute(select(PresenceStatus).where(PresenceStatus.slug == slug))
    return result.scalar_one_or_none()


async def ensure_unique_slug(
    session: AsyncSession, name: str, *, exclude_id: int | None = None
) -> str:
    base = slugify(name) or "status"
    candidate = base
    n = 2
    while True:
        stmt = select(PresenceStatus).where(PresenceStatus.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(PresenceStatus.id != exclude_id)
        conflict = (await session.execute(stmt)).scalar_one_or_none()
        if conflict is None:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


def presence_allows_write(user: User) -> bool:
    status = user.__dict__.get("presence_status")
    if status is None:
        return True
    return bool(status.can_write_chats)


def presence_participates_in_routing(user: User) -> bool:
    status = user.__dict__.get("presence_status")
    if status is None:
        return False
    return bool(status.participates_in_routing) and bool(status.is_active)


async def set_user_presence(
    session: AsyncSession, user: User, status: PresenceStatus
) -> User:
    user.presence_status_id = status.id
    user.presence_status = status
    await session.flush()
    return user
