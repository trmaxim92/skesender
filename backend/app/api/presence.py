from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import PresenceStatus, PresenceStatusSlug, User
from app.presence import ensure_unique_slug, set_user_presence
from app.rbac import (
    SECTION_CHATS,
    SECTION_EMPLOYEES,
    SECTION_SETTINGS,
    load_user_rbac,
    require_permission,
    user_can,
)
from app.schemas import (
    PresenceEmployeeOut,
    PresenceStatusCreateRequest,
    PresenceStatusOut,
    PresenceStatusUpdateRequest,
    UserOut,
)
from app.serializers_user import presence_to_out, user_to_out

router = APIRouter(prefix="/presence", tags=["presence"])


class SetPresenceRequest(BaseModel):
    presence_status_id: int = Field(ge=1)


def _to_out(row: PresenceStatus) -> PresenceStatusOut:
    return PresenceStatusOut.model_validate(row)


@router.get("/statuses", response_model=list[PresenceStatusOut])
async def list_statuses(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PresenceStatusOut]:
    """Active statuses for the profile menu (any authenticated user)."""
    _ = user
    stmt = select(PresenceStatus).order_by(PresenceStatus.sort_order, PresenceStatus.id)
    if not include_inactive:
        stmt = stmt.where(PresenceStatus.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/statuses/manage", response_model=list[PresenceStatusOut])
async def list_statuses_manage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[PresenceStatusOut]:
    _ = user
    rows = (
        await db.execute(select(PresenceStatus).order_by(PresenceStatus.sort_order, PresenceStatus.id))
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("/statuses", response_model=PresenceStatusOut, status_code=status.HTTP_201_CREATED)
async def create_status(
    body: PresenceStatusCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> PresenceStatusOut:
    _ = user
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название")
    slug = await ensure_unique_slug(db, name)
    reserved = {s.value for s in PresenceStatusSlug}
    if slug in reserved:
        slug = await ensure_unique_slug(db, f"{name}-custom")
    row = PresenceStatus(
        name=name,
        slug=slug,
        color=body.color.strip() or "#9ca3af",
        sort_order=body.sort_order,
        is_system=False,
        is_active=body.is_active,
        participates_in_routing=body.participates_in_routing,
        can_write_chats=body.can_write_chats,
        on_duty=body.on_duty,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.patch("/statuses/{status_id}", response_model=PresenceStatusOut)
async def update_status(
    status_id: int,
    body: PresenceStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> PresenceStatusOut:
    _ = user
    row = await db.get(PresenceStatus, status_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Статус не найден")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Укажите название")
        row.name = name
        if not row.is_system:
            row.slug = await ensure_unique_slug(db, name, exclude_id=row.id)
    if body.color is not None:
        row.color = body.color.strip() or row.color
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    if body.participates_in_routing is not None:
        row.participates_in_routing = body.participates_in_routing
    if body.can_write_chats is not None:
        row.can_write_chats = body.can_write_chats
    if body.on_duty is not None:
        row.on_duty = body.on_duty
    if body.is_active is not None:
        if row.is_system and row.slug == PresenceStatusSlug.OFFLINE.value and not body.is_active:
            raise HTTPException(status_code=400, detail="Системный «Оффлайн» нельзя отключить")
        row.is_active = body.is_active
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_status(
    status_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> None:
    _ = user
    row = await db.get(PresenceStatus, status_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Статус не найден")
    if row.is_system:
        raise HTTPException(status_code=400, detail="Системный статус нельзя удалить")
    offline = (
        await db.execute(
            select(PresenceStatus).where(PresenceStatus.slug == PresenceStatusSlug.OFFLINE.value)
        )
    ).scalar_one_or_none()
    if offline is not None:
        await db.execute(
            update(User)
            .where(User.presence_status_id == row.id)
            .values(presence_status_id=offline.id)
        )
    else:
        await db.execute(
            update(User)
            .where(User.presence_status_id == row.id)
            .values(presence_status_id=None)
        )
    await db.delete(row)
    await db.commit()


@router.patch("/me", response_model=UserOut)
async def set_my_presence(
    body: SetPresenceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserOut:
    loaded = await load_user_rbac(db, user)
    row = await db.get(PresenceStatus, body.presence_status_id)
    if row is None or not row.is_active:
        raise HTTPException(status_code=400, detail="Статус недоступен")
    await set_user_presence(db, loaded, row)
    await db.commit()
    loaded = await load_user_rbac(db, loaded)
    return user_to_out(loaded)


@router.get("/employees", response_model=list[PresenceEmployeeOut])
async def list_employees_presence(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PresenceEmployeeOut]:
    loaded = await load_user_rbac(db, user)
    if not (user_can(loaded, SECTION_EMPLOYEES) or user_can(loaded, SECTION_CHATS)):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.presence_status),
            selectinload(User.access_role),
            selectinload(User.department_memberships),
        )
        .where(User.is_active.is_(True))
        .order_by(User.name)
    )
    items: list[PresenceEmployeeOut] = []
    for u in result.scalars().all():
        role = u.__dict__.get("access_role")
        memberships = u.__dict__.get("department_memberships") or []
        items.append(
            PresenceEmployeeOut(
                id=u.id,
                name=u.name,
                email=u.email,
                role_name=role.name if role else None,
                department_ids=[m.department_id for m in memberships],
                is_active=u.is_active,
                presence_status=presence_to_out(u.__dict__.get("presence_status")),
            )
        )
    return items
