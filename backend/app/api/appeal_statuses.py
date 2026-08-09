"""CRUD for configurable appeal workflow statuses."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.appeal_statuses import ensure_unique_appeal_status_slug
from app.db import get_db
from app.deps import get_current_user
from app.models import Appeal, AppealStatusDef, AppealStatusSlug, User
from app.rbac import SECTION_CHATS, SECTION_CONTACTS, SECTION_SETTINGS, require_permission, user_can
from app.schemas import (
    AppealStatusDefCreateRequest,
    AppealStatusDefOut,
    AppealStatusDefUpdateRequest,
)

router = APIRouter(prefix="/appeal-statuses", tags=["appeal-statuses"])


def _to_out(row: AppealStatusDef) -> AppealStatusDefOut:
    return AppealStatusDefOut.model_validate(row)


@router.get("", response_model=list[AppealStatusDefOut])
async def list_statuses(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[AppealStatusDefOut]:
    _ = user
    stmt = select(AppealStatusDef).order_by(AppealStatusDef.sort_order, AppealStatusDef.id)
    if not include_inactive:
        stmt = stmt.where(AppealStatusDef.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/manage", response_model=list[AppealStatusDefOut])
async def list_statuses_manage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[AppealStatusDefOut]:
    _ = user
    rows = (
        await db.execute(
            select(AppealStatusDef).order_by(AppealStatusDef.sort_order, AppealStatusDef.id)
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/active", response_model=list[AppealStatusDefOut])
async def list_active_statuses(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AppealStatusDefOut]:
    if not (user_can(user, SECTION_CONTACTS) or user_can(user, SECTION_CHATS) or user_can(user, SECTION_SETTINGS)):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    rows = (
        await db.execute(
            select(AppealStatusDef)
            .where(AppealStatusDef.is_active.is_(True))
            .order_by(AppealStatusDef.sort_order, AppealStatusDef.id)
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=AppealStatusDefOut, status_code=status.HTTP_201_CREATED)
async def create_status(
    body: AppealStatusDefCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> AppealStatusDefOut:
    _ = user
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название")
    slug = await ensure_unique_appeal_status_slug(db, name)
    reserved = {s.value for s in AppealStatusSlug}
    if slug in reserved:
        slug = await ensure_unique_appeal_status_slug(db, f"{name}-custom")
    counts_as_open = body.counts_as_open
    if body.is_terminal:
        counts_as_open = False
    row = AppealStatusDef(
        name=name,
        slug=slug,
        color=body.color.strip() or "#9ca3af",
        sort_order=body.sort_order,
        is_system=False,
        is_active=body.is_active,
        is_terminal=body.is_terminal,
        needs_callback=body.needs_callback,
        counts_as_open=counts_as_open,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.patch("/{status_id}", response_model=AppealStatusDefOut)
async def update_status(
    status_id: int,
    body: AppealStatusDefUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> AppealStatusDefOut:
    _ = user
    row = await db.get(AppealStatusDef, status_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Статус не найден")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Укажите название")
        row.name = name
        if not row.is_system:
            row.slug = await ensure_unique_appeal_status_slug(db, name, exclude_id=row.id)
    if body.color is not None:
        row.color = body.color.strip() or row.color
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    if body.is_terminal is not None:
        row.is_terminal = body.is_terminal
        if body.is_terminal:
            row.counts_as_open = False
    if body.needs_callback is not None:
        row.needs_callback = body.needs_callback
    if body.counts_as_open is not None and not (body.is_terminal or row.is_terminal):
        row.counts_as_open = body.counts_as_open
    if body.is_active is not None:
        if row.is_system and row.slug == AppealStatusSlug.NEW.value and not body.is_active:
            raise HTTPException(status_code=400, detail="Системный «Новое» нельзя отключить")
        row.is_active = body.is_active
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/{status_id}")
async def delete_status(
    status_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> Response:
    _ = user
    row = await db.get(AppealStatusDef, status_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Статус не найден")
    if row.is_system:
        raise HTTPException(status_code=400, detail="Системный статус нельзя удалить")
    fallback = (
        await db.execute(
            select(AppealStatusDef).where(AppealStatusDef.slug == AppealStatusSlug.NEW.value)
        )
    ).scalar_one_or_none()
    if fallback is not None:
        await db.execute(
            update(Appeal).where(Appeal.status_id == row.id).values(status_id=fallback.id)
        )
    else:
        await db.execute(update(Appeal).where(Appeal.status_id == row.id).values(status_id=None))
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
