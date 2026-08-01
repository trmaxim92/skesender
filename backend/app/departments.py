from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Channel,
    Department,
    Dialog,
    FieldDefinition,
    FieldScope,
    FieldType,
    User,
    UserDepartment,
)
from app.rbac import role_all_channels


SYSTEM_CLIENT_FIELDS: tuple[tuple[str, str, str, int], ...] = (
    ("full_name", "ФИО", FieldType.TEXT.value, 0),
    ("phone", "Телефон", FieldType.PHONE.value, 1),
    ("external_id", "ID", FieldType.TEXT.value, 2),
)


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # keep cyrillic/latin/digits
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:60] or "dept"


async def ensure_default_department(session: AsyncSession) -> Department:
    result = await session.execute(select(Department).where(Department.slug == "general"))
    dept = result.scalar_one_or_none()
    if dept is None:
        dept = Department(name="Общий", slug="general", is_active=True)
        session.add(dept)
        await session.flush()
    return dept


async def ensure_system_client_fields(session: AsyncSession) -> None:
    for key, label, field_type, sort_order in SYSTEM_CLIENT_FIELDS:
        existing = (
            await session.execute(
                select(FieldDefinition).where(
                    FieldDefinition.scope == FieldScope.CLIENT.value,
                    FieldDefinition.key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                FieldDefinition(
                    scope=FieldScope.CLIENT.value,
                    department_id=None,
                    key=key,
                    label=label,
                    field_type=field_type,
                    required=key == "full_name",
                    sort_order=sort_order,
                    is_system=True,
                    is_active=True,
                )
            )


async def backfill_department_ids(session: AsyncSession, dept: Department) -> None:
    await session.execute(
        update(Channel).where(Channel.department_id.is_(None)).values(department_id=dept.id)
    )
    await session.execute(
        update(Dialog).where(Dialog.department_id.is_(None)).values(department_id=dept.id)
    )


async def accessible_department_ids(user: User, db: AsyncSession) -> list[int] | None:
    """None means all departments (admin / all_channels)."""
    if role_all_channels(user):
        return None
    if "department_memberships" not in (user.__dict__ or {}):
        result = await db.execute(
            select(UserDepartment.department_id).where(UserDepartment.user_id == user.id)
        )
        return list(result.scalars().all())
    return [m.department_id for m in (user.department_memberships or [])]


async def ensure_department_access(
    user: User, department_id: int | None, db: AsyncSession
) -> None:
    from fastapi import HTTPException, status

    if department_id is None:
        # dialogs without department: only all-departments roles
        ids = await accessible_department_ids(user, db)
        if ids is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к отделу"
            )
        return
    ids = await accessible_department_ids(user, db)
    if ids is not None and department_id not in ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к отделу"
        )


async def unique_department_slug(session: AsyncSession, name: str, exclude_id: int | None = None) -> str:
    base = slugify(name)
    candidate = base
    n = 2
    while True:
        stmt = select(Department).where(Department.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(Department.id != exclude_id)
        exists = (await session.execute(stmt)).scalar_one_or_none()
        if exists is None:
            return candidate
        candidate = f"{base}-{n}"[:64]
        n += 1
