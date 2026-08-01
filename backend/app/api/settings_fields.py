from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.fields import field_def_to_out, list_field_definitions, make_field_key
from app.models import Department, FieldDefinition, FieldScope, User, utcnow
from app.rbac import ACTION_MANAGE_USERS, SECTION_SETTINGS, load_user_rbac, user_can
from app.schemas import (
    FieldDefinitionCreateRequest,
    FieldDefinitionOut,
    FieldDefinitionUpdateRequest,
)

router = APIRouter(prefix="/settings/fields", tags=["settings-fields"])


async def require_settings_access(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    loaded = await load_user_rbac(db, user)
    if user_can(loaded, SECTION_SETTINGS) or user_can(loaded, ACTION_MANAGE_USERS):
        return loaded
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


@router.get("", response_model=list[FieldDefinitionOut])
async def list_fields(
    scope: str = Query(..., pattern="^(client|appeal)$"),
    department_id: int | None = Query(default=None),
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_settings_access),
) -> list[FieldDefinitionOut]:
    if scope == FieldScope.APPEAL.value and department_id is None:
        raise HTTPException(status_code=400, detail="Укажите department_id для полей обращения")
    items = await list_field_definitions(
        db,
        scope=scope,
        department_id=department_id,
        active_only=not include_inactive,
    )
    return [field_def_to_out(x) for x in items]


@router.post("", response_model=FieldDefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_field(
    body: FieldDefinitionCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_settings_access),
) -> FieldDefinitionOut:
    if body.scope == FieldScope.APPEAL.value:
        if body.department_id is None:
            raise HTTPException(status_code=400, detail="Укажите department_id")
        dept = await db.get(Department, body.department_id)
        if dept is None:
            raise HTTPException(status_code=400, detail="Отдел не найден")
        department_id = body.department_id
    else:
        department_id = None

    key = make_field_key(body.label, body.key)
    existing = await list_field_definitions(
        db, scope=body.scope, department_id=department_id, active_only=False
    )
    if any(f.key == key for f in existing):
        raise HTTPException(status_code=400, detail=f"Поле с ключом «{key}» уже есть")

    fd = FieldDefinition(
        scope=body.scope,
        department_id=department_id,
        key=key,
        label=body.label.strip(),
        field_type=body.field_type,
        options_json=json.dumps(body.options, ensure_ascii=False) if body.options else None,
        required=body.required,
        sort_order=body.sort_order,
        is_system=False,
        is_active=True,
    )
    db.add(fd)
    await db.commit()
    await db.refresh(fd)
    return field_def_to_out(fd)


@router.patch("/{field_id}", response_model=FieldDefinitionOut)
async def update_field(
    field_id: int,
    body: FieldDefinitionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_settings_access),
) -> FieldDefinitionOut:
    fd = await db.get(FieldDefinition, field_id)
    if fd is None:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    if fd.is_system and body.field_type is not None and body.field_type != fd.field_type:
        raise HTTPException(status_code=400, detail="Тип системного поля нельзя менять")
    if body.label is not None:
        fd.label = body.label.strip()
    if body.field_type is not None and not fd.is_system:
        fd.field_type = body.field_type
    if body.options is not None:
        fd.options_json = json.dumps(body.options, ensure_ascii=False) if body.options else None
    if body.required is not None and not fd.is_system:
        fd.required = body.required
    if body.sort_order is not None:
        fd.sort_order = body.sort_order
    if body.is_active is not None:
        if fd.is_system and not body.is_active:
            raise HTTPException(status_code=400, detail="Системное поле нельзя отключить")
        fd.is_active = body.is_active
    fd.updated_at = utcnow()
    await db.commit()
    await db.refresh(fd)
    return field_def_to_out(fd)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_settings_access),
) -> None:
    fd = await db.get(FieldDefinition, field_id)
    if fd is None:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    if fd.is_system:
        raise HTTPException(status_code=400, detail="Системное поле нельзя удалить")
    await db.delete(fd)
    await db.commit()
