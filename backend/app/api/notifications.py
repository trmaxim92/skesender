"""In-app notification bell: system news now, other kinds later."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import SystemNews, SystemNewsRead, User, utcnow
from app.rbac import SECTION_SETTINGS, require_permission
from app.schemas import (
    NotificationOut,
    NotificationsPageOut,
    NotificationsReadRequest,
    SystemNewsCreateRequest,
    SystemNewsOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _news_id(news_id: int) -> str:
    return f"news:{news_id}"


def _parse_news_id(raw: str) -> int | None:
    if not raw.startswith("news:"):
        return None
    try:
        return int(raw.split(":", 1)[1])
    except ValueError:
        return None


def _to_notification(news: SystemNews, *, read: bool) -> NotificationOut:
    return NotificationOut(
        id=_news_id(news.id),
        kind="system_news",
        title=news.title,
        body=news.body,
        created_at=news.published_at or news.created_at,
        read=read,
        link=f"/news?id={news.id}",
    )


@router.get("", response_model=NotificationsPageOut)
async def list_notifications(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationsPageOut:
    """Bell feed for the current employee (system news; extensible)."""
    limit = max(1, min(limit, 100))
    result = await db.execute(
        select(SystemNews).order_by(SystemNews.published_at.desc()).limit(limit)
    )
    news_rows = list(result.scalars().all())
    if not news_rows:
        return NotificationsPageOut(items=[], unread_count=0)

    news_ids = [n.id for n in news_rows]
    read_result = await db.execute(
        select(SystemNewsRead.news_id).where(
            SystemNewsRead.user_id == user.id,
            SystemNewsRead.news_id.in_(news_ids),
        )
    )
    read_ids = set(read_result.scalars().all())

    unread_total = await db.scalar(
        select(func.count())
        .select_from(SystemNews)
        .where(
            ~SystemNews.id.in_(
                select(SystemNewsRead.news_id).where(SystemNewsRead.user_id == user.id)
            )
        )
    )

    items = [_to_notification(n, read=n.id in read_ids) for n in news_rows]
    return NotificationsPageOut(items=items, unread_count=int(unread_total or 0))


@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    total = await db.scalar(
        select(func.count())
        .select_from(SystemNews)
        .where(
            ~SystemNews.id.in_(
                select(SystemNewsRead.news_id).where(SystemNewsRead.user_id == user.id)
            )
        )
    )
    return {"unread_count": int(total or 0)}


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notifications_read(
    body: NotificationsReadRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if body.ids:
        news_ids = [nid for raw in body.ids if (nid := _parse_news_id(raw)) is not None]
    else:
        result = await db.execute(select(SystemNews.id))
        news_ids = list(result.scalars().all())

    if not news_ids:
        return

    existing = await db.execute(
        select(SystemNewsRead.news_id).where(
            SystemNewsRead.user_id == user.id,
            SystemNewsRead.news_id.in_(news_ids),
        )
    )
    already = set(existing.scalars().all())
    now = utcnow()
    for nid in news_ids:
        if nid in already:
            continue
        db.add(SystemNewsRead(user_id=user.id, news_id=nid, read_at=now))
    await db.commit()


# --- Admin: publish / manage system news ---


@router.get("/system-news", response_model=list[SystemNewsOut])
async def list_system_news_admin(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[SystemNewsOut]:
    result = await db.execute(
        select(SystemNews)
        .options(selectinload(SystemNews.created_by))
        .order_by(SystemNews.published_at.desc())
    )
    rows = list(result.scalars().all())
    out: list[SystemNewsOut] = []
    for news in rows:
        rc = await db.scalar(
            select(func.count()).select_from(SystemNewsRead).where(SystemNewsRead.news_id == news.id)
        )
        out.append(
            SystemNewsOut(
                id=news.id,
                title=news.title,
                body=news.body,
                created_at=news.created_at,
                published_at=news.published_at,
                created_by_id=news.created_by_id,
                created_by_name=news.created_by.name if news.created_by else None,
                read_count=int(rc or 0),
            )
        )
    return out


@router.post("/system-news", response_model=SystemNewsOut, status_code=status.HTTP_201_CREATED)
async def create_system_news(
    body: SystemNewsCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> SystemNewsOut:
    news = SystemNews(
        title=body.title.strip(),
        body=body.body.strip(),
        created_by_id=user.id,
        published_at=utcnow(),
    )
    db.add(news)
    await db.commit()
    await db.refresh(news)

    if body.send_push:
        try:
            from app.push import notify_system_news

            await notify_system_news(news_id=news.id, title=news.title, body=news.body)
        except Exception:
            logger.exception("Failed to push system news id=%s", news.id)

    return SystemNewsOut(
        id=news.id,
        title=news.title,
        body=news.body,
        created_at=news.created_at,
        published_at=news.published_at,
        created_by_id=user.id,
        created_by_name=user.name,
        read_count=0,
    )


@router.delete("/system-news/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> None:
    news = await db.get(SystemNews, news_id)
    if news is None:
        raise HTTPException(status_code=404, detail="News not found")
    await db.delete(news)
    await db.commit()
