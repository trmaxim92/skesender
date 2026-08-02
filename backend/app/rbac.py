from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import AccessRole, Role, RoleChannel, RolePermission, User, UserChannel

# Permission codes
SECTION_CHATS = "section.chats"
SECTION_APPEALS = "section.appeals"
SECTION_MAILING = "section.mailing"
SECTION_CHANNELS = "section.channels"
SECTION_EMPLOYEES = "section.employees"
SECTION_TEMPLATES = "section.templates"
SECTION_WEBHOOKS = "section.webhooks"
SECTION_SETTINGS = "section.settings"
ACTION_WRITE = "action.write"
ACTION_MANAGE_CHANNELS = "action.manage_channels"
ACTION_MANAGE_USERS = "action.manage_users"
ACTION_DELETE_APPEALS = "action.delete_appeals"

ALL_PERMISSIONS: tuple[str, ...] = (
    SECTION_CHATS,
    SECTION_APPEALS,
    SECTION_MAILING,
    SECTION_CHANNELS,
    SECTION_EMPLOYEES,
    SECTION_WEBHOOKS,
    SECTION_SETTINGS,
    ACTION_WRITE,
    ACTION_MANAGE_CHANNELS,
    ACTION_MANAGE_USERS,
    ACTION_DELETE_APPEALS,
)

SECTION_LABELS: dict[str, str] = {
    SECTION_CHATS: "Чаты",
    SECTION_APPEALS: "Обращения",
    SECTION_MAILING: "Рассылки",
    SECTION_CHANNELS: "Раздел «Каналы» (настройки)",
    SECTION_EMPLOYEES: "Сотрудники",
    SECTION_TEMPLATES: "Шаблоны (устарело)",
    SECTION_WEBHOOKS: "Webhooks",
    SECTION_SETTINGS: "Настройки",
    ACTION_WRITE: "Запись (ответы, рассылки)",
    ACTION_MANAGE_CHANNELS: "Управление каналами",
    ACTION_MANAGE_USERS: "Управление сотрудниками и ролями",
    ACTION_DELETE_APPEALS: "Удаление обращений",
}

LEGACY_PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN.value: set(ALL_PERMISSIONS),
    Role.OPERATOR.value: {
        SECTION_CHATS,
        SECTION_APPEALS,
        SECTION_MAILING,
        ACTION_WRITE,
    },
    Role.VIEWER.value: {
        SECTION_CHATS,
        SECTION_APPEALS,
    },
}

SYSTEM_ROLE_DEFS: tuple[dict, ...] = (
    {
        "slug": "admin",
        "name": "Админ",
        "all_channels": True,
        "permissions": list(ALL_PERMISSIONS),
    },
    {
        "slug": "operator",
        "name": "Оператор",
        # Dialog ACL is separate from the Channels settings section.
        "all_channels": True,
        "permissions": [
            SECTION_CHATS,
            SECTION_APPEALS,
            SECTION_MAILING,
            ACTION_WRITE,
        ],
    },
    {
        "slug": "viewer",
        "name": "Наблюдатель",
        "all_channels": False,
        "permissions": [SECTION_CHATS, SECTION_APPEALS],
    },
)


def _legacy_permissions(user: User) -> set[str]:
    return set(LEGACY_PERMISSIONS.get(user.role, LEGACY_PERMISSIONS[Role.OPERATOR.value]))


def user_permissions(user: User) -> set[str]:
    role = getattr(user, "access_role", None)
    if role is not None:
        return {p.code for p in (role.permissions or [])}
    return _legacy_permissions(user)


def user_can(user: User, code: str) -> bool:
    return code in user_permissions(user)


def role_all_channels(user: User) -> bool:
    role = getattr(user, "access_role", None)
    if role is not None:
        return bool(role.all_channels)
    return user.role == Role.ADMIN.value


async def accessible_channel_ids(user: User, db: AsyncSession) -> list[int] | None:
    """None means all channels. Channel ACL comes from the access role."""
    if role_all_channels(user):
        return None
    role = getattr(user, "access_role", None)
    if role is not None:
        if "channel_access" in (role.__dict__ or {}):
            ids = [rc.channel_id for rc in (role.channel_access or [])]
        else:
            result = await db.execute(
                select(RoleChannel.channel_id).where(RoleChannel.role_id == role.id)
            )
            ids = list(result.scalars().all())
        if ids:
            return ids
    # Legacy fallback: per-user ACL (until migrated to role)
    if "channel_access" not in (user.__dict__ or {}):
        result = await db.execute(
            select(UserChannel.channel_id).where(UserChannel.user_id == user.id)
        )
        return list(result.scalars().all())
    return [uc.channel_id for uc in (user.channel_access or [])]


async def load_user_rbac(db: AsyncSession, user: User) -> User:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.access_role).selectinload(AccessRole.permissions),
            selectinload(User.access_role).selectinload(AccessRole.channel_access),
            selectinload(User.channel_access),
            selectinload(User.department_memberships),
        )
        .where(User.id == user.id)
    )
    loaded = result.scalar_one()
    return loaded


def require_permission(code: str):
    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        loaded = await load_user_rbac(db, user)
        if not user_can(loaded, code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return loaded

    return _dep


async def ensure_channel_access(user: User, channel_id: int, db: AsyncSession) -> None:
    ids = await accessible_channel_ids(user, db)
    if ids is not None and channel_id not in ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к каналу")


async def seed_access_roles(session: AsyncSession) -> dict[str, AccessRole]:
    """Create system roles if missing; sync missing permissions for system roles."""
    by_slug: dict[str, AccessRole] = {}
    for spec in SYSTEM_ROLE_DEFS:
        result = await session.execute(select(AccessRole).where(AccessRole.slug == spec["slug"]))
        role = result.scalar_one_or_none()
        if role is None:
            role = AccessRole(
                name=spec["name"],
                slug=spec["slug"],
                is_system=True,
                all_channels=spec["all_channels"],
            )
            session.add(role)
            await session.flush()
            for code in spec["permissions"]:
                session.add(RolePermission(role_id=role.id, code=code))
        else:
            # Keep all_channels in sync with system role defs (operator: True).
            role.all_channels = bool(spec["all_channels"])
            existing = (
                await session.execute(
                    select(RolePermission.code).where(RolePermission.role_id == role.id)
                )
            ).scalars().all()
            have = set(existing)
            wanted = set(spec["permissions"])
            for code in wanted:
                if code not in have:
                    session.add(RolePermission(role_id=role.id, code=code))
            # Narrow remove: drop rights that no longer belong on this system role.
            # Custom roles are never touched (they have different slug / is_system=False).
            obsolete = have - wanted
            if obsolete and role.is_system and role.slug == "operator":
                drop = obsolete & {SECTION_CHANNELS, SECTION_TEMPLATES}
                if drop:
                    await session.execute(
                        delete(RolePermission).where(
                            RolePermission.role_id == role.id,
                            RolePermission.code.in_(drop),
                        )
                    )
        by_slug[spec["slug"]] = role
    await session.flush()
    return by_slug


async def migrate_users_to_access_roles(
    session: AsyncSession, by_slug: dict[str, AccessRole]
) -> None:
    result = await session.execute(select(User).where(User.access_role_id.is_(None)))
    for user in result.scalars().all():
        slug = user.role if user.role in by_slug else Role.OPERATOR.value
        user.access_role_id = by_slug[slug].id
