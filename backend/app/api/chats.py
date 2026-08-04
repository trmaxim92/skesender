from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import String, and_, cast, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.appeals import ensure_open_appeal, get_current_appeal
from app.config import get_settings
from app.db import get_db
from app.departments import accessible_department_ids, ensure_department_access
from app.deps import bearer, get_current_user
from app.fields import (
    field_def_to_out,
    list_field_definitions,
    load_field_values,
    upsert_field_value,
)
from app.integrations.base import IntegrationError
from app.integrations.registry import get_adapter
from app.models import (
    Appeal,
    AppealStatus,
    Channel,
    ChannelStatus,
    ChannelTransport,
    ChatMessage,
    Dialog,
    FieldScope,
    MessageAttachment,
    MessageDirection,
    MessageStatus,
    MessageTemplate,
    TemplateKind,
    User,
    utcnow,
)
from app.rbac import (
    ACTION_WRITE,
    SECTION_CHATS,
    accessible_channel_ids,
    ensure_channel_access,
    load_user_rbac,
    require_permission,
    role_all_channels,
    user_can,
)
from app.realtime.publish import (
    dialog_assigned_event,
    dialog_to_out,
    dialog_updated_event,
    emit_event,
    message_created_event,
    message_deleted_event,
    message_updated_event,
)
from app.schemas import (
    AppealFieldsUpdateRequest,
    AppealOut,
    AssignDialogRequest,
    ClientCardOut,
    ClientFieldsUpdateRequest,
    CreateNoteRequest,
    DialogOut,
    DialogsPageOut,
    DialogSidebarOut,
    EditMessageRequest,
    MessageOut,
    MessagesPageOut,
    StartChatOut,
    StartChatRequest,
    UnreadSummaryOut,
)
from app.security import decode_access_token, token_version_matches
from app.serializers import message_preview_text, message_to_out
from app.storage.attachments import absolute_path, guess_kind, save_bytes
from app.dialogs import claim_if_unassigned, clear_unread, get_or_create_dialog, heal_stale_outbound_unread
from app.outbound_start import PeerResolveError, resolve_outbound_peer, transport_allows_start

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["chats"])

_DIALOG_LOAD = (
    selectinload(Dialog.channel),
    selectinload(Dialog.assignee),
    selectinload(Dialog.current_appeal).selectinload(Appeal.closed_by),
)

_MESSAGE_LOAD_OPTIONS = (
    selectinload(ChatMessage.attachments),
    selectinload(ChatMessage.reply_to).selectinload(ChatMessage.attachments),
)


class OutboundDeliveryFailed(IntegrationError):
    """Provider send failed after a durable CRM draft was marked failed."""

    def __init__(self, detail: str, *, message_id: int):
        super().__init__(detail)
        self.message_id = message_id


def _require_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    from app.presence import presence_allows_write

    if not presence_allows_write(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Текущий статус не позволяет писать в чаты",
        )


async def _require_dialog_access(user: User, dialog: Dialog, db: AsyncSession) -> None:
    await ensure_channel_access(user, dialog.channel_id, db)
    await ensure_department_access(user, dialog.department_id, db)


async def _apply_dialog_acl(stmt, user: User, db: AsyncSession):
    channel_ids = await accessible_channel_ids(user, db)
    if channel_ids is not None:
        if not channel_ids:
            return None
        stmt = stmt.where(Dialog.channel_id.in_(channel_ids))
    dept_ids = await accessible_department_ids(user, db)
    if dept_ids is not None:
        if not dept_ids:
            return None
        stmt = stmt.where(Dialog.department_id.in_(dept_ids))
    return stmt


async def _load_message(db: AsyncSession, message_id: int) -> ChatMessage:
    result = await db.execute(
        select(ChatMessage).options(*_MESSAGE_LOAD_OPTIONS).where(ChatMessage.id == message_id)
    )
    return result.scalar_one()


async def _message_by_external(
    db: AsyncSession, channel_id: int, external_id: str
) -> ChatMessage | None:
    result = await db.execute(
        select(ChatMessage)
        .options(*_MESSAGE_LOAD_OPTIONS)
        .where(
            ChatMessage.channel_id == channel_id,
            ChatMessage.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


async def _create_outbound_draft(
    db: AsyncSession,
    *,
    dialog: Dialog,
    channel: Channel,
    appeal_id: int,
    user: User,
    text: str,
    reply_to_message_id: int | None,
    upload: tuple[bytes, str, str | None] | None,
) -> ChatMessage:
    """Insert outbound row before provider call (status=sent, no external_id yet)."""
    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal_id,
        external_id=None,
        direction=MessageDirection.OUT.value,
        text=text,
        status=MessageStatus.SENT.value,
        operator_id=user.id,
        operator_name=user.name,
        reply_to_message_id=reply_to_message_id,
        created_at=utcnow(),
    )
    db.add(msg)
    await db.flush()
    if upload is not None:
        raw, filename, mime = upload
        kind = guess_kind(mime, filename)
        relative, safe_name, resolved_mime, size = save_bytes(
            data=raw,
            file_name=filename,
            message_id=msg.id,
            mime_type=mime,
        )
        db.add(
            MessageAttachment(
                message_id=msg.id,
                kind=kind.value,
                file_name=safe_name,
                mime_type=resolved_mime,
                size_bytes=size,
                storage_path=relative,
            )
        )
        await db.flush()
    return msg


async def _finalize_outbound(
    db: AsyncSession,
    msg: ChatMessage,
    *,
    channel_id: int,
    external_id: str | None,
) -> ChatMessage:
    """Attach provider id after successful send; reuse row on unique race."""
    msg.external_id = external_id
    msg.status = MessageStatus.DELIVERED.value
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        if not external_id:
            raise
        existing = await _message_by_external(db, channel_id, external_id)
        if existing is None:
            raise
        if existing.id != msg.id:
            # Echo/other writer won the unique key — drop our draft duplicate.
            await db.delete(msg)
            await db.flush()
        return existing
    return await _load_message(db, msg.id)


async def _mark_outbound_failed(db: AsyncSession, msg: ChatMessage) -> ChatMessage:
    msg.status = MessageStatus.FAILED.value
    await db.flush()
    return await _load_message(db, msg.id)


async def _deliver_outbound_part(
    db: AsyncSession,
    *,
    dialog: Dialog,
    channel: Channel,
    appeal_id: int,
    user: User,
    text: str,
    reply_to_message_id: int | None,
    upload: tuple[bytes, str, str | None] | None,
    send,
) -> ChatMessage:
    """DB-first outbound: draft commit → provider → delivered/failed.

    Survives crash after provider accept: CRM keeps the row (sent/failed) instead of
    an orphan-only message on Telegram/MAX/webchat.
    """
    msg = await _create_outbound_draft(
        db,
        dialog=dialog,
        channel=channel,
        appeal_id=appeal_id,
        user=user,
        text=text,
        reply_to_message_id=reply_to_message_id,
        upload=upload,
    )
    msg_id = msg.id
    # Durable before provider I/O (also flushes pending dialog/appeal changes).
    await db.commit()
    try:
        send_result = await send()
    except IntegrationError as exc:
        msg = await db.get(ChatMessage, msg_id)
        if msg is not None:
            await _mark_outbound_failed(db, msg)
            await db.commit()
            raise OutboundDeliveryFailed(str(exc), message_id=msg_id) from exc
        raise
    msg = await db.get(ChatMessage, msg_id)
    if msg is None:
        raise IntegrationError("Outbound draft disappeared after commit")
    finalized = await _finalize_outbound(
        db, msg, channel_id=channel.id, external_id=send_result.external_id
    )
    await db.commit()
    return finalized


async def _publish_failed_outbound(
    db: AsyncSession, *, dialog_id: int, message_id: int
) -> None:
    """Push failed outbound into realtime so the timeline shows the ! tick."""
    loaded = await _load_message(db, message_id)
    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id))
    dialog_loaded = result.scalar_one()
    preview = message_preview_text(loaded.text or "", list(loaded.attachments or []))
    dialog_loaded.last_message = preview or loaded.text or ""
    dialog_loaded.last_direction = MessageDirection.OUT.value
    dialog_loaded.last_status = loaded.status
    dialog_loaded.last_at = loaded.created_at
    await db.commit()
    await emit_event(message_created_event(dialog_loaded, loaded))


async def _refresh_dialog_preview(db: AsyncSession, dialog: Dialog) -> None:
    """Update dialog.last_* from the latest non-internal, non-deleted message."""
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


def to_dialog_out(dialog: Dialog) -> DialogOut:
    return dialog_to_out(dialog)


def _appeal_to_out(appeal: Appeal) -> AppealOut:
    return AppealOut(
        id=appeal.id,
        dialog_id=appeal.dialog_id,
        number=appeal.number,
        status=appeal.status,  # type: ignore[arg-type]
        opened_at=appeal.opened_at,
        closed_at=appeal.closed_at,
        closed_by_id=appeal.closed_by_id,
        closed_by_name=appeal.closed_by.name if appeal.closed_by else None,
    )


@router.get("/dialogs", response_model=DialogsPageOut)
async def list_dialogs(
    filter: str = Query("new"),
    appeal_status: str = Query("open"),
    q: str = Query(""),
    channel_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogsPageOut:
    # new|unassigned → без оператора; mine → мои; others → чужие; all → без фильтра assignee
    filter_key = {
        "new": "new",
        "unassigned": "new",
        "all": "all",
        "mine": "mine",
        "others": "others",
        "foreign": "others",
    }.get(filter)
    if filter_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="filter must be new|mine|others|all",
        )
    if appeal_status not in {"all", "open", "closed"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="appeal_status must be all|open|closed",
        )

    stmt = select(Dialog).options(*_DIALOG_LOAD).order_by(Dialog.last_at.desc(), Dialog.id.desc())
    stmt = await _apply_dialog_acl(stmt, user, db)
    if stmt is None:
        return DialogsPageOut(items=[], has_more=False, limit=limit, offset=offset)
    if filter_key == "new":
        stmt = stmt.where(Dialog.assignee_id.is_(None))
    elif filter_key == "mine":
        stmt = stmt.where(Dialog.assignee_id == user.id)
    elif filter_key == "others":
        stmt = stmt.where(
            Dialog.assignee_id.is_not(None),
            Dialog.assignee_id != user.id,
        )
    # filter_key == "all": no assignee predicate

    if channel_id is not None:
        await ensure_channel_access(user, channel_id, db)
        stmt = stmt.where(Dialog.channel_id == channel_id)

    if appeal_status == "open":
        # Missing current_appeal treated as open (legacy rows).
        open_ids = select(Appeal.id).where(Appeal.status == AppealStatus.OPEN.value)
        stmt = stmt.where(
            or_(Dialog.current_appeal_id.is_(None), Dialog.current_appeal_id.in_(open_ids))
        )
    elif appeal_status == "closed":
        closed_ids = select(Appeal.id).where(Appeal.status == AppealStatus.CLOSED.value)
        stmt = stmt.where(Dialog.current_appeal_id.in_(closed_ids))

    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        conditions = [
            Dialog.contact_name.ilike(like),
            Dialog.contact_phone.ilike(like),
            Dialog.contact_username.ilike(like),
            Dialog.contact_external_id.ilike(like),
            Dialog.id.in_(
                select(Appeal.dialog_id).where(cast(Appeal.number, String).ilike(like))
            ),
        ]
        if needle.lstrip("#").isdigit():
            conditions.append(cast(Dialog.id, String).ilike(like))
            num = int(needle.lstrip("#"))
            conditions.append(
                Dialog.id.in_(select(Appeal.dialog_id).where(Appeal.number == num))
            )
        stmt = stmt.where(or_(*conditions))

    stmt = stmt.offset(offset).limit(limit + 1)
    result = await db.execute(stmt)
    dialogs = list(result.scalars().all())
    has_more = len(dialogs) > limit
    if has_more:
        dialogs = dialogs[:limit]
    return DialogsPageOut(
        items=[to_dialog_out(d) for d in dialogs],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-summary", response_model=UnreadSummaryOut)
async def unread_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> UnreadSummaryOut:
    """Сумма непрочитанных по вкладкам Новые / Мои / Чужие (только открытые обращения)."""
    healed = await heal_stale_outbound_unread(db)
    if healed:
        await db.commit()

    channel_ids = await accessible_channel_ids(user, db)
    dept_ids = await accessible_department_ids(user, db)

    async def _sum(predicate) -> int:
        if channel_ids is not None and not channel_ids:
            return 0
        if dept_ids is not None and not dept_ids:
            return 0
        # Same "open" definition as list_dialogs (legacy rows without current_appeal).
        open_ids = select(Appeal.id).where(Appeal.status == AppealStatus.OPEN.value)
        stmt = (
            select(func.coalesce(func.sum(Dialog.unread), 0))
            .select_from(Dialog)
            .where(
                Dialog.unread > 0,
                or_(
                    Dialog.current_appeal_id.is_(None),
                    Dialog.current_appeal_id.in_(open_ids),
                ),
                predicate,
            )
        )
        if channel_ids is not None:
            stmt = stmt.where(Dialog.channel_id.in_(channel_ids))
        if dept_ids is not None:
            stmt = stmt.where(Dialog.department_id.in_(dept_ids))
        return int(await db.scalar(stmt) or 0)

    return UnreadSummaryOut(
        new=await _sum(Dialog.assignee_id.is_(None)),
        mine=await _sum(Dialog.assignee_id == user.id),
        others=await _sum(
            and_(Dialog.assignee_id.is_not(None), Dialog.assignee_id != user.id)
        ),
    )


@router.get("/dialogs/{dialog_id}/appeals", response_model=list[AppealOut])
async def list_dialog_appeals(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> list[AppealOut]:
    dialog = await db.get(Dialog, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    result = await db.execute(
        select(Appeal)
        .options(selectinload(Appeal.closed_by))
        .where(Appeal.dialog_id == dialog.id)
        .order_by(Appeal.number.asc())
    )
    return [_appeal_to_out(a) for a in result.scalars().all()]


@router.get("/dialogs/{dialog_id}/messages", response_model=MessagesPageOut)
async def list_messages(
    dialog_id: int,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None),
    appeal_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> MessagesPageOut:
    dialog = await db.get(Dialog, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    if appeal_id is not None:
        appeal = await db.get(Appeal, appeal_id)
        if appeal is None or appeal.dialog_id != dialog.id:
            # Stale client appeal_id after dialog switch — fall back to current appeal.
            appeal_id = dialog.current_appeal_id
            if appeal_id is not None:
                appeal = await db.get(Appeal, appeal_id)
                if appeal is None or appeal.dialog_id != dialog.id:
                    appeal_id = None
            else:
                appeal_id = None

    stmt = (
        select(ChatMessage)
        .options(*_MESSAGE_LOAD_OPTIONS)
        .where(ChatMessage.dialog_id == dialog_id)
    )
    if appeal_id is not None:
        # Legacy rows without appeal_id show only under the current appeal.
        if dialog.current_appeal_id == appeal_id:
            stmt = stmt.where(
                or_(ChatMessage.appeal_id == appeal_id, ChatMessage.appeal_id.is_(None))
            )
        else:
            stmt = stmt.where(ChatMessage.appeal_id == appeal_id)
    if before_id is not None:
        pivot = await db.get(ChatMessage, before_id)
        if pivot is None or pivot.dialog_id != dialog_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid before_id")
        stmt = stmt.where(
            or_(
                ChatMessage.created_at < pivot.created_at,
                and_(
                    ChatMessage.created_at == pivot.created_at,
                    ChatMessage.id < pivot.id,
                ),
            )
        )
    stmt = stmt.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    rows.reverse()

    # Mark read only on the newest page of the current appeal (initial open).
    viewing_current = appeal_id is None or appeal_id == dialog.current_appeal_id
    if before_id is None and viewing_current:
        await clear_unread(db, dialog)
        result_dialog = await db.execute(
            select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id)
        )
        dialog_loaded = result_dialog.scalar_one()
        event = dialog_updated_event(dialog_loaded)
        await db.commit()
        await emit_event(event)
    else:
        await db.commit()

    return MessagesPageOut(
        items=[message_to_out(m) for m in rows],
        has_more=has_more,
    )


@router.post("/dialogs/{dialog_id}/read", response_model=DialogOut)
async def mark_dialog_read(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogOut:
    """Atomic unread clear for an open chat (WS inbound while viewing)."""
    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id))
    dialog = result.scalar_one_or_none()
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    cleared = await clear_unread(db, dialog)
    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id))
    dialog_loaded = result.scalar_one()
    out = to_dialog_out(dialog_loaded)
    await db.commit()
    if cleared:
        await emit_event(dialog_updated_event(dialog_loaded))
    return out


@router.post("/start", response_model=StartChatOut)
async def start_outbound_chat(
    body: StartChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> StartChatOut:
    """Create/open dialog + appeal and send the first outbound text."""
    _require_write(user)
    user = await load_user_rbac(db, user)

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Введите текст сообщения")

    channel = await db.get(Channel, body.channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
    await ensure_channel_access(user, channel.id, db)
    await ensure_department_access(user, channel.department_id, db)

    transport = channel.transport if isinstance(channel.transport, str) else channel.transport.value
    if not transport_allows_start(transport):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот тип канала не поддерживает исходящий старт",
        )
    if channel.status != ChannelStatus.ONLINE.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Канал не онлайн")
    if not channel.credentials_enc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Канал недоступен")

    try:
        peer = await resolve_outbound_peer(channel, body.recipient, db)
    except PeerResolveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    dialog = await get_or_create_dialog(
        db,
        channel=channel,
        external_chat_id=peer.external_chat_id,
        contact_external_id=peer.contact_external_id,
        contact_name=peer.contact_name,
        contact_username=peer.contact_username,
    )
    if peer.contact_phone and not dialog.contact_phone:
        dialog.contact_phone = peer.contact_phone
    if peer.contact_username and not dialog.contact_username:
        dialog.contact_username = peer.contact_username
    if peer.contact_name and (
        not dialog.contact_name or dialog.contact_name in {dialog.external_chat_id, peer.external_chat_id}
    ):
        dialog.contact_name = peer.contact_name

    appeal = await ensure_open_appeal(db, dialog)
    dialog.assignee_id = user.id

    adapter = get_adapter(channel.transport)

    async def _send():
        return await adapter.send_text(channel, dialog, text)

    try:
        msg = await _deliver_outbound_part(
            db,
            dialog=dialog,
            channel=channel,
            appeal_id=appeal.id,
            user=user,
            text=text,
            reply_to_message_id=None,
            upload=None,
            send=_send,
        )
    except OutboundDeliveryFailed as exc:
        await _publish_failed_outbound(db, dialog_id=dialog.id, message_id=exc.message_id)
        detail = str(exc)
        low = detail.lower()
        if "chat not found" in low:
            detail = (
                "Telegram: чат не найден. Для бота нужен числовой chat id "
                "(после /start диалог появится в «Чатах»). "
                "@username для лички Bot API обычно не принимает — "
                "либо укажите user id, либо канал «Telegram · аккаунт»."
            )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except IntegrationError as exc:
        detail = str(exc)
        low = detail.lower()
        if "chat not found" in low:
            detail = (
                "Telegram: чат не найден. Для бота нужен числовой chat id "
                "(после /start диалог появится в «Чатах»). "
                "@username для лички Bot API обычно не принимает — "
                "либо укажите user id, либо канал «Telegram · аккаунт»."
            )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc

    preview = message_preview_text(msg.text or "", list(msg.attachments or [])) or text
    dialog.last_message = preview
    dialog.last_direction = MessageDirection.OUT.value
    dialog.last_status = msg.status
    dialog.last_at = msg.created_at
    await clear_unread(db, dialog)

    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id))
    dialog_loaded = result.scalar_one()
    loaded_msg = await _load_message(db, msg.id)
    event = message_created_event(dialog_loaded, loaded_msg)
    await db.commit()
    await emit_event(event)

    return StartChatOut(dialog=dialog_to_out(dialog_loaded), message=message_to_out(loaded_msg))


@router.post("/dialogs/{dialog_id}/messages", response_model=MessageOut)
async def send_dialog_message(
    dialog_id: int,
    response: Response,
    text: str = Form(default=""),
    files: list[UploadFile] | None = File(default=None),
    reply_to_message_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> MessageOut:
    _require_write(user)

    dialog = await db.get(Dialog, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    current = await get_current_appeal(db, dialog)
    if current is None or current.status != AppealStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Обращение закрыто. Дождитесь нового сообщения клиента.",
        )

    channel = await db.get(Channel, dialog.channel_id)
    if channel is None or not channel.credentials_enc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Channel unavailable")

    reply_target: ChatMessage | None = None
    reply_external_id: str | None = None
    if reply_to_message_id is not None:
        reply_target = await db.get(ChatMessage, reply_to_message_id)
        if reply_target is None or reply_target.dialog_id != dialog.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reply target not found in this dialog",
            )
        if not reply_target.external_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reply: target message has no provider id",
            )
        reply_external_id = reply_target.external_id

    caption = (text or "").strip()
    uploads: list[tuple[bytes, str, str | None]] = []
    settings = get_settings()
    for upload in files or []:
        raw = await upload.read()
        if not raw:
            continue
        if len(raw) > settings.attachment_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large (max {settings.attachment_max_bytes} bytes)",
            )
        uploads.append((raw, upload.filename or "file", upload.content_type))

    if not caption and not uploads:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty message")

    adapter = get_adapter(channel.transport)
    created: list[ChatMessage] = []
    send_error: str | None = None
    try:
        if uploads:
            # One provider message per file — each gets its own DB row + external_id.
            for index, (raw, filename, mime) in enumerate(uploads):
                kind = guess_kind(mime, filename).value
                part_caption = caption if index == 0 else ""
                part_reply = reply_external_id if index == 0 else None
                part_reply_db = reply_target.id if reply_target and index == 0 else None

                async def _send_media(
                    _raw=raw,
                    _filename=filename,
                    _mime=mime,
                    _kind=kind,
                    _caption=part_caption,
                    _reply=part_reply,
                ):
                    return await adapter.send_media(
                        channel,
                        dialog,
                        kind=_kind,
                        data=_raw,
                        filename=_filename,
                        mime_type=_mime,
                        caption=_caption or None,
                        reply_to_external_id=_reply,
                    )

                try:
                    msg = await _deliver_outbound_part(
                        db,
                        dialog=dialog,
                        channel=channel,
                        appeal_id=current.id,
                        user=user,
                        text=part_caption,
                        reply_to_message_id=part_reply_db,
                        upload=(raw, filename, mime),
                        send=_send_media,
                    )
                except OutboundDeliveryFailed as exc:
                    send_error = str(exc)
                    await _publish_failed_outbound(
                        db, dialog_id=dialog.id, message_id=exc.message_id
                    )
                    break
                except IntegrationError as exc:
                    send_error = str(exc)
                    break
                created.append(msg)
        else:

            async def _send_text():
                return await adapter.send_text(
                    channel,
                    dialog,
                    caption,
                    reply_to_external_id=reply_external_id,
                )

            try:
                msg = await _deliver_outbound_part(
                    db,
                    dialog=dialog,
                    channel=channel,
                    appeal_id=current.id,
                    user=user,
                    text=caption,
                    reply_to_message_id=reply_target.id if reply_target else None,
                    upload=None,
                    send=_send_text,
                )
            except OutboundDeliveryFailed as exc:
                await _publish_failed_outbound(
                    db, dialog_id=dialog.id, message_id=exc.message_id
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
                ) from exc
            created.append(msg)
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if not created:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=send_error or "Send failed",
        )

    last = created[-1]
    preview = message_preview_text(
        last.text or "",
        list(last.attachments or []),
    )
    if not preview and last.text:
        preview = last.text
    dialog.last_message = preview or caption or (uploads[0][1] if uploads else "")
    dialog.last_direction = MessageDirection.OUT.value
    dialog.last_status = last.status
    dialog.last_at = last.created_at
    # Ответ оператора = чат просмотрен; иначе бейдж остаётся при last_direction=out.
    await clear_unread(db, dialog)
    # Первый ответивший на незанятое обращение становится ответственным.
    claimed = await claim_if_unassigned(db, dialog, user.id)

    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
    )
    dialog_loaded = result.scalar_one()
    events = []
    outs: list[MessageOut] = []
    for msg in created:
        loaded = await _load_message(db, msg.id)
        events.append(message_created_event(dialog_loaded, loaded))
        outs.append(message_to_out(loaded))
    if claimed:
        events.append(dialog_assigned_event(dialog_loaded))
        events.append(dialog_updated_event(dialog_loaded))
    await db.commit()
    for event in events:
        await emit_event(event)

    if send_error:
        # Partial success: messages already committed + pushed over WS.
        # Return 200 so the client does not treat the whole send as failed.
        logger.warning(
            "Partial multi-file send dialog=%s created=%s/%s: %s",
            dialog_id,
            len(created),
            len(uploads),
            send_error,
        )
        response.headers["X-SkySender-Warning"] = (
            f"Отправлено {len(created)} из {len(uploads)}: {send_error}"
        )[:500]
    return outs[-1]


@router.post("/dialogs/{dialog_id}/notes", response_model=MessageOut)
async def create_dialog_note(
    dialog_id: int,
    body: CreateNoteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> MessageOut:
    """Internal manager note — stored in the thread, never sent to the client."""
    _require_write(user)

    dialog = await db.get(Dialog, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty note")

    target_appeal_id: int | None = None
    if body.appeal_id is not None:
        appeal = await db.get(Appeal, body.appeal_id)
        if appeal is None or appeal.dialog_id != dialog.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Appeal not found in this dialog",
            )
        target_appeal_id = appeal.id
    else:
        current = await get_current_appeal(db, dialog)
        target_appeal_id = current.id if current else None

    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=dialog.channel_id,
        appeal_id=target_appeal_id,
        external_id=None,
        direction=MessageDirection.OUT.value,
        text=text,
        status=MessageStatus.DELIVERED.value,
        operator_id=user.id,
        operator_name=user.name,
        is_internal=True,
        created_at=utcnow(),
    )
    db.add(msg)
    await db.flush()

    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
    )
    dialog_loaded = result.scalar_one()
    loaded = await _load_message(db, msg.id)
    event = message_created_event(dialog_loaded, loaded)
    out = message_to_out(loaded)
    await db.commit()
    await emit_event(event)
    return out


@router.post("/dialogs/{dialog_id}/close", response_model=DialogOut)
async def close_dialog_appeal(
    dialog_id: int,
    response: Response,
    with_reply: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogOut:
    _require_write(user)

    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id))
    dialog = result.scalar_one_or_none()
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    appeal = await get_current_appeal(db, dialog)
    if appeal is None or appeal.status != AppealStatus.OPEN.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет открытого обращения")

    channel = await db.get(Channel, dialog.channel_id)
    if channel is None or not channel.credentials_enc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Channel unavailable")

    reply_text = ""
    if with_reply:
        tpl_result = await db.execute(
            select(MessageTemplate)
            .where(MessageTemplate.kind == TemplateKind.APPEAL_CLOSED.value)
            .order_by(
                # Prefer system (shared) template over personal leftovers.
                MessageTemplate.created_by_id.is_not(None),
                MessageTemplate.updated_at.desc(),
            )
        )
        templates = list(tpl_result.scalars().all())
        # Prefer ownerless system row, then transport match.
        system = [t for t in templates if t.created_by_id is None]
        pool = system or templates
        tpl = next((t for t in pool if t.transport in {channel.transport, "all"}), None)
        if tpl is not None:
            reply_text = (
                tpl.body.replace("{{operator}}", user.name)
                .replace("{{contact}}", dialog.contact_name or "Клиент")
                .replace("{{appeal}}", str(appeal.number))
                .strip()
            )

    # Close first — never leave client with a goodbye while appeal stays open.
    appeal_id = appeal.id
    appeal.status = AppealStatus.CLOSED.value
    appeal.closed_at = utcnow()
    appeal.closed_by_id = user.id
    await clear_unread(db, dialog)
    await db.commit()

    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id))
    dialog_loaded = result.scalar_one()
    events = [dialog_updated_event(dialog_loaded)]
    reply_error: str | None = None
    created_msg: ChatMessage | None = None

    if reply_text:
        adapter = get_adapter(channel.transport)

        async def _send_close_reply():
            return await adapter.send_text(channel, dialog_loaded, reply_text)

        try:
            created_msg = await _deliver_outbound_part(
                db,
                dialog=dialog_loaded,
                channel=channel,
                appeal_id=appeal_id,
                user=user,
                text=reply_text,
                reply_to_message_id=None,
                upload=None,
                send=_send_close_reply,
            )
        except OutboundDeliveryFailed as exc:
            reply_error = str(exc)
            await _publish_failed_outbound(
                db, dialog_id=dialog.id, message_id=exc.message_id
            )
            logger.warning(
                "Close reply failed dialog=%s appeal=%s: %s",
                dialog_id,
                appeal_id,
                reply_error,
            )
        except IntegrationError as exc:
            reply_error = str(exc)
            logger.warning(
                "Close reply failed dialog=%s appeal=%s: %s",
                dialog_id,
                appeal_id,
                reply_error,
            )
        except IntegrityError as exc:
            reply_error = "Close reply conflicted with existing message"
            logger.warning(
                "Close reply conflict dialog=%s appeal=%s: %s",
                dialog_id,
                appeal_id,
                exc,
            )
        else:
            dialog_loaded.last_message = reply_text
            dialog_loaded.last_direction = MessageDirection.OUT.value
            dialog_loaded.last_status = created_msg.status
            dialog_loaded.last_at = created_msg.created_at
            await db.commit()
            result = await db.execute(
                select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
            )
            dialog_loaded = result.scalar_one()
            created_msg = await _load_message(db, created_msg.id)
            events = [
                dialog_updated_event(dialog_loaded),
                message_created_event(dialog_loaded, created_msg),
            ]

    out = to_dialog_out(dialog_loaded)
    for ev in events:
        await emit_event(ev)
    if reply_error:
        response.headers["X-SkySender-Warning"] = (
            f"Обращение закрыто, но шаблон не отправлен: {reply_error}"
        )[:500]
    return out


@router.get("/dialogs/{dialog_id}/sidebar", response_model=DialogSidebarOut)
async def dialog_sidebar(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogSidebarOut:
    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id))
    dialog = result.scalar_one_or_none()
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    appeals_result = await db.execute(
        select(Appeal)
        .options(selectinload(Appeal.closed_by))
        .where(Appeal.dialog_id == dialog.id)
        .order_by(Appeal.number.desc())
    )
    appeals = list(appeals_result.scalars().all())
    transport = None
    channel_name = None
    if dialog.channel is not None:
        transport = dialog.channel.transport
        channel_name = dialog.channel.name

    return DialogSidebarOut(
        client=ClientCardOut(
            contact_name=dialog.contact_name,
            contact_username=dialog.contact_username,
            contact_avatar_url=dialog.contact_avatar_url,
            contact_external_id=dialog.contact_external_id,
            contact_phone=dialog.contact_phone,
            channel_id=dialog.channel_id,
            transport=transport,  # type: ignore[arg-type]
            channel_name=channel_name,
            dialog_created_at=dialog.created_at,
            appeals_count=len(appeals),
            assignee_id=dialog.assignee_id,
            assignee_name=dialog.assignee.name if dialog.assignee else None,
            department_id=dialog.department_id,
        ),
        current_appeal=_appeal_to_out(dialog.current_appeal) if dialog.current_appeal else None,
        appeals=[_appeal_to_out(a) for a in appeals],
        client_fields=[
            field_def_to_out(f)
            for f in await list_field_definitions(db, scope=FieldScope.CLIENT.value)
        ],
        appeal_fields=[
            field_def_to_out(f)
            for f in await list_field_definitions(
                db,
                scope=FieldScope.APPEAL.value,
                department_id=dialog.department_id,
            )
        ]
        if dialog.department_id
        else [],
        client_values={
            "full_name": dialog.contact_name or "",
            "phone": dialog.contact_phone or "",
            "external_id": dialog.contact_external_id or "",
            **(await load_field_values(db, scope=FieldScope.CLIENT.value, owner_id=dialog.id)),
        },
        appeal_values=(
            await load_field_values(
                db,
                scope=FieldScope.APPEAL.value,
                owner_id=dialog.current_appeal.id,
            )
            if dialog.current_appeal
            else {}
        ),
    )


@router.patch("/dialogs/{dialog_id}/client-fields", response_model=DialogSidebarOut)
async def update_client_fields(
    dialog_id: int,
    body: ClientFieldsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogSidebarOut:
    _require_write(user)
    result = await db.execute(select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id))
    dialog = result.scalar_one_or_none()
    if dialog is None:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    if body.full_name is not None:
        dialog.contact_name = body.full_name.strip() or dialog.contact_name
    if body.phone is not None:
        dialog.contact_phone = body.phone.strip() or None
    if body.external_id is not None:
        dialog.contact_external_id = body.external_id.strip() or None

    defs = await list_field_definitions(db, scope=FieldScope.CLIENT.value)
    allowed = {f.key for f in defs if not f.is_system}
    for item in body.values:
        if item.key in {"full_name", "phone", "external_id"}:
            continue
        if item.key not in allowed:
            continue
        await upsert_field_value(
            db,
            scope=FieldScope.CLIENT.value,
            owner_id=dialog.id,
            field_key=item.key,
            value=item.value,
        )
    await db.commit()
    return await dialog_sidebar(dialog_id, db, user)


@router.patch("/appeals/{appeal_id}/fields", response_model=DialogSidebarOut)
async def update_appeal_fields(
    appeal_id: int,
    body: AppealFieldsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogSidebarOut:
    _require_write(user)
    appeal = await db.get(Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(status_code=404, detail="Appeal not found")
    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == appeal.dialog_id)
    )
    dialog = result.scalar_one_or_none()
    if dialog is None:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    defs = await list_field_definitions(
        db, scope=FieldScope.APPEAL.value, department_id=dialog.department_id
    )
    allowed = {f.key for f in defs}
    for item in body.values:
        if item.key not in allowed:
            continue
        await upsert_field_value(
            db,
            scope=FieldScope.APPEAL.value,
            owner_id=appeal.id,
            field_key=item.key,
            value=item.value,
        )
    await db.commit()
    return await dialog_sidebar(dialog.id, db, user)


@router.patch("/dialogs/{dialog_id}/messages/{message_id}", response_model=MessageOut)
async def edit_dialog_message(
    dialog_id: int,
    message_id: int,
    body: EditMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> MessageOut:
    _require_write(user)

    dialog = await db.get(Dialog, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    msg = await db.get(ChatMessage, message_id)
    if msg is None or msg.dialog_id != dialog.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if msg.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message deleted")
    if msg.direction != MessageDirection.OUT.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only edit outbound")

    new_text = body.text.strip()
    if not new_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty text")

    if msg.is_internal:
        msg.text = new_text
        msg.edited_at = utcnow()
        await db.flush()
        msg = await _load_message(db, msg.id)
        result = await db.execute(
            select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
        )
        dialog_loaded = result.scalar_one()
        event = message_updated_event(dialog_loaded, msg)
        out = message_to_out(msg)
        await db.commit()
        await emit_event(event)
        return out

    if not msg.external_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message has no provider id")

    channel = await db.get(Channel, dialog.channel_id)
    if channel is None or not channel.credentials_enc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Channel unavailable")

    # DB-first: CRM leads; revert if provider rejects the edit.
    previous_text = msg.text
    previous_edited_at = msg.edited_at
    msg.text = new_text
    msg.edited_at = utcnow()
    await db.commit()

    adapter = get_adapter(channel.transport)
    try:
        await adapter.edit_text(channel, dialog, external_id=msg.external_id, text=new_text)
    except IntegrationError as exc:
        msg.text = previous_text
        msg.edited_at = previous_edited_at
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    msg = await _load_message(db, msg.id)
    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
    )
    dialog_loaded = result.scalar_one()
    await _refresh_dialog_preview(db, dialog_loaded)

    event = message_updated_event(dialog_loaded, msg)
    out = message_to_out(msg)
    await db.commit()
    await emit_event(event)
    return out


@router.delete("/dialogs/{dialog_id}/messages/{message_id}", response_model=MessageOut)
async def delete_dialog_message(
    dialog_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> MessageOut:
    _require_write(user)

    dialog = await db.get(Dialog, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)

    msg = await db.get(ChatMessage, message_id)
    if msg is None or msg.dialog_id != dialog.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if msg.deleted_at is not None:
        msg = await _load_message(db, msg.id)
        return message_to_out(msg)
    if msg.direction != MessageDirection.OUT.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only delete outbound")

    if msg.is_internal:
        msg.deleted_at = utcnow()
        await db.flush()
        msg = await _load_message(db, msg.id)
        result = await db.execute(
            select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
        )
        dialog_loaded = result.scalar_one()
        event = message_deleted_event(dialog_loaded, msg)
        out = message_to_out(msg)
        await db.commit()
        await emit_event(event)
        return out

    if not msg.external_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message has no provider id")

    channel = await db.get(Channel, dialog.channel_id)
    if channel is None or not channel.credentials_enc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Channel unavailable")

    # Soft-delete in CRM first; undelete if provider delete fails.
    msg.deleted_at = utcnow()
    await db.commit()

    adapter = get_adapter(channel.transport)
    try:
        await adapter.delete_message(channel, dialog, external_id=msg.external_id)
    except IntegrationError as exc:
        msg.deleted_at = None
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    msg = await _load_message(db, msg.id)
    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
    )
    dialog_loaded = result.scalar_one()
    await _refresh_dialog_preview(db, dialog_loaded)

    event = message_deleted_event(dialog_loaded, msg)
    out = message_to_out(msg)
    await db.commit()
    await emit_event(event)
    return out


@router.post("/messages/{message_id}/repair-media", response_model=MessageOut)
async def repair_message_media_endpoint(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> MessageOut:
    """Re-fetch MAX attachments for messages that landed as empty «[медиа]»."""
    _require_write(user)
    msg = await _load_message(db, message_id)
    dialog = await db.get(Dialog, msg.dialog_id)
    if dialog is None:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await _require_dialog_access(user, dialog, db)
    channel = await db.get(Channel, msg.channel_id)
    if channel is None or channel.transport != ChannelTransport.MAX.value:
        raise HTTPException(status_code=400, detail="Repair supported only for MAX personal")
    if msg.attachments:
        return message_to_out(msg)

    from app.integrations.max_personal.inbox import repair_message_media
    from app.integrations.max_personal.runtime import runtime as max_runtime

    try:
        client = await max_runtime.ensure_client(channel.id)
        stored = await repair_message_media(
            db, msg=msg, channel=channel, client=client
        )
    except IntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("repair-media failed message=%s", message_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not stored:
        raise HTTPException(status_code=404, detail="MAX did not return attachments for this message")

    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog.id)
    )
    dialog_loaded = result.scalar_one()
    await _refresh_dialog_preview(db, dialog_loaded)
    msg = await _load_message(db, msg.id)
    out = message_to_out(msg)
    event = message_updated_event(dialog_loaded, msg, channel.transport)
    await db.commit()
    await emit_event(event)
    return out


@router.get("/attachments/{attachment_id}", response_model=None)
async def download_attachment(
    attachment_id: int,
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> FileResponse | RedirectResponse:
    access = None
    if creds and creds.credentials:
        access = creds.credentials
    elif token:
        access = token
    payload = decode_access_token(access) if access else None
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    result = await db.execute(select(User).where(User.email == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not token_version_matches(payload, user.token_version):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    user = await load_user_rbac(db, user)

    att = await db.get(MessageAttachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    msg = await db.get(ChatMessage, att.message_id)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    dialog = await db.get(Dialog, msg.dialog_id)
    if dialog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    await _require_dialog_access(user, dialog, db)

    if not att.storage_path:
        if att.remote_url:
            return RedirectResponse(att.remote_url)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    try:
        path = absolute_path(att.storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        if att.remote_url:
            return RedirectResponse(att.remote_url)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing on disk")
    return FileResponse(
        path,
        media_type=att.mime_type or "application/octet-stream",
        filename=att.file_name,
        content_disposition_type="inline",
    )


@router.patch("/dialogs/{dialog_id}/assign", response_model=DialogOut)
async def assign_dialog(
    dialog_id: int,
    body: AssignDialogRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> DialogOut:
    _require_write(user)

    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id)
    )
    dialog_obj = result.scalar_one_or_none()
    if dialog_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialog not found")
    await _require_dialog_access(user, dialog_obj, db)

    current_assignee = dialog_obj.assignee_id
    new_assignee = body.assignee_id

    if current_assignee is None:
        # Unassigned: only self-claim (or no-op keep null).
        if new_assignee is not None and new_assignee != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Свободное обращение можно только забрать себе",
            )
    elif current_assignee != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Передать обращение может только ответственный менеджер",
        )

    if new_assignee is not None:
        assignee = (
            await db.execute(
                select(User)
                .options(selectinload(User.department_memberships), selectinload(User.access_role))
                .where(User.id == new_assignee)
            )
        ).scalar_one_or_none()
        if assignee is None or not assignee.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Менеджер не найден или неактивен",
            )
        if dialog_obj.department_id is not None and not role_all_channels(assignee):
            assignee_depts = {m.department_id for m in (assignee.department_memberships or [])}
            if dialog_obj.department_id not in assignee_depts:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Менеджер не состоит в отделе этого чата",
                )

    # Optimistic lock on assignee — last writer without check used to overwrite races.
    if current_assignee is None:
        claimed = await db.execute(
            update(Dialog)
            .where(Dialog.id == dialog_id, Dialog.assignee_id.is_(None))
            .values(assignee_id=new_assignee)
        )
    else:
        claimed = await db.execute(
            update(Dialog)
            .where(Dialog.id == dialog_id, Dialog.assignee_id == current_assignee)
            .values(assignee_id=new_assignee)
        )
    if claimed.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Обращение уже назначено другому менеджеру — обновите список",
        )

    await db.commit()
    result = await db.execute(
        select(Dialog).options(*_DIALOG_LOAD).where(Dialog.id == dialog_id)
    )
    dialog_obj = result.scalar_one()
    updated = dialog_updated_event(dialog_obj)
    assigned = dialog_assigned_event(dialog_obj)
    await emit_event(updated)
    await emit_event(assigned)
    return to_dialog_out(dialog_obj)

