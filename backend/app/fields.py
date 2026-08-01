from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments import slugify
from app.models import FieldDefinition, FieldScope, FieldValue, utcnow
from app.schemas import FieldDefinitionOut


def field_def_to_out(fd: FieldDefinition) -> FieldDefinitionOut:
    options: list[str] = []
    if fd.options_json:
        try:
            raw = json.loads(fd.options_json)
            if isinstance(raw, list):
                options = [str(x) for x in raw]
        except json.JSONDecodeError:
            options = []
    return FieldDefinitionOut(
        id=fd.id,
        scope=fd.scope,
        department_id=fd.department_id,
        key=fd.key,
        label=fd.label,
        field_type=fd.field_type,
        options=options,
        required=fd.required,
        sort_order=fd.sort_order,
        is_system=fd.is_system,
        is_active=fd.is_active,
    )


def make_field_key(label: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        key = re.sub(r"[^\w]+", "_", explicit.strip().lower()).strip("_")
        return key[:64] or "field"
    base = slugify(label).replace("-", "_")
    return (base or "field")[:64]


async def list_field_definitions(
    db: AsyncSession,
    *,
    scope: str,
    department_id: int | None = None,
    active_only: bool = True,
) -> list[FieldDefinition]:
    stmt = select(FieldDefinition).where(FieldDefinition.scope == scope)
    if scope == FieldScope.CLIENT.value:
        stmt = stmt.where(FieldDefinition.department_id.is_(None))
    else:
        if department_id is None:
            return []
        stmt = stmt.where(FieldDefinition.department_id == department_id)
    if active_only:
        stmt = stmt.where(FieldDefinition.is_active.is_(True))
    stmt = stmt.order_by(FieldDefinition.sort_order.asc(), FieldDefinition.id.asc())
    return list((await db.execute(stmt)).scalars().all())


async def load_field_values(
    db: AsyncSession, *, scope: str, owner_id: int
) -> dict[str, str]:
    result = await db.execute(
        select(FieldValue).where(FieldValue.scope == scope, FieldValue.owner_id == owner_id)
    )
    return {fv.field_key: fv.value_text for fv in result.scalars().all()}


async def upsert_field_value(
    db: AsyncSession, *, scope: str, owner_id: int, field_key: str, value: str
) -> None:
    existing = (
        await db.execute(
            select(FieldValue).where(
                FieldValue.scope == scope,
                FieldValue.owner_id == owner_id,
                FieldValue.field_key == field_key,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            FieldValue(
                scope=scope,
                owner_id=owner_id,
                field_key=field_key,
                value_text=value,
                updated_at=utcnow(),
            )
        )
    else:
        existing.value_text = value
        existing.updated_at = utcnow()
