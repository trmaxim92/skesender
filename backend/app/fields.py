from __future__ import annotations

import json
import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments import slugify
from app.models import FieldDefinition, FieldScope, FieldValue, FieldValueHistory, utcnow
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


def _is_empty_value(value: str | None, field_type: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True
    if field_type == "bool" and raw.lower() in {"false", "0", "no", "нет"}:
        return True
    return False


async def list_field_definitions(
    db: AsyncSession,
    *,
    scope: str,
    department_id: int | None = None,
    active_only: bool = True,
) -> list[FieldDefinition]:
    """Load field defs for a scope.

    Client scope: always includes global (department_id IS NULL) fields.
    When department_id is set, also includes that department's extra client fields.
    Appeal scope: requires department_id (department-specific set only).
    """
    stmt = select(FieldDefinition).where(FieldDefinition.scope == scope)
    if scope == FieldScope.CLIENT.value:
        if department_id is None:
            stmt = stmt.where(FieldDefinition.department_id.is_(None))
        else:
            stmt = stmt.where(
                (FieldDefinition.department_id.is_(None))
                | (FieldDefinition.department_id == department_id)
            )
    else:
        if department_id is None:
            return []
        stmt = stmt.where(FieldDefinition.department_id == department_id)
    if active_only:
        stmt = stmt.where(FieldDefinition.is_active.is_(True))
    stmt = stmt.order_by(
        FieldDefinition.is_system.desc(),
        FieldDefinition.department_id.asc().nulls_first(),
        FieldDefinition.sort_order.asc(),
        FieldDefinition.id.asc(),
    )
    return list((await db.execute(stmt)).scalars().all())


async def load_field_values(
    db: AsyncSession, *, scope: str, owner_id: int
) -> dict[str, str]:
    result = await db.execute(
        select(FieldValue).where(FieldValue.scope == scope, FieldValue.owner_id == owner_id)
    )
    return {fv.field_key: fv.value_text for fv in result.scalars().all()}


async def upsert_field_value(
    db: AsyncSession,
    *,
    scope: str,
    owner_id: int,
    field_key: str,
    value: str,
    changed_by_id: int | None = None,
    source: str = "user",
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
    new_text = value if value is not None else ""
    old_text = existing.value_text if existing is not None else ""
    if existing is None:
        db.add(
            FieldValue(
                scope=scope,
                owner_id=owner_id,
                field_key=field_key,
                value_text=new_text,
                updated_at=utcnow(),
            )
        )
    else:
        if existing.value_text == new_text:
            return
        existing.value_text = new_text
        existing.updated_at = utcnow()

    if old_text != new_text:
        db.add(
            FieldValueHistory(
                scope=scope,
                owner_id=owner_id,
                field_key=field_key,
                old_value=old_text,
                new_value=new_text,
                changed_by_id=changed_by_id,
                source=source,
                created_at=utcnow(),
            )
        )


async def missing_required_labels(
    defs: list[FieldDefinition],
    values: dict[str, str],
    *,
    skip_system_keys: set[str] | None = None,
) -> list[str]:
    skip = skip_system_keys or set()
    missing: list[str] = []
    for fd in defs:
        if not fd.required or not fd.is_active:
            continue
        if fd.key in skip:
            continue
        if _is_empty_value(values.get(fd.key), fd.field_type):
            missing.append(fd.label or fd.key)
    return missing


async def assert_required_filled(
    db: AsyncSession,
    *,
    department_id: int | None,
    client_owner_scope: str,
    client_owner_id: int,
    appeal_id: int | None,
    client_overrides: dict[str, str] | None = None,
) -> None:
    """Raise 400 listing missing required fields for close / terminal stage."""
    client_defs = await list_field_definitions(
        db, scope=FieldScope.CLIENT.value, department_id=department_id
    )
    client_values = await load_field_values(
        db, scope=client_owner_scope, owner_id=client_owner_id
    )
    if client_overrides:
        client_values = {**client_values, **client_overrides}

    missing = await missing_required_labels(
        client_defs,
        client_values,
        skip_system_keys={"full_name", "phone", "external_id"},
    )
    # System full_name / phone live on owner columns — callers pass them in overrides.
    for fd in client_defs:
        if not fd.required or not fd.is_system:
            continue
        if fd.key == "full_name" and _is_empty_value(client_values.get("full_name"), "text"):
            missing.append(fd.label or "ФИО")
        if fd.key == "phone" and _is_empty_value(client_values.get("phone"), "phone"):
            missing.append(fd.label or "Телефон")

    if appeal_id is not None and department_id is not None:
        appeal_defs = await list_field_definitions(
            db, scope=FieldScope.APPEAL.value, department_id=department_id
        )
        appeal_values = await load_field_values(
            db, scope=FieldScope.APPEAL.value, owner_id=appeal_id
        )
        missing.extend(await missing_required_labels(appeal_defs, appeal_values))

    # Dedupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for label in missing:
        if label in seen:
            continue
        seen.add(label)
        ordered.append(label)
    if ordered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Заполните обязательные поля: {', '.join(ordered)}",
        )


async def migrate_contact_appeal_values_to_appeal(
    db: AsyncSession,
    *,
    contact_id: int,
    appeal_id: int,
    clear_legacy: bool = False,
) -> dict[str, str]:
    """Copy legacy contact_appeal values onto the appeal row.

    Returns the merged appeal values after copy.
    """
    legacy = await load_field_values(
        db, scope=FieldScope.CONTACT_APPEAL.value, owner_id=contact_id
    )
    current = await load_field_values(db, scope=FieldScope.APPEAL.value, owner_id=appeal_id)
    if not legacy:
        return current
    for key, value in legacy.items():
        if key in current and (current[key] or "").strip():
            continue
        await upsert_field_value(
            db,
            scope=FieldScope.APPEAL.value,
            owner_id=appeal_id,
            field_key=key,
            value=value or "",
            source="migrate",
        )
        current[key] = value or ""
    if clear_legacy:
        result = await db.execute(
            select(FieldValue).where(
                FieldValue.scope == FieldScope.CONTACT_APPEAL.value,
                FieldValue.owner_id == contact_id,
            )
        )
        for row in result.scalars().all():
            await db.delete(row)
    return current
