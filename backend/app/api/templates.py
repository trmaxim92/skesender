from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ChannelTransport, MessageTemplate, TemplateKind, User
from app.rbac import (
    ACTION_MANAGE_USERS,
    SECTION_CHATS,
    SECTION_SETTINGS,
    load_user_rbac,
    require_permission,
    user_can,
)
from app.schemas import TemplateOut, TemplateUpdateRequest
from app.deps import get_current_user

router = APIRouter(prefix="/templates", tags=["templates"])

_ALLOWED_TRANSPORTS = {"all", *[t.value for t in ChannelTransport]}
_DEFAULT_CLOSE_BODY = (
    "Ваше обращение №{{appeal}} закрыто. Если вопрос останется — напишите нам снова."
)


def _validate_transport(value: str) -> str:
    if value not in _ALLOWED_TRANSPORTS:
        raise HTTPException(status_code=400, detail=f"Invalid transport: {value}")
    return value


def _template_out(tpl: MessageTemplate) -> TemplateOut:
    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        body=tpl.body,
        transport=tpl.transport,
        kind=tpl.kind,
        category_id=None,
        category_name=None,
        media_kind=getattr(tpl, "media_kind", None),
        media_name=getattr(tpl, "media_name", None),
        mime_type=getattr(tpl, "mime_type", None),
        has_media=bool(getattr(tpl, "media_path", None)),
        created_by_id=tpl.created_by_id,
        is_mine=False,
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


async def _get_system_close(db: AsyncSession) -> MessageTemplate | None:
    """Prefer shared (ownerless) appeal_closed; fall back to any row."""
    shared = await db.execute(
        select(MessageTemplate)
        .where(
            MessageTemplate.kind == TemplateKind.APPEAL_CLOSED.value,
            MessageTemplate.created_by_id.is_(None),
        )
        .order_by(MessageTemplate.updated_at.desc())
        .limit(1)
    )
    row = shared.scalar_one_or_none()
    if row is not None:
        return row
    any_row = await db.execute(
        select(MessageTemplate)
        .where(MessageTemplate.kind == TemplateKind.APPEAL_CLOSED.value)
        .order_by(MessageTemplate.updated_at.desc())
        .limit(1)
    )
    return any_row.scalar_one_or_none()


async def ensure_system_close_template(db: AsyncSession) -> MessageTemplate:
    existing = await _get_system_close(db)
    if existing is not None:
        if existing.created_by_id is not None:
            existing.created_by_id = None
            await db.flush()
        return existing
    tpl = MessageTemplate(
        name="Обращение закрыто",
        body=_DEFAULT_CLOSE_BODY,
        transport="all",
        kind=TemplateKind.APPEAL_CLOSED.value,
        created_by_id=None,
    )
    db.add(tpl)
    await db.flush()
    return tpl


@router.get("/close", response_model=TemplateOut)
async def get_close_template(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    """System close-appeal message — readable by anyone who can chat."""
    loaded = await load_user_rbac(db, user)
    if not (
        user_can(loaded, SECTION_CHATS)
        or user_can(loaded, SECTION_SETTINGS)
        or user_can(loaded, ACTION_MANAGE_USERS)
    ):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    tpl = await ensure_system_close_template(db)
    await db.commit()
    await db.refresh(tpl)
    return _template_out(tpl)


@router.put("/close", response_model=TemplateOut)
async def update_close_template(
    body: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> TemplateOut:
    """Admin/settings: edit the single system close-appeal template."""
    tpl = await ensure_system_close_template(db)
    if body.name is not None:
        tpl.name = body.name.strip() or tpl.name
    if body.body is not None:
        text = body.body.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Пустой текст шаблона")
        tpl.body = text
    if body.transport is not None:
        tpl.transport = _validate_transport(body.transport)
    tpl.kind = TemplateKind.APPEAL_CLOSED.value
    tpl.created_by_id = None
    await db.commit()
    await db.refresh(tpl)
    return _template_out(tpl)
