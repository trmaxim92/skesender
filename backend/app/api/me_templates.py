from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import ChannelTransport, MessageTemplate, TemplateCategory, User
from app.rbac import ACTION_WRITE, SECTION_CHATS, user_can
from app.schemas import (
    TemplateCategoryCreateRequest,
    TemplateCategoryOut,
    TemplateCategoryUpdateRequest,
    TemplateCreateRequest,
    TemplateOut,
    TemplateUpdateRequest,
)

router = APIRouter(prefix="/me", tags=["me"])

_ALLOWED_TRANSPORTS = {"all", *[t.value for t in ChannelTransport]}


def _require_personal_templates(user: User) -> User:
    if not (user_can(user, ACTION_WRITE) or user_can(user, SECTION_CHATS)):
        raise HTTPException(status_code=403, detail="Permission denied")
    return user


def _validate_transport(value: str) -> str:
    if value not in _ALLOWED_TRANSPORTS:
        raise HTTPException(status_code=400, detail=f"Invalid transport: {value}")
    return value


def _template_out(tpl: MessageTemplate, user: User) -> TemplateOut:
    cat = getattr(tpl, "category", None)
    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        body=tpl.body,
        transport=tpl.transport,
        kind=tpl.kind,
        category_id=tpl.category_id,
        category_name=cat.name if cat is not None else None,
        created_by_id=tpl.created_by_id,
        is_mine=True,
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


async def _load_own_template(
    db: AsyncSession, user: User, template_id: int
) -> MessageTemplate | None:
    result = await db.execute(
        select(MessageTemplate)
        .options(selectinload(MessageTemplate.category))
        .where(
            MessageTemplate.id == template_id,
            MessageTemplate.created_by_id == user.id,
        )
    )
    return result.scalar_one_or_none()


async def _get_own_category(
    db: AsyncSession, user: User, category_id: int
) -> TemplateCategory:
    cat = await db.get(TemplateCategory, category_id)
    if cat is None or cat.created_by_id != user.id:
        raise HTTPException(status_code=400, detail="Category not found")
    return cat


@router.get("/template-categories", response_model=list[TemplateCategoryOut])
async def list_my_categories(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateCategory]:
    _require_personal_templates(user)
    result = await db.execute(
        select(TemplateCategory)
        .where(TemplateCategory.created_by_id == user.id)
        .order_by(TemplateCategory.sort_order.asc(), TemplateCategory.name.asc())
    )
    return list(result.scalars().all())


@router.post(
    "/template-categories",
    response_model=TemplateCategoryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_category(
    body: TemplateCategoryCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateCategory:
    _require_personal_templates(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    cat = TemplateCategory(
        name=body.name.strip(),
        sort_order=body.sort_order,
        created_by_id=user.id,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.patch("/template-categories/{category_id}", response_model=TemplateCategoryOut)
async def update_my_category(
    category_id: int,
    body: TemplateCategoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateCategory:
    _require_personal_templates(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    cat = await db.get(TemplateCategory, category_id)
    if cat is None or cat.created_by_id != user.id:
        raise HTTPException(status_code=404, detail="Category not found")
    if body.name is not None:
        cat.name = body.name.strip()
    if body.sort_order is not None:
        cat.sort_order = body.sort_order
    await db.commit()
    await db.refresh(cat)
    return cat


@router.delete("/template-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_personal_templates(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    cat = await db.get(TemplateCategory, category_id)
    if cat is None or cat.created_by_id != user.id:
        raise HTTPException(status_code=404, detail="Category not found")
    await db.delete(cat)
    await db.commit()


@router.get("/templates", response_model=list[TemplateOut])
async def list_my_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateOut]:
    _require_personal_templates(user)
    result = await db.execute(
        select(MessageTemplate)
        .options(selectinload(MessageTemplate.category))
        .where(MessageTemplate.created_by_id == user.id)
        .order_by(MessageTemplate.updated_at.desc())
    )
    return [_template_out(t, user) for t in result.scalars().all()]


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_my_template(
    body: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    _require_personal_templates(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    category_id = body.category_id
    if category_id is not None:
        await _get_own_category(db, user, category_id)
    tpl = MessageTemplate(
        name=body.name.strip(),
        body=body.body.strip(),
        transport=_validate_transport(body.transport),
        kind=body.kind.value,
        category_id=category_id,
        created_by_id=user.id,
    )
    db.add(tpl)
    await db.commit()
    loaded = await _load_own_template(db, user, tpl.id)
    assert loaded is not None
    return _template_out(loaded, user)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_my_template(
    template_id: int,
    body: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    _require_personal_templates(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    tpl = await _load_own_template(db, user, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.name is not None:
        tpl.name = body.name.strip()
    if body.body is not None:
        tpl.body = body.body.strip()
    if body.transport is not None:
        tpl.transport = _validate_transport(body.transport)
    if body.kind is not None:
        tpl.kind = body.kind.value
    data = body.model_dump(exclude_unset=True)
    if "category_id" in data:
        if body.category_id is not None:
            await _get_own_category(db, user, body.category_id)
        tpl.category_id = body.category_id
    await db.commit()
    loaded = await _load_own_template(db, user, template_id)
    assert loaded is not None
    return _template_out(loaded, user)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_personal_templates(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    tpl = await db.get(MessageTemplate, template_id)
    if tpl is None or tpl.created_by_id != user.id:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tpl)
    await db.commit()
