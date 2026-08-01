from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.departments import accessible_department_ids, ensure_department_access
from app.models import (
    Appeal,
    AppealStatus,
    ChatMessage,
    Dialog,
    FieldScope,
    FieldValue,
    MessageAttachment,
    User,
)
from app.rbac import (
    ACTION_DELETE_APPEALS,
    SECTION_APPEALS,
    accessible_channel_ids,
    ensure_channel_access,
    require_permission,
)
from app.realtime.publish import dialog_updated_event, emit_event
from app.schemas import AppealDetailOut, AppealListItemOut, AppealListOut
from app.serializers import message_preview_text

router = APIRouter(prefix="/appeals", tags=["appeals"])


def _parse_day_start(value: str | None) -> datetime | None:
    if not value:
        return None
    day = datetime.fromisoformat(value).date()
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _parse_day_end(value: str | None) -> datetime | None:
    if not value:
        return None
    day = datetime.fromisoformat(value).date()
    return datetime.combine(day, time.max, tzinfo=timezone.utc)


def _to_item(appeal: Appeal) -> AppealListItemOut:
    dialog = appeal.dialog
    channel = dialog.channel if dialog is not None else None
    assignee = dialog.assignee if dialog is not None else None
    return AppealListItemOut(
        id=appeal.id,
        dialog_id=appeal.dialog_id,
        number=appeal.number,
        status=appeal.status,  # type: ignore[arg-type]
        opened_at=appeal.opened_at,
        closed_at=appeal.closed_at,
        closed_by_id=appeal.closed_by_id,
        closed_by_name=appeal.closed_by.name if appeal.closed_by else None,
        contact_name=dialog.contact_name if dialog else "Клиент",
        contact_username=dialog.contact_username if dialog else None,
        contact_external_id=dialog.contact_external_id if dialog else None,
        contact_avatar_url=dialog.contact_avatar_url if dialog else None,
        channel_id=dialog.channel_id if dialog else 0,
        channel_name=channel.name if channel else None,
        transport=channel.transport if channel else None,  # type: ignore[arg-type]
        assignee_id=dialog.assignee_id if dialog else None,
        assignee_name=assignee.name if assignee else None,
        last_message=dialog.last_message if dialog else "",
        last_at=dialog.last_at if dialog else appeal.opened_at,
    )


@router.get("", response_model=AppealListOut)
async def list_appeals(
    q: str | None = Query(default=None, description="Поиск по номеру, контакту, логину, тексту"),
    status_filter: str = Query("all", alias="status", pattern="^(all|open|closed)$"),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD по opened_at"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD по opened_at"),
    assignee: str = Query("all", pattern="^(all|unassigned|mine)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_APPEALS)),
) -> AppealListOut:
    stmt = (
        select(Appeal)
        .join(Dialog, Dialog.id == Appeal.dialog_id)
        .options(
            selectinload(Appeal.closed_by),
            selectinload(Appeal.dialog).selectinload(Dialog.channel),
            selectinload(Appeal.dialog).selectinload(Dialog.assignee),
        )
    )

    channel_ids = await accessible_channel_ids(user, db)
    if channel_ids is not None:
        if not channel_ids:
            return AppealListOut(items=[], total=0, limit=limit, offset=offset)
        stmt = stmt.where(Dialog.channel_id.in_(channel_ids))

    dept_ids = await accessible_department_ids(user, db)
    if dept_ids is not None:
        if not dept_ids:
            return AppealListOut(items=[], total=0, limit=limit, offset=offset)
        stmt = stmt.where(Dialog.department_id.in_(dept_ids))

    if status_filter != "all":
        stmt = stmt.where(Appeal.status == status_filter)

    start = _parse_day_start(date_from)
    end = _parse_day_end(date_to)
    if start is not None:
        stmt = stmt.where(Appeal.opened_at >= start)
    if end is not None:
        stmt = stmt.where(Appeal.opened_at <= end)

    if assignee == "unassigned":
        stmt = stmt.where(Dialog.assignee_id.is_(None))
    elif assignee == "mine":
        stmt = stmt.where(Dialog.assignee_id == user.id)

    query = (q or "").strip()
    if query:
        like = f"%{query}%"
        number_match = None
        if query.isdigit():
            number_match = Appeal.number == int(query)

        text_exists = exists(
            select(ChatMessage.id).where(
                ChatMessage.appeal_id == Appeal.id,
                ChatMessage.text.ilike(like),
            )
        )
        clauses = [
            Dialog.contact_name.ilike(like),
            Dialog.contact_username.ilike(like),
            Dialog.contact_external_id.ilike(like),
            Dialog.last_message.ilike(like),
            text_exists,
        ]
        if number_match is not None:
            clauses.append(number_match)
            clauses.append(Appeal.id == int(query))
        # also allow "#12" style
        if query.startswith("#") and query[1:].isdigit():
            clauses.append(Appeal.number == int(query[1:]))

        stmt = stmt.where(or_(*clauses))

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(await db.scalar(count_stmt) or 0)

    result = await db.execute(
        stmt.order_by(Appeal.opened_at.desc(), Appeal.id.desc()).offset(offset).limit(limit)
    )
    items = [_to_item(a) for a in result.scalars().all()]
    return AppealListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{appeal_id}", response_model=AppealDetailOut)
async def get_appeal(
    appeal_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_APPEALS)),
) -> AppealDetailOut:
    result = await db.execute(
        select(Appeal)
        .join(Dialog, Dialog.id == Appeal.dialog_id)
        .options(
            selectinload(Appeal.closed_by),
            selectinload(Appeal.dialog).selectinload(Dialog.channel),
            selectinload(Appeal.dialog).selectinload(Dialog.assignee),
            selectinload(Appeal.dialog).selectinload(Dialog.current_appeal),
        )
        .where(Appeal.id == appeal_id)
    )
    appeal = result.scalar_one_or_none()
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found")

    dialog = appeal.dialog
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")

    await ensure_channel_access(user, dialog.channel_id, db)
    await ensure_department_access(user, dialog.department_id, db)

    base = _to_item(appeal)
    current = dialog.current_appeal
    current_status = current.status if current else None
    can_open = current_status == AppealStatus.OPEN.value
    return AppealDetailOut(
        **base.model_dump(),
        current_appeal_id=dialog.current_appeal_id,
        current_appeal_status=current_status,  # type: ignore[arg-type]
        can_open_in_chats=can_open,
    )


async def _refresh_dialog_preview(db: AsyncSession, dialog: Dialog) -> None:
    latest = await db.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.attachments))
        .where(
            ChatMessage.dialog_id == dialog.id,
            ChatMessage.deleted_at.is_(None),
            ChatMessage.is_internal.is_(False),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    last_msg = latest.scalar_one_or_none()
    if last_msg is not None:
        dialog.last_message = message_preview_text(last_msg.text, last_msg.attachments)
        dialog.last_direction = last_msg.direction
        dialog.last_status = last_msg.status
        dialog.last_at = last_msg.created_at
    else:
        dialog.last_message = ""
        dialog.last_direction = None
        dialog.last_status = None


@router.delete("/{appeal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appeal(
    appeal_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(ACTION_DELETE_APPEALS)),
) -> None:
    """Hard-delete an appeal with its messages and appeal field values."""
    result = await db.execute(
        select(Appeal)
        .options(selectinload(Appeal.dialog).selectinload(Dialog.channel))
        .where(Appeal.id == appeal_id)
    )
    appeal = result.scalar_one_or_none()
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found")

    dialog = appeal.dialog
    if dialog is None:
        dialog = await db.get(Dialog, appeal.dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")

    await ensure_channel_access(user, dialog.channel_id, db)
    await ensure_department_access(user, dialog.department_id, db)

    msg_ids = select(ChatMessage.id).where(ChatMessage.appeal_id == appeal.id)
    await db.execute(delete(MessageAttachment).where(MessageAttachment.message_id.in_(msg_ids)))
    await db.execute(delete(ChatMessage).where(ChatMessage.appeal_id == appeal.id))
    await db.execute(
        delete(FieldValue).where(
            FieldValue.scope == FieldScope.APPEAL.value,
            FieldValue.owner_id == appeal.id,
        )
    )

    was_current = dialog.current_appeal_id == appeal.id
    dialog_id = dialog.id

    await db.delete(appeal)
    await db.flush()

    if was_current:
        remaining = await db.execute(
            select(Appeal)
            .where(Appeal.dialog_id == dialog_id)
            .order_by(Appeal.number.desc(), Appeal.id.desc())
            .limit(1)
        )
        next_appeal = remaining.scalar_one_or_none()
        dialog.current_appeal_id = next_appeal.id if next_appeal else None

    await _refresh_dialog_preview(db, dialog)

    loaded = await db.execute(
        select(Dialog)
        .options(
            selectinload(Dialog.channel),
            selectinload(Dialog.assignee),
            selectinload(Dialog.current_appeal).selectinload(Appeal.closed_by),
        )
        .where(Dialog.id == dialog_id)
    )
    dialog_loaded = loaded.scalar_one()
    event = dialog_updated_event(dialog_loaded)
    await db.commit()
    await emit_event(event)

