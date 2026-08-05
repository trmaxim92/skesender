from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    AttachmentKind,
    ChannelTransport,
    MessageTemplate,
    TemplateAttachment,
    TemplateCategory,
    TemplateKind,
    User,
)
from app.rbac import ACTION_WRITE, SECTION_CHATS, user_can
from app.schemas import (
    TemplateAttachmentOut,
    TemplateCategoryCreateRequest,
    TemplateCategoryOut,
    TemplateCategoryUpdateRequest,
    TemplateOut,
)
from app.storage.attachments import absolute_path, guess_kind, save_bytes

router = APIRouter(prefix="/me", tags=["me"])

_ALLOWED_TRANSPORTS = {"all", *[t.value for t in ChannelTransport]}
_MAX_IMAGES = 10


def _require_personal_templates(user: User) -> User:
    if not (user_can(user, ACTION_WRITE) or user_can(user, SECTION_CHATS)):
        raise HTTPException(status_code=403, detail="Permission denied")
    return user


def _require_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")


def _validate_transport(value: str) -> str:
    if value not in _ALLOWED_TRANSPORTS:
        raise HTTPException(status_code=400, detail=f"Invalid transport: {value}")
    return value


def _parse_kind(value: str) -> str:
    raw = (value or TemplateKind.GENERAL.value).strip().lower()
    try:
        return TemplateKind(raw).value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid kind: {value}") from exc


def _attachments_out(tpl: MessageTemplate) -> list[TemplateAttachmentOut]:
    rows = list(getattr(tpl, "attachments", None) or [])
    rows = sorted(rows, key=lambda a: (a.sort_order, a.id))
    if rows:
        return [
            TemplateAttachmentOut(
                id=a.id,
                file_name=a.file_name,
                mime_type=a.mime_type,
                sort_order=a.sort_order,
            )
            for a in rows
        ]
    if tpl.media_path:
        return [
            TemplateAttachmentOut(
                id=0,
                file_name=tpl.media_name or "image.jpg",
                mime_type=tpl.mime_type,
                sort_order=0,
            )
        ]
    return []


def _template_out(tpl: MessageTemplate, user: User) -> TemplateOut:
    cat = getattr(tpl, "category", None)
    attachments = _attachments_out(tpl)
    first = attachments[0] if attachments else None
    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        body=tpl.body,
        transport=tpl.transport,
        kind=tpl.kind,
        category_id=tpl.category_id,
        category_name=cat.name if cat is not None else None,
        media_kind=tpl.media_kind or (AttachmentKind.IMAGE.value if first else None),
        media_name=first.file_name if first else tpl.media_name,
        mime_type=first.mime_type if first else tpl.mime_type,
        has_media=bool(attachments),
        media_count=len(attachments),
        attachments=attachments,
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
        .options(
            selectinload(MessageTemplate.category),
            selectinload(MessageTemplate.attachments),
        )
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


def _unlink_path(relative: str | None) -> None:
    if not relative:
        return
    try:
        path = absolute_path(relative)
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _sync_legacy_media(tpl: MessageTemplate) -> None:
    rows = sorted(list(tpl.attachments or []), key=lambda a: (a.sort_order, a.id))
    if not rows:
        tpl.media_kind = None
        tpl.media_path = None
        tpl.media_name = None
        tpl.mime_type = None
        return
    first = rows[0]
    tpl.media_kind = first.kind
    tpl.media_path = first.storage_path
    tpl.media_name = first.file_name
    tpl.mime_type = first.mime_type


async def _add_images(tpl: MessageTemplate, files: list[UploadFile]) -> int:
    existing = len(list(tpl.attachments or []))
    added = 0
    for media in files:
        if not media.filename:
            continue
        if existing + added >= _MAX_IMAGES:
            raise HTTPException(
                status_code=400, detail=f"Максимум {_MAX_IMAGES} изображений на шаблон"
            )
        data = await media.read()
        if not data:
            continue
        kind = guess_kind(media.content_type, media.filename)
        if kind != AttachmentKind.IMAGE:
            raise HTTPException(status_code=400, detail="Можно прикрепить только изображения")
        relative, safe_name, mime, size = save_bytes(
            data=data,
            file_name=media.filename,
            message_id=None,
            mime_type=media.content_type,
        )
        tpl.attachments.append(
            TemplateAttachment(
                kind=kind.value,
                file_name=safe_name,
                mime_type=mime,
                size_bytes=size,
                storage_path=relative,
                sort_order=existing + added,
            )
        )
        added += 1
    return added


def _clear_all_media(tpl: MessageTemplate) -> None:
    paths = {a.storage_path for a in list(tpl.attachments or []) if a.storage_path}
    if tpl.media_path:
        paths.add(tpl.media_path)
    for relative in paths:
        _unlink_path(relative)
    tpl.attachments.clear()
    tpl.media_kind = None
    tpl.media_path = None
    tpl.media_name = None
    tpl.mime_type = None


def _parse_remove_ids(raw: str | None) -> set[int]:
    if not raw or not raw.strip():
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def _normalize_uploads(media: list[UploadFile] | None) -> list[UploadFile]:
    if not media:
        return []
    return [m for m in media if m is not None and getattr(m, "filename", None)]


def _has_any_media(tpl: MessageTemplate) -> bool:
    return bool(tpl.attachments) or bool(tpl.media_path)


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
    _require_write(user)
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
    _require_write(user)
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
    _require_write(user)
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
        .options(
            selectinload(MessageTemplate.category),
            selectinload(MessageTemplate.attachments),
        )
        .where(MessageTemplate.created_by_id == user.id)
        .order_by(MessageTemplate.updated_at.desc())
    )
    return [_template_out(t, user) for t in result.scalars().all()]


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_my_template(
    name: str = Form(...),
    body: str = Form(""),
    transport: str = Form("all"),
    kind: str = Form(TemplateKind.GENERAL.value),
    category_id: int | None = Form(default=None),
    media: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    _require_personal_templates(user)
    _require_write(user)
    name = name.strip()
    body = (body or "").strip()
    uploads = _normalize_uploads(media)
    if not name:
        raise HTTPException(status_code=400, detail="Название обязательно")
    if not body and not uploads:
        raise HTTPException(status_code=400, detail="Нужен текст или изображение")
    if category_id is not None:
        await _get_own_category(db, user, category_id)
    tpl = MessageTemplate(
        name=name,
        body=body,
        transport=_validate_transport(transport),
        kind=_parse_kind(kind),
        category_id=category_id,
        created_by_id=user.id,
    )
    db.add(tpl)
    await db.flush()
    await _add_images(tpl, uploads)
    _sync_legacy_media(tpl)
    await db.commit()
    loaded = await _load_own_template(db, user, tpl.id)
    assert loaded is not None
    return _template_out(loaded, user)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_my_template(
    template_id: int,
    name: str | None = Form(default=None),
    body: str | None = Form(default=None),
    transport: str | None = Form(default=None),
    kind: str | None = Form(default=None),
    category_id: str | None = Form(default=None),
    clear_media: bool = Form(default=False),
    remove_attachment_ids: str = Form(default=""),
    media: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    """Update personal template. category_id: omit to keep, empty string to clear."""
    _require_personal_templates(user)
    _require_write(user)
    tpl = await _load_own_template(db, user, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Название обязательно")
        tpl.name = name
    if body is not None:
        tpl.body = body.strip()
    if transport is not None:
        tpl.transport = _validate_transport(transport)
    if kind is not None:
        tpl.kind = _parse_kind(kind)
    if category_id is not None:
        if category_id.strip() == "":
            tpl.category_id = None
        else:
            cid = int(category_id)
            await _get_own_category(db, user, cid)
            tpl.category_id = cid

    if clear_media:
        _clear_all_media(tpl)
    else:
        remove_ids = _parse_remove_ids(remove_attachment_ids)
        if remove_ids:
            for att in list(tpl.attachments or []):
                if att.id in remove_ids:
                    _unlink_path(att.storage_path)
                    tpl.attachments.remove(att)
            if 0 in remove_ids and tpl.media_path and not tpl.attachments:
                _unlink_path(tpl.media_path)
                tpl.media_kind = None
                tpl.media_path = None
                tpl.media_name = None
                tpl.mime_type = None

    uploads = _normalize_uploads(media)
    if uploads:
        await _add_images(tpl, uploads)

    _sync_legacy_media(tpl)
    if not (tpl.body or "").strip() and not _has_any_media(tpl):
        raise HTTPException(status_code=400, detail="Нужен текст или изображение")
    await db.commit()
    loaded = await _load_own_template(db, user, template_id)
    assert loaded is not None
    return _template_out(loaded, user)


@router.get("/templates/{template_id}/media")
async def my_template_media(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """First image (compat). Prefer /media/{attachment_id} for multi."""
    _require_personal_templates(user)
    tpl = await _load_own_template(db, user, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    rows = sorted(list(tpl.attachments or []), key=lambda a: (a.sort_order, a.id))
    if rows:
        att = rows[0]
        path = absolute_path(att.storage_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Файл не найден")
        return FileResponse(
            path,
            media_type=att.mime_type or "application/octet-stream",
            filename=att.file_name or path.name,
        )
    if not tpl.media_path:
        raise HTTPException(status_code=404, detail="Медиа не найдено")
    path = absolute_path(tpl.media_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(
        path,
        media_type=tpl.mime_type or "application/octet-stream",
        filename=tpl.media_name or path.name,
    )


@router.get("/templates/{template_id}/media/{attachment_id}")
async def my_template_media_item(
    template_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_personal_templates(user)
    tpl = await _load_own_template(db, user, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if attachment_id == 0 and tpl.media_path:
        path = absolute_path(tpl.media_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Файл не найден")
        return FileResponse(
            path,
            media_type=tpl.mime_type or "application/octet-stream",
            filename=tpl.media_name or path.name,
        )
    att = next((a for a in (tpl.attachments or []) if a.id == attachment_id), None)
    if att is None:
        raise HTTPException(status_code=404, detail="Медиа не найдено")
    path = absolute_path(att.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(
        path,
        media_type=att.mime_type or "application/octet-stream",
        filename=att.file_name or path.name,
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_personal_templates(user)
    _require_write(user)
    tpl = await _load_own_template(db, user, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    _clear_all_media(tpl)
    await db.delete(tpl)
    await db.commit()
