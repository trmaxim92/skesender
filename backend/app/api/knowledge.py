"""Operator knowledge base — nested folders + rich-text articles."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from html import unescape

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import AttachmentKind, KnowledgeArticle, KnowledgeFolder, User
from app.rbac import ACTION_WRITE, SECTION_KNOWLEDGE, user_can
from app.schemas import (
    KbArticleCreateRequest,
    KbArticleOut,
    KbArticleSummaryOut,
    KbArticleUpdateRequest,
    KbFolderCreateRequest,
    KbFolderNodeOut,
    KbFolderReorderRequest,
    KbFolderUpdateRequest,
    KbImageOut,
    KbSearchHitOut,
    KbSearchOut,
    KbTreeOut,
)
from app.storage.attachments import absolute_path, guess_kind, save_bytes

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html or "")
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _snippet(html: str, query: str, *, radius: int = 70) -> str:
    plain = _strip_html(html)
    if not plain:
        return ""
    q = (query or "").strip().lower()
    low = plain.lower()
    idx = low.find(q) if q else -1
    if idx < 0:
        return plain[: radius * 2] + ("…" if len(plain) > radius * 2 else "")
    start = max(0, idx - radius)
    end = min(len(plain), idx + len(q) + radius)
    chunk = plain[start:end]
    if start > 0:
        chunk = "…" + chunk
    if end < len(plain):
        chunk = chunk + "…"
    return chunk


def _require_knowledge(user: User) -> None:
    if not user_can(user, SECTION_KNOWLEDGE):
        raise HTTPException(status_code=403, detail="Permission denied")


def _require_write(user: User) -> None:
    _require_knowledge(user)
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")


def _slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9а-яё]+", "-", text, flags=re.IGNORECASE)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text or "article")[:80]


async def _unique_slug(db: AsyncSession, base: str, *, exclude_id: int | None = None) -> str:
    candidate = base
    n = 2
    while True:
        q = select(KnowledgeArticle.id).where(KnowledgeArticle.slug == candidate)
        if exclude_id is not None:
            q = q.where(KnowledgeArticle.id != exclude_id)
        exists = (await db.execute(q.limit(1))).scalar_one_or_none()
        if exists is None:
            return candidate
        candidate = f"{base}-{n}"[:120]
        n += 1


def _article_summary(a: KnowledgeArticle) -> KbArticleSummaryOut:
    return KbArticleSummaryOut(
        id=a.id,
        folder_id=a.folder_id,
        title=a.title,
        slug=a.slug,
        is_published=bool(a.is_published),
        updated_at=a.updated_at,
    )


def _article_out(a: KnowledgeArticle) -> KbArticleOut:
    created = a.created_by
    updated = a.updated_by
    return KbArticleOut(
        id=a.id,
        folder_id=a.folder_id,
        title=a.title,
        slug=a.slug,
        body_html=a.body_html or "",
        is_published=bool(a.is_published),
        created_by_id=a.created_by_id,
        created_by_name=(created.name if created else None),
        updated_by_id=a.updated_by_id,
        updated_by_name=(updated.name if updated else None),
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _build_tree(
    folders: list[KnowledgeFolder],
    *,
    include_unpublished: bool,
) -> list[KbFolderNodeOut]:
    by_parent: dict[int | None, list[KnowledgeFolder]] = {}
    for f in folders:
        by_parent.setdefault(f.parent_id, []).append(f)
    for rows in by_parent.values():
        rows.sort(key=lambda x: (x.sort_order, x.title.lower(), x.id))

    def walk(parent_id: int | None) -> list[KbFolderNodeOut]:
        nodes: list[KbFolderNodeOut] = []
        for f in by_parent.get(parent_id, []):
            arts = sorted(
                list(f.articles or []),
                key=lambda a: (a.title.lower(), a.id),
            )
            if not include_unpublished:
                arts = [a for a in arts if a.is_published]
            nodes.append(
                KbFolderNodeOut(
                    id=f.id,
                    parent_id=f.parent_id,
                    title=f.title,
                    icon=f.icon,
                    sort_order=f.sort_order,
                    articles=[_article_summary(a) for a in arts],
                    children=walk(f.id),
                )
            )
        return nodes

    return walk(None)


async def _folder_or_404(db: AsyncSession, folder_id: int) -> KnowledgeFolder:
    folder = await db.get(KnowledgeFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


async def _is_descendant(
    db: AsyncSession, *, ancestor_id: int, maybe_descendant_id: int
) -> bool:
    """True if maybe_descendant_id is ancestor_id or nested under it."""
    if ancestor_id == maybe_descendant_id:
        return True
    current = await db.get(KnowledgeFolder, maybe_descendant_id)
    seen: set[int] = set()
    while current is not None and current.parent_id is not None:
        if current.parent_id in seen:
            break
        if current.parent_id == ancestor_id:
            return True
        seen.add(current.parent_id)
        current = await db.get(KnowledgeFolder, current.parent_id)
    return False


@router.get("/tree", response_model=KbTreeOut)
async def knowledge_tree(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbTreeOut:
    _require_knowledge(user)
    can_write = user_can(user, ACTION_WRITE)
    result = await db.execute(
        select(KnowledgeFolder).options(selectinload(KnowledgeFolder.articles))
    )
    folders = list(result.scalars().unique().all())
    return KbTreeOut(folders=_build_tree(folders, include_unpublished=can_write))


@router.get("/search", response_model=KbSearchOut)
async def search_articles(
    q: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbSearchOut:
    _require_knowledge(user)
    query = (q or "").strip()
    if len(query) < 2:
        return KbSearchOut(items=[])
    pattern = f"%{query}%"
    stmt = (
        select(KnowledgeArticle)
        .where(
            or_(
                KnowledgeArticle.title.ilike(pattern),
                KnowledgeArticle.body_html.ilike(pattern),
            )
        )
        .order_by(KnowledgeArticle.updated_at.desc())
        .limit(40)
    )
    if not user_can(user, ACTION_WRITE):
        stmt = stmt.where(KnowledgeArticle.is_published.is_(True))
    rows = list((await db.execute(stmt)).scalars().all())
    return KbSearchOut(
        items=[
            KbSearchHitOut(
                id=a.id,
                folder_id=a.folder_id,
                title=a.title,
                snippet=_snippet(a.body_html or "", query),
                is_published=bool(a.is_published),
                updated_at=a.updated_at,
            )
            for a in rows
        ]
    )


@router.post("/images", response_model=KbImageOut, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> KbImageOut:
    _require_write(user)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Изображение больше 8 МБ")
    kind = guess_kind(file.content_type, file.filename)
    if kind != AttachmentKind.IMAGE:
        raise HTTPException(status_code=400, detail="Можно загрузить только изображение")
    relative, safe_name, _mime, _size = save_bytes(
        data=data,
        file_name=file.filename,
        mime_type=file.content_type,
        subdir="kb",
    )
    return KbImageOut(url=f"/api/knowledge/media/{relative}", file_name=safe_name)


@router.get("/media/{file_path:path}")
async def knowledge_media(
    file_path: str,
    user: User = Depends(get_current_user),
) -> FileResponse:
    _require_knowledge(user)
    # Only allow files under the kb/ upload prefix.
    normalized = (file_path or "").replace("\\", "/").lstrip("/")
    if not normalized.startswith("kb/") or ".." in normalized.split("/"):
        raise HTTPException(status_code=404, detail="Файл не найден")
    try:
        path = absolute_path(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Файл не найден") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path, filename=path.name)


@router.get("/articles/{article_id}", response_model=KbArticleOut)
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbArticleOut:
    _require_knowledge(user)
    result = await db.execute(
        select(KnowledgeArticle)
        .options(
            selectinload(KnowledgeArticle.created_by),
            selectinload(KnowledgeArticle.updated_by),
        )
        .where(KnowledgeArticle.id == article_id)
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    if not article.is_published and not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=404, detail="Article not found")
    return _article_out(article)


@router.post("/folders", response_model=KbFolderNodeOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: KbFolderCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbFolderNodeOut:
    _require_write(user)
    if body.parent_id is not None:
        await _folder_or_404(db, body.parent_id)
    folder = KnowledgeFolder(
        title=body.title.strip(),
        parent_id=body.parent_id,
        icon=(body.icon.strip() if body.icon else None),
        sort_order=body.sort_order,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return KbFolderNodeOut(
        id=folder.id,
        parent_id=folder.parent_id,
        title=folder.title,
        icon=folder.icon,
        sort_order=folder.sort_order,
        articles=[],
        children=[],
    )


@router.patch("/folders/{folder_id}", response_model=KbFolderNodeOut)
async def update_folder(
    folder_id: int,
    body: KbFolderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbFolderNodeOut:
    _require_write(user)
    folder = await _folder_or_404(db, folder_id)
    if "title" in body.model_fields_set and body.title is not None:
        folder.title = body.title.strip()
    if "icon" in body.model_fields_set:
        folder.icon = body.icon.strip() if body.icon else None
    if "sort_order" in body.model_fields_set and body.sort_order is not None:
        folder.sort_order = body.sort_order
    if "parent_id" in body.model_fields_set:
        new_parent = body.parent_id
        if new_parent is not None:
            if new_parent == folder.id:
                raise HTTPException(status_code=400, detail="Папка не может быть родителем самой себе")
            await _folder_or_404(db, new_parent)
            if await _is_descendant(db, ancestor_id=folder.id, maybe_descendant_id=new_parent):
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя переместить папку внутрь собственного потомка",
                )
        folder.parent_id = new_parent
    folder.updated_at = datetime.now(timezone.utc)
    await db.commit()
    result = await db.execute(
        select(KnowledgeFolder)
        .options(selectinload(KnowledgeFolder.articles))
        .where(KnowledgeFolder.id == folder.id)
    )
    folder = result.scalar_one()
    arts = sorted(list(folder.articles or []), key=lambda a: (a.title.lower(), a.id))
    return KbFolderNodeOut(
        id=folder.id,
        parent_id=folder.parent_id,
        title=folder.title,
        icon=folder.icon,
        sort_order=folder.sort_order,
        articles=[_article_summary(a) for a in arts],
        children=[],
    )


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_write(user)
    folder = await _folder_or_404(db, folder_id)
    await db.delete(folder)
    await db.commit()


@router.post("/folders/reorder", response_model=KbTreeOut)
async def reorder_folders(
    body: KbFolderReorderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbTreeOut:
    _require_write(user)
    ids = [item.id for item in body.items]
    result = await db.execute(select(KnowledgeFolder).where(KnowledgeFolder.id.in_(ids)))
    by_id = {f.id: f for f in result.scalars().all()}
    for item in body.items:
        folder = by_id.get(item.id)
        if folder is None:
            raise HTTPException(status_code=404, detail=f"Folder {item.id} not found")
        if item.parent_id is not None:
            if item.parent_id == folder.id:
                raise HTTPException(status_code=400, detail="Invalid parent")
            if item.parent_id not in by_id:
                await _folder_or_404(db, item.parent_id)
            if await _is_descendant(
                db, ancestor_id=folder.id, maybe_descendant_id=item.parent_id
            ):
                raise HTTPException(status_code=400, detail="Cycle in folder tree")
        folder.parent_id = item.parent_id
        folder.sort_order = item.sort_order
        folder.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await knowledge_tree(db=db, user=user)


@router.post(
    "/articles",
    response_model=KbArticleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_article(
    body: KbArticleCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbArticleOut:
    _require_write(user)
    await _folder_or_404(db, body.folder_id)
    slug = await _unique_slug(db, _slugify(body.title))
    article = KnowledgeArticle(
        folder_id=body.folder_id,
        title=body.title.strip(),
        slug=slug,
        body_html=body.body_html or "",
        is_published=body.is_published,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(article)
    await db.commit()
    result = await db.execute(
        select(KnowledgeArticle)
        .options(
            selectinload(KnowledgeArticle.created_by),
            selectinload(KnowledgeArticle.updated_by),
        )
        .where(KnowledgeArticle.id == article.id)
    )
    return _article_out(result.scalar_one())


@router.patch("/articles/{article_id}", response_model=KbArticleOut)
async def update_article(
    article_id: int,
    body: KbArticleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KbArticleOut:
    _require_write(user)
    result = await db.execute(
        select(KnowledgeArticle)
        .options(
            selectinload(KnowledgeArticle.created_by),
            selectinload(KnowledgeArticle.updated_by),
        )
        .where(KnowledgeArticle.id == article_id)
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    if "folder_id" in body.model_fields_set and body.folder_id is not None:
        await _folder_or_404(db, body.folder_id)
        article.folder_id = body.folder_id
    if "title" in body.model_fields_set and body.title is not None:
        article.title = body.title.strip()
        article.slug = await _unique_slug(db, _slugify(article.title), exclude_id=article.id)
    if "body_html" in body.model_fields_set and body.body_html is not None:
        article.body_html = body.body_html
    if "is_published" in body.model_fields_set and body.is_published is not None:
        article.is_published = body.is_published
    article.updated_by_id = user.id
    article.updated_at = datetime.now(timezone.utc)
    await db.commit()
    result = await db.execute(
        select(KnowledgeArticle)
        .options(
            selectinload(KnowledgeArticle.created_by),
            selectinload(KnowledgeArticle.updated_by),
        )
        .where(KnowledgeArticle.id == article.id)
    )
    return _article_out(result.scalar_one())


@router.delete("/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _require_write(user)
    article = await db.get(KnowledgeArticle, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    await db.delete(article)
    await db.commit()
