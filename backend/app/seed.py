from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.departments import (
    backfill_department_ids,
    ensure_default_department,
    ensure_system_client_fields,
)
from app.integrations.maxbot.connector import upsert_seed_channel
from app.models import (
    MessageTemplate,
    Role,
    RoleChannel,
    TemplateKind,
    User,
    UserChannel,
    UserDepartment,
)
from app.rbac import migrate_users_to_access_roles, seed_access_roles
from app.security import hash_password

logger = logging.getLogger(__name__)


async def _ensure_role_channel(session: AsyncSession, role_id: int, channel_id: int) -> None:
    exists = (
        await session.execute(
            select(RoleChannel).where(
                RoleChannel.role_id == role_id, RoleChannel.channel_id == channel_id
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(RoleChannel(role_id=role_id, channel_id=channel_id))


async def migrate_user_channels_to_roles(session: AsyncSession) -> None:
    """One-time-ish: copy per-user channel ACL onto the user's access role."""
    rows = await session.execute(
        select(User.access_role_id, UserChannel.channel_id)
        .join(UserChannel, UserChannel.user_id == User.id)
        .where(User.access_role_id.is_not(None))
    )
    seen: set[tuple[int, int]] = set()
    for role_id, channel_id in rows.all():
        if role_id is None:
            continue
        key = (int(role_id), int(channel_id))
        if key in seen:
            continue
        seen.add(key)
        await _ensure_role_channel(session, key[0], key[1])


async def seed_database(session: AsyncSession) -> None:
    settings = get_settings()

    by_slug = await seed_access_roles(session)

    dept = await ensure_default_department(session)
    await ensure_system_client_fields(session)
    await backfill_department_ids(session, dept)

    admin_email = settings.seed_admin_email.lower().strip()
    result = await session.execute(select(User).where(User.email == admin_email))
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = User(
            email=admin_email,
            name=settings.seed_admin_name,
            password_hash=hash_password(settings.seed_admin_password),
            role=Role.ADMIN.value,
            access_role_id=by_slug["admin"].id,
        )
        session.add(admin)
        await session.flush()
        logger.info("Seeded admin user %s", admin_email)

    for email, name, role in (
        ("anna@order-elite.local", "Анна Операторова", Role.OPERATOR),
        ("igor@order-elite.local", "Игорь Смотров", Role.VIEWER),
    ):
        exists = await session.execute(select(User).where(User.email == email))
        if exists.scalar_one_or_none() is None:
            session.add(
                User(
                    email=email,
                    name=name,
                    password_hash=hash_password(settings.seed_admin_password),
                    role=role.value,
                    access_role_id=by_slug[role.value].id,
                )
            )

    await migrate_users_to_access_roles(session, by_slug)
    await migrate_user_channels_to_roles(session)

    for email in ("anna@order-elite.local", "igor@order-elite.local"):
        u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            continue
        exists_ud = (
            await session.execute(
                select(UserDepartment).where(
                    UserDepartment.user_id == u.id, UserDepartment.department_id == dept.id
                )
            )
        ).scalar_one_or_none()
        if exists_ud is None:
            session.add(UserDepartment(user_id=u.id, department_id=dept.id))

    closed_tpl = await session.execute(
        select(MessageTemplate).where(MessageTemplate.kind == TemplateKind.APPEAL_CLOSED.value).limit(1)
    )
    if closed_tpl.scalar_one_or_none() is None:
        session.add(
            MessageTemplate(
                name="Обращение закрыто",
                body=(
                    "Ваше обращение №{{appeal}} закрыто. "
                    "Если вопрос останется — напишите нам снова."
                ),
                transport="all",
                kind=TemplateKind.APPEAL_CLOSED.value,
                created_by_id=admin.id if admin else None,
            )
        )
        logger.info("Seeded appeal_closed template")

    token = settings.seed_max_bot_token.strip()
    if not token:
        logger.warning("SEED_MAX_BOT_TOKEN empty — skip maxbot channel seed")
        await session.commit()
        return

    channel = await upsert_seed_channel(session, token=token, created_by_id=admin.id)
    if channel.department_id is None:
        channel.department_id = dept.id
    logger.info(
        "Seeded/updated maxbot channel identity=%s status=%s",
        channel.identity,
        channel.status,
    )
    for email in ("anna@order-elite.local", "igor@order-elite.local"):
        u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            continue
        exists_uc = (
            await session.execute(
                select(UserChannel).where(
                    UserChannel.user_id == u.id, UserChannel.channel_id == channel.id
                )
            )
        ).scalar_one_or_none()
        if exists_uc is None:
            session.add(UserChannel(user_id=u.id, channel_id=channel.id))
        if u.access_role_id:
            await _ensure_role_channel(session, u.access_role_id, channel.id)
    await session.commit()
