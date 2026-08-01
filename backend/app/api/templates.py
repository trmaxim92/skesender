from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ChannelTransport, MessageTemplate, Role, User
from app.rbac import ACTION_WRITE, SECTION_TEMPLATES, require_permission
from app.schemas import TemplateCreateRequest, TemplateOut, TemplateUpdateRequest

router = APIRouter(prefix="/templates", tags=["templates"])

_ALLOWED_TRANSPORTS = {"all", *[t.value for t in ChannelTransport]}


def _validate_transport(value: str) -> str:
    if value not in _ALLOWED_TRANSPORTS:
        raise HTTPException(status_code=400, detail=f"Invalid transport: {value}")
    return value


def _is_admin(user: User) -> bool:
    return user.role == Role.ADMIN.value


def _template_out(tpl: MessageTemplate) -> TemplateOut:
    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        body=tpl.body,
        transport=tpl.transport,
        kind=tpl.kind,
        category_id=None,
        category_name=None,
        created_by_id=tpl.created_by_id,
        is_mine=False,
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(SECTION_TEMPLATES)),
) -> list[TemplateOut]:
    """Общие шаблоны (командные / для рассылки ответов)."""
    result = await db.execute(
        select(MessageTemplate)
        .where(MessageTemplate.created_by_id.is_(None))
        .order_by(MessageTemplate.updated_at.desc())
    )
    return [_template_out(t) for t in result.scalars().all()]


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_WRITE)),
) -> TemplateOut:
    # Shared catalog — no owner; also require section.templates via write+section for UI
    if not _is_admin(user):
        # Operators with write can add shared if they have templates section
        from app.rbac import user_can

        if not user_can(user, SECTION_TEMPLATES):
            raise HTTPException(status_code=403, detail="Permission denied")
    tpl = MessageTemplate(
        name=body.name.strip(),
        body=body.body.strip(),
        transport=_validate_transport(body.transport),
        kind=body.kind.value,
        category_id=None,
        created_by_id=None,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return _template_out(tpl)


@router.patch("/{template_id:int}", response_model=TemplateOut)
async def update_template(
    template_id: int,
    body: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_WRITE)),
) -> TemplateOut:
    from app.rbac import user_can

    if not _is_admin(user) and not user_can(user, SECTION_TEMPLATES):
        raise HTTPException(status_code=403, detail="Permission denied")
    tpl = await db.get(MessageTemplate, template_id)
    if tpl is None or tpl.created_by_id is not None:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.name is not None:
        tpl.name = body.name.strip()
    if body.body is not None:
        tpl.body = body.body.strip()
    if body.transport is not None:
        tpl.transport = _validate_transport(body.transport)
    if body.kind is not None:
        tpl.kind = body.kind.value
    await db.commit()
    await db.refresh(tpl)
    return _template_out(tpl)


@router.delete("/{template_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_WRITE)),
) -> None:
    from app.rbac import user_can

    if not _is_admin(user) and not user_can(user, SECTION_TEMPLATES):
        raise HTTPException(status_code=403, detail="Permission denied")
    tpl = await db.get(MessageTemplate, template_id)
    if tpl is None or tpl.created_by_id is not None:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tpl)
    await db.commit()
