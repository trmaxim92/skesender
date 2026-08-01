#!/usr/bin/env python3
"""Ensure demo admin + manager users exist (idempotent)."""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/opt/order-elite/backend")

from sqlalchemy import select

from app.db import SessionLocal
from app.departments import ensure_default_department
from app.models import Role, User, UserDepartment
from app.rbac import seed_access_roles
from app.security import hash_password


DEMOS = (
    ("admin@order-elite.local", "Админ Демо", Role.ADMIN, "demo"),
    ("manager@order-elite.local", "Менеджер Демо", Role.OPERATOR, "demo"),
)


async def main() -> None:
    async with SessionLocal() as session:
        by_slug = await seed_access_roles(session)
        dept = await ensure_default_department(session)
        for email, name, role, password in DEMOS:
            row = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if row is None:
                row = User(
                    email=email,
                    name=name,
                    password_hash=hash_password(password),
                    role=role.value,
                    access_role_id=by_slug[role.value].id,
                )
                session.add(row)
                await session.flush()
                print(f"created {email}")
            else:
                row.name = name
                row.role = role.value
                row.access_role_id = by_slug[role.value].id
                row.password_hash = hash_password(password)
                print(f"updated {email}")
            link = (
                await session.execute(
                    select(UserDepartment).where(
                        UserDepartment.user_id == row.id,
                        UserDepartment.department_id == dept.id,
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                session.add(UserDepartment(user_id=row.id, department_id=dept.id))
        await session.commit()
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
