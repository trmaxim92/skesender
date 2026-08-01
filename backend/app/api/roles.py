from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import AccessRole, RoleChannel, RolePermission, User
from app.rbac import (
    ACTION_MANAGE_USERS,
    ALL_PERMISSIONS,
    SECTION_LABELS,
    require_permission,
)
from app.schemas import (
    AccessRoleCreateRequest,
    AccessRoleOut,
    AccessRoleUpdateRequest,
    PermissionCatalogItem,
)

router = APIRouter(prefix="/roles", tags=["roles"])

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    base = _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "role"
    return base[:60]


def _role_out(role: AccessRole) -> AccessRoleOut:
    return AccessRoleOut(
        id=role.id,
        name=role.name,
        slug=role.slug,
        is_system=role.is_system,
        all_channels=role.all_channels,
        permissions=sorted({p.code for p in (role.permissions or [])}),
        channel_ids=[] if role.all_channels else [rc.channel_id for rc in (role.channel_access or [])],
        created_at=role.created_at,
    )


async def _load_role(db: AsyncSession, role_id: int) -> AccessRole | None:
    return (
        await db.execute(
            select(AccessRole)
            .options(
                selectinload(AccessRole.permissions),
                selectinload(AccessRole.channel_access),
            )
            .where(AccessRole.id == role_id)
        )
    ).scalar_one_or_none()


async def _set_role_channels(db: AsyncSession, role_id: int, channel_ids: list[int]) -> None:
    await db.execute(delete(RoleChannel).where(RoleChannel.role_id == role_id))
    await db.flush()
    for cid in channel_ids:
        db.add(RoleChannel(role_id=role_id, channel_id=cid))


@router.get("/permissions", response_model=list[PermissionCatalogItem])
async def permission_catalog(
    _: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> list[PermissionCatalogItem]:
    return [PermissionCatalogItem(code=c, label=SECTION_LABELS.get(c, c)) for c in ALL_PERMISSIONS]


@router.get("", response_model=list[AccessRoleOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> list[AccessRoleOut]:
    result = await db.execute(
        select(AccessRole)
        .options(
            selectinload(AccessRole.permissions),
            selectinload(AccessRole.channel_access),
        )
        .order_by(AccessRole.id.asc())
    )
    return [_role_out(r) for r in result.scalars().all()]


@router.post("", response_model=AccessRoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: AccessRoleCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> AccessRoleOut:
    name = body.name.strip()
    slug = _slugify(name)
    exists = await db.execute(select(AccessRole).where(AccessRole.slug == slug))
    if exists.scalar_one_or_none():
        slug = f"{slug}-{int(__import__('time').time()) % 100000}"

    codes = [c for c in body.permissions if c in ALL_PERMISSIONS]
    role = AccessRole(
        name=name,
        slug=slug,
        is_system=False,
        all_channels=body.all_channels,
    )
    db.add(role)
    await db.flush()
    for code in codes:
        db.add(RolePermission(role_id=role.id, code=code))
    if not body.all_channels and body.channel_ids:
        await _set_role_channels(db, role.id, body.channel_ids)
    await db.commit()
    loaded = await _load_role(db, role.id)
    assert loaded is not None
    return _role_out(loaded)


@router.patch("/{role_id}", response_model=AccessRoleOut)
async def update_role(
    role_id: int,
    body: AccessRoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> AccessRoleOut:
    role = await _load_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")

    if body.name is not None:
        role.name = body.name.strip()
    if body.all_channels is not None:
        role.all_channels = body.all_channels
        if body.all_channels:
            await _set_role_channels(db, role.id, [])
    if body.permissions is not None:
        codes = {c for c in body.permissions if c in ALL_PERMISSIONS}
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        await db.flush()
        for code in codes:
            db.add(RolePermission(role_id=role.id, code=code))
    if body.channel_ids is not None and not (body.all_channels if body.all_channels is not None else role.all_channels):
        await _set_role_channels(db, role.id, body.channel_ids)

    await db.commit()
    loaded = await _load_role(db, role_id)
    assert loaded is not None
    return _role_out(loaded)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> None:
    role = await db.get(AccessRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Системную роль нельзя удалить")
    users = (
        await db.execute(select(User.id).where(User.access_role_id == role_id).limit(1))
    ).scalar_one_or_none()
    if users is not None:
        raise HTTPException(status_code=400, detail="Роль назначена сотрудникам")
    await db.delete(role)
    await db.commit()
