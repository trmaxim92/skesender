"""Contacts CRM module — phone leads, claim, comments, messenger outbound."""

from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.chats import execute_start_chat
from app.appeals import ensure_contact_appeal
from app.appeal_statuses import (
    apply_status_def_to_appeal,
    promote_contact_on_claim,
    sync_contact_status_from_stage,
)
from app.db import get_db
from app.departments import ensure_default_department
from app.fields import field_def_to_out, list_field_definitions, load_field_values, upsert_field_value
from app.models import (
    Appeal,
    AppealStatus,
    AppealStatusDef,
    Contact,
    ContactCallOutcome,
    ContactCallResult,
    ContactComment,
    ContactStatus,
    FieldScope,
    User,
    utcnow,
)
from app.rbac import (
    ACTION_WRITE,
    SECTION_CHATS,
    SECTION_CONTACTS,
    load_user_rbac,
    require_permission,
    user_can,
)
from app.schemas import (
    AppealOut,
    AppealStatusDefOut,
    ContactAppealStatusRequest,
    ContactCallResultOut,
    ContactClaimBatchRequest,
    ContactClaimBatchResult,
    ContactClaimSkipped,
    ContactCommentCreateRequest,
    ContactCommentOut,
    ContactCreateRequest,
    ContactFieldsUpdateRequest,
    ContactImportResult,
    ContactMessageRequest,
    ContactOut,
    ContactOutcomeRequest,
    ContactsPageOut,
    ContactsSummaryOut,
    ContactUpdateRequest,
    StartChatOut,
)

router = APIRouter(prefix="/contacts", tags=["contacts"])

_CONTACT_LOAD = (
    selectinload(Contact.assignee),
    selectinload(Contact.comments).selectinload(ContactComment.author),
    selectinload(Contact.call_results).selectinload(ContactCallResult.author),
)

_PHONE_STRIP = re.compile(r"[^\d+]")
_SYSTEM_KEYS = {"full_name", "phone", "external_id"}


def _require_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    from app.presence import presence_allows_write

    if not presence_allows_write(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Текущий статус не позволяет писать",
        )


def _normalize_phone(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    cleaned = _PHONE_STRIP.sub("", s)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


async def _contact_out(
    db: AsyncSession,
    c: Contact,
    *,
    with_comments: bool = False,
    with_fields: bool = False,
) -> ContactOut:
    comments: list[ContactCommentOut] = []
    if with_comments:
        for row in c.comments or []:
            comments.append(
                ContactCommentOut(
                    id=row.id,
                    text=row.text,
                    author_id=row.author_id,
                    author_name=row.author.name if row.author else None,
                    created_at=row.created_at,
                )
            )

    call_results: list[ContactCallResultOut] = []
    if with_comments:
        rows = sorted(c.call_results or [], key=lambda r: r.id, reverse=True)
        for row in rows[:30]:
            call_results.append(
                ContactCallResultOut(
                    id=row.id,
                    outcome=row.outcome,
                    note=row.note or "",
                    author_id=row.author_id,
                    author_name=row.author.name if row.author else None,
                    created_at=row.created_at,
                )
            )

    client_fields = []
    client_values: dict[str, str] = {}
    appeal_fields = []
    appeal_values: dict[str, str] = {}
    current_appeal: AppealOut | None = None
    appeal_statuses: list[AppealStatusDefOut] = []
    if with_fields:
        defs = await list_field_definitions(db, scope=FieldScope.CLIENT.value)
        client_fields = [field_def_to_out(f) for f in defs]
        stored = await load_field_values(
            db, scope=FieldScope.CONTACT.value, owner_id=c.id
        )
        client_values = {
            "full_name": c.name or "",
            "phone": c.phone or "",
            "external_id": stored.get("external_id", ""),
            **{k: v for k, v in stored.items() if k not in _SYSTEM_KEYS},
        }
        if not client_values["full_name"] and stored.get("full_name"):
            client_values["full_name"] = stored["full_name"]
        if not client_values["phone"] and stored.get("phone"):
            client_values["phone"] = stored["phone"]

        dept_id = c.department_id
        if dept_id is None:
            general = await ensure_default_department(db)
            dept_id = general.id
        appeal_defs = await list_field_definitions(
            db, scope=FieldScope.APPEAL.value, department_id=dept_id
        )
        appeal_fields = [field_def_to_out(f) for f in appeal_defs]
        appeal_values = await load_field_values(
            db, scope=FieldScope.CONTACT_APPEAL.value, owner_id=c.id
        )

        status_rows = (
            await db.execute(
                select(AppealStatusDef)
                .where(AppealStatusDef.is_active.is_(True))
                .order_by(AppealStatusDef.sort_order, AppealStatusDef.id)
            )
        ).scalars().all()
        appeal_statuses = [AppealStatusDefOut.model_validate(r) for r in status_rows]

        appeal_row = (
            await db.execute(
                select(Appeal)
                .options(selectinload(Appeal.status_def), selectinload(Appeal.closed_by))
                .where(
                    Appeal.contact_id == c.id,
                    Appeal.status == AppealStatus.OPEN.value,
                )
                .order_by(Appeal.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if appeal_row is None:
            appeal_row = (
                await db.execute(
                    select(Appeal)
                    .options(selectinload(Appeal.status_def), selectinload(Appeal.closed_by))
                    .where(Appeal.contact_id == c.id)
                    .order_by(Appeal.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if appeal_row is not None:
            current_appeal = AppealOut(
                id=appeal_row.id,
                dialog_id=appeal_row.dialog_id,
                contact_id=appeal_row.contact_id,
                number=appeal_row.number,
                status=appeal_row.status,  # type: ignore[arg-type]
                status_id=appeal_row.status_id,
                status_def=(
                    AppealStatusDefOut.model_validate(appeal_row.status_def)
                    if appeal_row.status_def
                    else None
                ),
                opened_at=appeal_row.opened_at,
                closed_at=appeal_row.closed_at,
                closed_by_id=appeal_row.closed_by_id,
                closed_by_name=appeal_row.closed_by.name if appeal_row.closed_by else None,
            )

    return ContactOut(
        id=c.id,
        name=c.name or "",
        phone=c.phone,
        status=c.status,
        assignee_id=c.assignee_id,
        assignee_name=c.assignee.name if c.assignee else None,
        department_id=c.department_id,
        created_by_id=c.created_by_id,
        last_outcome=c.last_outcome,
        last_outcome_at=c.last_outcome_at,
        created_at=c.created_at,
        updated_at=c.updated_at,
        comments=comments,
        call_results=call_results,
        client_fields=client_fields,
        client_values=client_values,
        appeal_fields=appeal_fields,
        appeal_values=appeal_values,
        current_appeal=current_appeal,
        appeal_statuses=appeal_statuses,
    )


async def _get_contact(db: AsyncSession, contact_id: int) -> Contact:
    result = await db.execute(
        select(Contact).options(*_CONTACT_LOAD).where(Contact.id == contact_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    return contact


async def _apply_client_fields(
    db: AsyncSession,
    contact: Contact,
    *,
    full_name: str | None,
    phone: str | None,
    external_id: str | None,
    values: list,
    appeal_values: list | None = None,
    department_id: int | None = None,
) -> None:
    if department_id is not None:
        contact.department_id = department_id
    if full_name is not None:
        contact.name = full_name.strip() or contact.name
    if phone is not None:
        normalized = _normalize_phone(phone)
        if len(normalized) >= 5:
            contact.phone = normalized
    if external_id is not None:
        await upsert_field_value(
            db,
            scope=FieldScope.CONTACT.value,
            owner_id=contact.id,
            field_key="external_id",
            value=external_id.strip(),
        )

    defs = await list_field_definitions(db, scope=FieldScope.CLIENT.value)
    allowed = {f.key for f in defs if not f.is_system}
    for item in values:
        key = getattr(item, "key", None) or (item.get("key") if isinstance(item, dict) else None)
        value = getattr(item, "value", None)
        if value is None and isinstance(item, dict):
            value = item.get("value", "")
        if not key or key in _SYSTEM_KEYS:
            continue
        if key not in allowed:
            continue
        await upsert_field_value(
            db,
            scope=FieldScope.CONTACT.value,
            owner_id=contact.id,
            field_key=str(key),
            value=str(value or ""),
        )

    if appeal_values is not None:
        dept_id = contact.department_id
        if dept_id is None:
            general = await ensure_default_department(db)
            dept_id = general.id
            if contact.department_id is None:
                contact.department_id = dept_id
        appeal_defs = await list_field_definitions(
            db, scope=FieldScope.APPEAL.value, department_id=dept_id
        )
        allowed_appeal = {f.key for f in appeal_defs}
        for item in appeal_values:
            key = getattr(item, "key", None) or (item.get("key") if isinstance(item, dict) else None)
            value = getattr(item, "value", None)
            if value is None and isinstance(item, dict):
                value = item.get("value", "")
            if not key or key not in allowed_appeal:
                continue
            await upsert_field_value(
                db,
                scope=FieldScope.CONTACT_APPEAL.value,
                owner_id=contact.id,
                field_key=str(key),
                value=str(value or ""),
            )


@router.get("", response_model=ContactsPageOut)
async def list_contacts(
    q: str | None = Query(default=None),
    filter: str = Query(default="all", pattern="^(all|mine|callback|others)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactsPageOut:
    """all = свободные; mine = мои; callback = мои на перезвон; others = чужие."""
    stmt = select(Contact).options(selectinload(Contact.assignee))
    count_stmt = select(func.count()).select_from(Contact)

    if filter == "all":
        stmt = stmt.where(Contact.assignee_id.is_(None))
        count_stmt = count_stmt.where(Contact.assignee_id.is_(None))
    elif filter == "mine":
        stmt = stmt.where(Contact.assignee_id == user.id)
        count_stmt = count_stmt.where(Contact.assignee_id == user.id)
    elif filter == "callback":
        callback_ids = (
            select(Appeal.contact_id)
            .join(AppealStatusDef, Appeal.status_id == AppealStatusDef.id)
            .where(
                Appeal.contact_id.is_not(None),
                Appeal.status == AppealStatus.OPEN.value,
                AppealStatusDef.needs_callback.is_(True),
            )
        )
        stmt = stmt.where(
            Contact.assignee_id == user.id,
            Contact.id.in_(callback_ids),
            Contact.status != ContactStatus.DONE.value,
        )
        count_stmt = count_stmt.where(
            Contact.assignee_id == user.id,
            Contact.id.in_(callback_ids),
            Contact.status != ContactStatus.DONE.value,
        )
    elif filter == "others":
        stmt = stmt.where(Contact.assignee_id.is_not(None), Contact.assignee_id != user.id)
        count_stmt = count_stmt.where(
            Contact.assignee_id.is_not(None), Contact.assignee_id != user.id
        )

    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        cond = or_(Contact.name.ilike(like), Contact.phone.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar_one())
    result = await db.execute(
        stmt.order_by(Contact.updated_at.desc(), Contact.id.desc()).offset(offset).limit(limit)
    )
    rows = list(result.scalars().all())
    # Lightweight custom values for table columns (company / email).
    values_by_owner: dict[int, dict[str, str]] = {c.id: {} for c in rows}
    if rows:
        from app.models import FieldValue

        ids = [c.id for c in rows]
        fv_rows = (
            await db.execute(
                select(FieldValue).where(
                    FieldValue.scope == FieldScope.CONTACT.value,
                    FieldValue.owner_id.in_(ids),
                )
            )
        ).scalars().all()
        for fv in fv_rows:
            values_by_owner.setdefault(fv.owner_id, {})[fv.field_key] = fv.value_text

    items = []
    open_appeal_by_contact: dict[int, Appeal] = {}
    if rows:
        ids = [c.id for c in rows]
        appeal_rows = (
            await db.execute(
                select(Appeal)
                .options(selectinload(Appeal.status_def))
                .where(
                    Appeal.contact_id.in_(ids),
                    Appeal.status == AppealStatus.OPEN.value,
                )
                .order_by(Appeal.id.desc())
            )
        ).scalars().all()
        for a in appeal_rows:
            if a.contact_id is None or a.contact_id in open_appeal_by_contact:
                continue
            open_appeal_by_contact[a.contact_id] = a

    for c in rows:
        out = await _contact_out(db, c)
        out.client_values = {
            "full_name": c.name or "",
            "phone": c.phone or "",
            **values_by_owner.get(c.id, {}),
        }
        a = open_appeal_by_contact.get(c.id)
        if a is not None:
            out.current_appeal = AppealOut(
                id=a.id,
                dialog_id=a.dialog_id,
                contact_id=a.contact_id,
                number=a.number,
                status=a.status,  # type: ignore[arg-type]
                status_id=a.status_id,
                status_def=(
                    AppealStatusDefOut.model_validate(a.status_def) if a.status_def else None
                ),
                opened_at=a.opened_at,
                closed_at=a.closed_at,
            )
        items.append(out)
    return ContactsPageOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=ContactsSummaryOut)
async def contacts_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactsSummaryOut:
    all_n = int(
        (
            await db.execute(
                select(func.count()).select_from(Contact).where(Contact.assignee_id.is_(None))
            )
        ).scalar_one()
    )
    mine_n = int(
        (
            await db.execute(
                select(func.count()).select_from(Contact).where(Contact.assignee_id == user.id)
            )
        ).scalar_one()
    )
    callback_ids = (
        select(Appeal.contact_id)
        .join(AppealStatusDef, Appeal.status_id == AppealStatusDef.id)
        .where(
            Appeal.contact_id.is_not(None),
            Appeal.status == AppealStatus.OPEN.value,
            AppealStatusDef.needs_callback.is_(True),
        )
    )
    callback_n = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Contact)
                .where(
                    Contact.assignee_id == user.id,
                    Contact.id.in_(callback_ids),
                    Contact.status != ContactStatus.DONE.value,
                )
            )
        ).scalar_one()
    )
    return ContactsSummaryOut(all=all_n, mine=mine_n, callback=callback_n)


@router.post("/next", response_model=ContactOut)
async def claim_next_contact(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    """Claim the oldest free contact from the pool."""
    _require_write(user)
    result = await db.execute(
        select(Contact)
        .where(Contact.assignee_id.is_(None))
        .order_by(Contact.created_at.asc(), Contact.id.asc())
        .limit(1)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Свободных контактов нет")

    claimed = await db.execute(
        update(Contact)
        .where(Contact.id == contact.id, Contact.assignee_id.is_(None))
        .values(assignee_id=user.id)
    )
    if claimed.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Контакт уже забрали — попробуйте ещё раз",
        )
    contact = await _get_contact(db, contact.id)
    await promote_contact_on_claim(db, contact)
    await db.commit()
    contact = await _get_contact(db, contact.id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.post("/claim-batch", response_model=ContactClaimBatchResult)
async def claim_contacts_batch(
    body: ContactClaimBatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactClaimBatchResult:
    """Claim several free contacts at once (manager bulk take)."""
    _require_write(user)
    # Preserve request order, drop duplicates.
    seen: set[int] = set()
    ids: list[int] = []
    for cid in body.contact_ids:
        if cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)

    result = await db.execute(select(Contact).where(Contact.id.in_(ids)))
    by_id = {c.id: c for c in result.scalars().all()}

    claimed_ids: list[int] = []
    skipped: list[ContactClaimSkipped] = []

    for cid in ids:
        contact = by_id.get(cid)
        if contact is None:
            skipped.append(ContactClaimSkipped(id=cid, reason="не найден"))
            continue
        if contact.assignee_id == user.id:
            claimed_ids.append(cid)
            continue
        if contact.assignee_id is not None:
            skipped.append(ContactClaimSkipped(id=cid, reason="уже у другого менеджера"))
            continue
        upd = await db.execute(
            update(Contact)
            .where(Contact.id == cid, Contact.assignee_id.is_(None))
            .values(assignee_id=user.id)
        )
        if upd.rowcount == 0:
            skipped.append(ContactClaimSkipped(id=cid, reason="уже забрали"))
        else:
            claimed_ids.append(cid)

    await db.commit()

    claimed_out: list[ContactOut] = []
    for cid in claimed_ids:
        contact = await _get_contact(db, cid)
        await promote_contact_on_claim(db, contact)
        await db.commit()
        contact = await _get_contact(db, cid)
        claimed_out.append(await _contact_out(db, contact))

    return ContactClaimBatchResult(claimed=claimed_out, skipped=skipped)


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ContactCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    _require_write(user)
    phone = _normalize_phone(body.phone)
    if len(phone) < 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите телефон")
    contact = Contact(
        name=(body.name or "").strip() or phone,
        phone=phone,
        status=ContactStatus.NEW.value,
        created_by_id=user.id,
    )
    db.add(contact)
    await db.commit()
    contact = await _get_contact(db, contact.id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.post("/import", response_model=ContactImportResult)
async def import_contacts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactImportResult:
    """CSV: required phone; ФИО/name; any extra columns matching client field key/label."""
    _require_write(user)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой CSV")

    headers = [(h or "").strip() for h in (reader.fieldnames or [])]
    lower_map = {h.lower(): h for h in headers if h}

    def _col(*names: str) -> str | None:
        for n in names:
            if n in lower_map:
                return lower_map[n]
        return None

    phone_col = _col("phone", "телефон", "tel", "mobile", "номер", "номер телефона")
    name_col = _col("name", "fio", "фио", "full_name", "ф.и.о.", "ф.и.о", "имя")
    if phone_col is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В CSV нужна колонка phone / телефон / номер",
        )

    defs = await list_field_definitions(db, scope=FieldScope.CLIENT.value)
    # Map CSV header → field key (custom + external_id).
    header_to_key: dict[str, str] = {}
    reserved_headers = {phone_col}
    if name_col:
        reserved_headers.add(name_col)
    for fd in defs:
        if fd.key in {"full_name", "phone"}:
            continue
        candidates = {fd.key.lower(), (fd.label or "").strip().lower()}
        for cand in candidates:
            if not cand:
                continue
            hdr = lower_map.get(cand)
            if hdr and hdr not in reserved_headers:
                header_to_key[hdr] = fd.key

    created = 0
    skipped = 0
    errors: list[str] = []
    existing_phones = {p for (p,) in (await db.execute(select(Contact.phone))).all()}

    pending: list[tuple[Contact, dict[str, str]]] = []

    for i, row in enumerate(reader, start=2):
        phone = _normalize_phone(str(row.get(phone_col) or ""))
        if len(phone) < 5:
            skipped += 1
            errors.append(f"строка {i}: нет телефона")
            continue
        if phone in existing_phones:
            skipped += 1
            continue
        name_raw = str(row.get(name_col) or "").strip() if name_col else ""
        contact = Contact(
            name=name_raw or phone,
            phone=phone,
            status=ContactStatus.NEW.value,
            created_by_id=user.id,
        )
        db.add(contact)
        existing_phones.add(phone)
        extra: dict[str, str] = {}
        for hdr, key in header_to_key.items():
            val = str(row.get(hdr) or "").strip()
            if val:
                extra[key] = val
        pending.append((contact, extra))
        created += 1

    await db.flush()
    for contact, extra in pending:
        for key, val in extra.items():
            await upsert_field_value(
                db,
                scope=FieldScope.CONTACT.value,
                owner_id=contact.id,
                field_key=key,
                value=val,
            )

    await db.commit()
    return ContactImportResult(created=created, skipped=skipped, errors=errors[:20])


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    contact = await _get_contact(db, contact_id)
    if contact.assignee_id == user.id:
        await ensure_contact_appeal(db, contact)
        await db.commit()
        contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: int,
    body: ContactUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    _require_write(user)
    contact = await _get_contact(db, contact_id)
    if body.name is not None:
        contact.name = body.name.strip() or contact.name
    if body.phone is not None:
        phone = _normalize_phone(body.phone)
        if len(phone) < 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите телефон")
        contact.phone = phone
    if body.status is not None:
        allowed = {s.value for s in ContactStatus}
        if body.status not in allowed:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный статус")
        contact.status = body.status
    await db.commit()
    contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.patch("/{contact_id}/fields", response_model=ContactOut)
async def update_contact_fields(
    contact_id: int,
    body: ContactFieldsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    """Save the same client-card fields as in chats (shared FieldDefinition catalog)."""
    _require_write(user)
    contact = await _get_contact(db, contact_id)
    await _apply_client_fields(
        db,
        contact,
        full_name=body.full_name,
        phone=body.phone,
        external_id=body.external_id,
        values=body.values,
        appeal_values=body.appeal_values,
        department_id=body.department_id,
    )
    await db.commit()
    contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.post("/{contact_id}/claim", response_model=ContactOut)
async def claim_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    _require_write(user)
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")

    if contact.assignee_id is not None and contact.assignee_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Контакт уже в работе у другого менеджера",
        )

    if contact.assignee_id is None:
        result = await db.execute(
            update(Contact)
            .where(Contact.id == contact_id, Contact.assignee_id.is_(None))
            .values(assignee_id=user.id)
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Контакт уже забрали — обновите список",
            )

    contact = await _get_contact(db, contact_id)
    await promote_contact_on_claim(db, contact)
    await db.commit()
    contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.post("/{contact_id}/appeal", response_model=ContactOut)
async def open_contact_appeal(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    """Ensure an open appeal exists for this contact (phone outreach without dialog)."""
    _require_write(user)
    contact = await _get_contact(db, contact_id)
    if contact.assignee_id is not None and contact.assignee_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Контакт в работе у другого менеджера",
        )
    if contact.assignee_id is None:
        contact.assignee_id = user.id
    await promote_contact_on_claim(db, contact)
    await db.commit()
    contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.patch("/{contact_id}/appeal/status", response_model=ContactOut)
async def set_contact_appeal_status(
    contact_id: int,
    body: ContactAppealStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    """Set workflow status on the contact's current open appeal."""
    _require_write(user)
    contact = await _get_contact(db, contact_id)
    if contact.assignee_id is not None and contact.assignee_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Статус может менять только ответственный менеджер",
        )
    if contact.assignee_id is None:
        contact.assignee_id = user.id

    status_def = await db.get(AppealStatusDef, body.status_id)
    if status_def is None or not status_def.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Статус не найден")

    appeal = await ensure_contact_appeal(db, contact)
    apply_status_def_to_appeal(appeal, status_def, closed_by_id=user.id)
    sync_contact_status_from_stage(contact, status_def)

    await db.commit()
    contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.post("/{contact_id}/comments", response_model=ContactCommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(
    contact_id: int,
    body: ContactCommentCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactCommentOut:
    _require_write(user)
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Введите комментарий")
    row = ContactComment(contact_id=contact_id, author_id=user.id, text=text)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ContactCommentOut(
        id=row.id,
        text=row.text,
        author_id=row.author_id,
        author_name=user.name,
        created_at=row.created_at,
    )


@router.post("/{contact_id}/outcome", response_model=ContactOut)
async def set_call_outcome(
    contact_id: int,
    body: ContactOutcomeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> ContactOut:
    """Record SIP/phone call outcome and update contact status."""
    _require_write(user)
    contact = await _get_contact(db, contact_id)
    if contact.assignee_id is not None and contact.assignee_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Исход может ставить только ответственный менеджер",
        )
    if contact.assignee_id is None:
        contact.assignee_id = user.id

    note = (body.note or "").strip()
    row = ContactCallResult(
        contact_id=contact.id,
        author_id=user.id,
        outcome=body.outcome,
        note=note,
    )
    db.add(row)
    contact.last_outcome = body.outcome
    contact.last_outcome_at = utcnow()
    # Prefer workflow stages in UI; keep legacy outcome → contact.status mapping for API callers.
    if body.outcome in {
        ContactCallOutcome.AGREED.value,
        ContactCallOutcome.REJECTED.value,
    }:
        contact.status = ContactStatus.DONE.value
    else:
        await promote_contact_on_claim(db, contact)

    await db.commit()
    contact = await _get_contact(db, contact_id)
    return await _contact_out(db, contact, with_comments=True, with_fields=True)


@router.post("/{contact_id}/message", response_model=StartChatOut)
async def send_contact_message(
    contact_id: int,
    body: ContactMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CONTACTS)),
) -> StartChatOut:
    """Start/open messenger dialog using contact phone and send text."""
    _require_write(user)
    if not user_can(user, SECTION_CHATS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к чатам для отправки сообщения",
        )
    user = await load_user_rbac(db, user)
    contact = await _get_contact(db, contact_id)

    if contact.assignee_id is None:
        await db.execute(
            update(Contact)
            .where(Contact.id == contact_id, Contact.assignee_id.is_(None))
            .values(assignee_id=user.id)
        )
        await db.flush()
        contact = await _get_contact(db, contact_id)
        await promote_contact_on_claim(db, contact)

    appeal = await ensure_contact_appeal(db, contact)
    return await execute_start_chat(
        db,
        user=user,
        channel_id=body.channel_id,
        recipient=contact.phone,
        text=body.text,
        reuse_appeal=appeal,
    )
