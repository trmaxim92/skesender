from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    AccessRole,
    Appeal,
    Channel,
    ChatMessage,
    Dialog,
    MailingCampaign,
    MailingTemplate,
    MessageTemplate,
    OutboundWebhook,
    Role,
    TemplateCategory,
    User,
    UserChannel,
    UserDepartment,
)
from app.rbac import (
    ACTION_MANAGE_USERS,
    SECTION_CHATS,
    SECTION_EMPLOYEES,
    load_user_rbac,
    require_permission,
    user_can,
)
from app.schemas import UserCreateRequest, UserOut, UserUpdateRequest
from app.security import hash_password
from app.serializers_user import user_to_out

router = APIRouter(prefix="/users", tags=["users"])


async def _load_user(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.access_role).selectinload(AccessRole.permissions),
            selectinload(User.access_role).selectinload(AccessRole.channel_access),
            selectinload(User.channel_access),
            selectinload(User.department_memberships),
        )
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def _set_channels(db: AsyncSession, user_id: int, channel_ids: list[int]) -> None:
    await db.execute(delete(UserChannel).where(UserChannel.user_id == user_id))
    await db.flush()
    for cid in channel_ids:
        db.add(UserChannel(user_id=user_id, channel_id=cid))


async def _set_departments(db: AsyncSession, user_id: int, department_ids: list[int]) -> None:
    await db.execute(delete(UserDepartment).where(UserDepartment.user_id == user_id))
    await db.flush()
    for did in department_ids:
        db.add(UserDepartment(user_id=user_id, department_id=did))


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    include_inactive: bool = False,
) -> list[UserOut]:
    loaded = await load_user_rbac(db, user)
    can_manage = user_can(loaded, ACTION_MANAGE_USERS)
    can_list = can_manage or user_can(loaded, SECTION_EMPLOYEES) or user_can(loaded, SECTION_CHATS)
    if not can_list:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    stmt = (
        select(User)
        .options(
            selectinload(User.access_role).selectinload(AccessRole.permissions),
            selectinload(User.access_role).selectinload(AccessRole.channel_access),
            selectinload(User.channel_access),
            selectinload(User.department_memberships),
        )
        .order_by(User.id.asc())
    )
    if include_inactive and not can_manage:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    result = await db.execute(stmt)
    return [user_to_out(u) for u in result.scalars().all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> UserOut:
    email = body.email.strip().lower()
    exists = await db.execute(select(User).where(User.email == email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already used")

    access_role_id = body.access_role_id
    legacy_role = body.role.value if body.role else Role.OPERATOR.value
    if access_role_id is None:
        role_row = (
            await db.execute(select(AccessRole).where(AccessRole.slug == legacy_role))
        ).scalar_one_or_none()
        if role_row:
            access_role_id = role_row.id
    else:
        role_row = await db.get(AccessRole, access_role_id)
        if role_row is None:
            raise HTTPException(status_code=400, detail="Роль не найдена")
        if role_row.slug in {Role.ADMIN.value, Role.OPERATOR.value, Role.VIEWER.value}:
            legacy_role = role_row.slug

    user = User(
        email=email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        role=legacy_role,
        access_role_id=access_role_id,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await _set_channels(db, user.id, body.channel_ids)
    await _set_departments(db, user.id, body.department_ids)
    await db.commit()
    loaded = await _load_user(db, user.id)
    assert loaded is not None
    return user_to_out(loaded)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> UserOut:
    user = await _load_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.name is not None:
        user.name = body.name.strip()
    if body.email is not None:
        email = body.email.strip().lower()
        if email != user.email:
            exists = await db.execute(select(User).where(User.email == email, User.id != user.id))
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already used")
            user.email = email
    if body.access_role_id is not None:
        role_row = await db.get(AccessRole, body.access_role_id)
        if role_row is None:
            raise HTTPException(status_code=400, detail="Роль не найдена")
        if user.id == current.id and role_row.slug != Role.ADMIN.value and user.role == Role.ADMIN.value:
            raise HTTPException(status_code=400, detail="Cannot demote yourself")
        user.access_role_id = role_row.id
        if role_row.slug in {Role.ADMIN.value, Role.OPERATOR.value, Role.VIEWER.value}:
            user.role = role_row.slug
    elif body.role is not None:
        if user.id == current.id and body.role != Role.ADMIN:
            raise HTTPException(status_code=400, detail="Cannot demote yourself")
        user.role = body.role.value
        role_row = (
            await db.execute(select(AccessRole).where(AccessRole.slug == body.role.value))
        ).scalar_one_or_none()
        if role_row:
            user.access_role_id = role_row.id
    if body.is_active is not None:
        if user.id == current.id and not body.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    if body.channel_ids is not None:
        await _set_channels(db, user.id, body.channel_ids)
    if body.department_ids is not None:
        await _set_departments(db, user.id, body.department_ids)

    await db.commit()
    loaded = await _load_user(db, user_id)
    assert loaded is not None
    return user_to_out(loaded)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя удалить самого себя")

    is_admin = user.role == Role.ADMIN.value
    if not is_admin and user.access_role_id is not None:
        role_row = await db.get(AccessRole, user.access_role_id)
        is_admin = bool(role_row and role_row.slug == Role.ADMIN.value)
    if is_admin:
        admin_role_ids = list(
            (
                await db.execute(select(AccessRole.id).where(AccessRole.slug == Role.ADMIN.value))
            ).scalars().all()
        )
        admin_filter = [User.role == Role.ADMIN.value]
        if admin_role_ids:
            admin_filter.append(User.access_role_id.in_(admin_role_ids))
        other_admins = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.id != user.id, User.is_active.is_(True), or_(*admin_filter))
        )
        if not other_admins:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя удалить последнего администратора",
            )

    # Personal templates / categories belong to the user — remove with them.
    cat_ids = (
        await db.execute(select(TemplateCategory.id).where(TemplateCategory.created_by_id == user_id))
    ).scalars().all()
    if cat_ids:
        await db.execute(
            update(MessageTemplate)
            .where(MessageTemplate.category_id.in_(cat_ids))
            .values(category_id=None)
        )
    await db.execute(delete(MessageTemplate).where(MessageTemplate.created_by_id == user_id))
    await db.execute(delete(TemplateCategory).where(TemplateCategory.created_by_id == user_id))

    # Detach nullable FKs so history stays, but the user row can be removed.
    await db.execute(update(Channel).where(Channel.created_by_id == user_id).values(created_by_id=None))
    await db.execute(update(Dialog).where(Dialog.assignee_id == user_id).values(assignee_id=None))
    await db.execute(update(Appeal).where(Appeal.closed_by_id == user_id).values(closed_by_id=None))
    await db.execute(
        update(ChatMessage).where(ChatMessage.operator_id == user_id).values(operator_id=None)
    )
    await db.execute(
        update(OutboundWebhook)
        .where(OutboundWebhook.created_by_id == user_id)
        .values(created_by_id=None)
    )
    await db.execute(
        update(MailingTemplate)
        .where(MailingTemplate.created_by_id == user_id)
        .values(created_by_id=None)
    )
    await db.execute(
        update(MailingCampaign)
        .where(MailingCampaign.created_by_id == user_id)
        .values(created_by_id=None)
    )

    await db.delete(user)
    await db.commit()
