from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.departments import unique_department_slug
from app.deps import get_current_user
from app.models import Channel, Department, Dialog, User, UserDepartment, utcnow
from app.rbac import (
    ACTION_MANAGE_CHANNELS,
    ACTION_MANAGE_USERS,
    SECTION_EMPLOYEES,
    SECTION_SETTINGS,
    load_user_rbac,
    user_can,
)
from app.schemas import (
    DepartmentCreateRequest,
    DepartmentOut,
    DepartmentUpdateRequest,
)

router = APIRouter(prefix="/departments", tags=["departments"])


def _can_manage_departments(user: User) -> bool:
    return (
        user_can(user, SECTION_EMPLOYEES)
        or user_can(user, ACTION_MANAGE_USERS)
        or user_can(user, SECTION_SETTINGS)
    )


def _to_out(dept: Department, channel_count: int = 0) -> DepartmentOut:
    return DepartmentOut(
        id=dept.id,
        name=dept.name,
        slug=dept.slug,
        is_active=dept.is_active,
        member_ids=[m.user_id for m in (dept.members or [])],
        channel_count=channel_count,
        created_at=dept.created_at,
    )


async def _load_dept(db: AsyncSession, dept_id: int) -> Department | None:
    result = await db.execute(
        select(Department)
        .options(selectinload(Department.members))
        .where(Department.id == dept_id)
    )
    return result.scalar_one_or_none()


async def _set_members(db: AsyncSession, dept_id: int, member_ids: list[int]) -> None:
    await db.execute(delete(UserDepartment).where(UserDepartment.department_id == dept_id))
    await db.flush()
    for uid in member_ids:
        db.add(UserDepartment(user_id=uid, department_id=dept_id))


@router.get("", response_model=list[DepartmentOut])
async def list_departments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DepartmentOut]:
    loaded = await load_user_rbac(db, user)
    if not (
        _can_manage_departments(loaded)
        or user_can(loaded, ACTION_MANAGE_CHANNELS)
        or user_can(loaded, SECTION_SETTINGS)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    result = await db.execute(
        select(Department).options(selectinload(Department.members)).order_by(Department.id.asc())
    )
    depts = list(result.scalars().all())
    counts: dict[int, int] = {}
    if depts:
        count_rows = await db.execute(
            select(Channel.department_id, func.count(Channel.id))
            .where(Channel.department_id.in_([d.id for d in depts]))
            .group_by(Channel.department_id)
        )
        counts = {int(did): int(c) for did, c in count_rows.all() if did is not None}
    return [_to_out(d, counts.get(d.id, 0)) for d in depts]


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DepartmentOut:
    loaded = await load_user_rbac(db, user)
    if not _can_manage_departments(loaded):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    name = body.name.strip()
    slug = await unique_department_slug(db, name)
    dept = Department(name=name, slug=slug, is_active=True)
    db.add(dept)
    await db.flush()
    if body.member_ids:
        await _set_members(db, dept.id, body.member_ids)
    await db.commit()
    loaded_dept = await _load_dept(db, dept.id)
    assert loaded_dept is not None
    return _to_out(loaded_dept, 0)


@router.patch("/{department_id}", response_model=DepartmentOut)
async def update_department(
    department_id: int,
    body: DepartmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DepartmentOut:
    loaded = await load_user_rbac(db, user)
    if not _can_manage_departments(loaded):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    dept = await _load_dept(db, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Отдел не найден")
    if body.name is not None:
        dept.name = body.name.strip()
        dept.slug = await unique_department_slug(db, dept.name, exclude_id=dept.id)
        dept.updated_at = utcnow()
    if body.is_active is not None:
        if dept.slug == "general" and not body.is_active:
            raise HTTPException(status_code=400, detail="Нельзя отключить отдел «Общий»")
        dept.is_active = body.is_active
    if body.member_ids is not None:
        await _set_members(db, dept.id, body.member_ids)
    await db.commit()
    loaded_dept = await _load_dept(db, department_id)
    assert loaded_dept is not None
    channel_count = int(
        await db.scalar(
            select(func.count(Channel.id)).where(Channel.department_id == department_id)
        )
        or 0
    )
    return _to_out(loaded_dept, channel_count)


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    loaded = await load_user_rbac(db, user)
    if not _can_manage_departments(loaded):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    dept = await db.get(Department, department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Отдел не найден")
    if dept.slug == "general":
        raise HTTPException(status_code=400, detail="Нельзя удалить отдел «Общий»")
    general = (
        await db.execute(select(Department).where(Department.slug == "general"))
    ).scalar_one_or_none()
    if general is None:
        raise HTTPException(status_code=400, detail="Нет отдела «Общий» для переноса")
    await db.execute(
        update(Channel)
        .where(Channel.department_id == department_id)
        .values(department_id=general.id)
    )
    await db.execute(
        update(Dialog)
        .where(Dialog.department_id == department_id)
        .values(department_id=general.id)
    )
    await db.delete(dept)
    await db.commit()
