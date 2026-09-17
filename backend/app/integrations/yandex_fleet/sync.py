from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fields import upsert_field_value
from app.integrations.yandex_fleet.client import FleetApiError, fleet_configured, iter_all_driver_profiles
from app.integrations.yandex_fleet.roles import infer_performer_role
from app.models import (
    Appeal,
    Contact,
    ContactStatus,
    FieldScope,
    FieldValue,
    FieldValueHistory,
    utcnow,
)

logger = logging.getLogger(__name__)

_PHONE_STRIP = re.compile(r"[^\d+]+")
EXTERNAL_ID_PREFIX = "yandex_fleet:"


@dataclass
class FleetSyncResult:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    purged: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_phone(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    cleaned = _PHONE_STRIP.sub("", s)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def _phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _fio(profile: dict) -> str:
    parts = [
        (profile.get("last_name") or "").strip(),
        (profile.get("first_name") or "").strip(),
        (profile.get("middle_name") or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def _external_id(driver_id: str) -> str:
    return f"{EXTERNAL_ID_PREFIX}{driver_id}"


def _first_phone(profile: dict) -> str:
    phones = profile.get("phones") or []
    if not isinstance(phones, list):
        return ""
    for raw in phones:
        phone = _normalize_phone(str(raw or ""))
        if len(phone) >= 5:
            return phone
    return ""


async def purge_all_contacts(db: AsyncSession) -> int:
    """Delete all CRM contacts and contact-only appeals / EAV values.

    Dialogs keep messages; dialog.contact_id / chat appeals only lose the CRM link (SET NULL).
    """
    contact_ids = list((await db.execute(select(Contact.id))).scalars().all())
    if not contact_ids:
        return 0

    # Phone-only appeals (no messenger dialog) — remove entirely.
    contact_only_appeal_ids = list(
        (
            await db.execute(
                select(Appeal.id).where(
                    Appeal.contact_id.in_(contact_ids),
                    Appeal.dialog_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if contact_only_appeal_ids:
        await db.execute(
            delete(FieldValue).where(
                FieldValue.scope == FieldScope.APPEAL.value,
                FieldValue.owner_id.in_(contact_only_appeal_ids),
            )
        )
        await db.execute(
            delete(FieldValueHistory).where(
                FieldValueHistory.scope == FieldScope.APPEAL.value,
                FieldValueHistory.owner_id.in_(contact_only_appeal_ids),
            )
        )
        await db.execute(delete(Appeal).where(Appeal.id.in_(contact_only_appeal_ids)))

    await db.execute(
        delete(FieldValue).where(
            or_(
                FieldValue.scope == FieldScope.CONTACT.value,
                FieldValue.scope == FieldScope.CONTACT_APPEAL.value,
            ),
            FieldValue.owner_id.in_(contact_ids),
        )
    )
    await db.execute(
        delete(FieldValueHistory).where(
            or_(
                FieldValueHistory.scope == FieldScope.CONTACT.value,
                FieldValueHistory.scope == FieldScope.CONTACT_APPEAL.value,
            ),
            FieldValueHistory.owner_id.in_(contact_ids),
        )
    )

    # Cascades: contact_comments, contact_call_results.
    # Dialogs/appeals with dialog_id: contact_id SET NULL via FK.
    await db.execute(delete(Contact))
    await db.flush()
    logger.warning("Purged %s CRM contacts (and related contact-only appeals/fields)", len(contact_ids))
    return len(contact_ids)


async def sync_fleet_drivers_to_contacts(
    db: AsyncSession,
    *,
    changed_by_id: int | None = None,
    purge_before: bool = False,
) -> FleetSyncResult:
    """Pull Fleet driver profiles → upsert Contact by external_id, else phone."""
    result = FleetSyncResult()
    if not fleet_configured():
        result.errors.append("Fleet API не настроен")
        return result

    if purge_before:
        result.purged = await purge_all_contacts(db)

    from app.departments import ensure_system_client_fields
    from app.integrations.yandex_fleet.state import load_runtime_settings

    await ensure_system_client_fields(db)
    runtime = await load_runtime_settings(db)
    statuses = [s.strip() for s in runtime.work_statuses.split(",") if s.strip()]

    try:
        rows = await iter_all_driver_profiles(work_statuses=statuses or None)
    except FleetApiError as exc:
        logger.warning("Fleet sync fetch failed: %s", exc)
        result.errors.append(str(exc))
        if purge_before:
            await db.commit()
        return result

    result.fetched = len(rows)

    ext_rows = (
        await db.execute(
            select(FieldValue.owner_id, FieldValue.value_text).where(
                FieldValue.scope == FieldScope.CONTACT.value,
                FieldValue.field_key == "external_id",
                FieldValue.value_text.startswith(EXTERNAL_ID_PREFIX),
            )
        )
    ).all()
    by_external: dict[str, int] = {str(v): int(oid) for oid, v in ext_rows if v}

    contacts = (await db.execute(select(Contact))).scalars().all()
    by_id: dict[int, Contact] = {c.id: c for c in contacts}
    by_phone_digits: dict[str, Contact] = {}
    for c in contacts:
        d = _phone_digits(c.phone)
        if d and d not in by_phone_digits:
            by_phone_digits[d] = c

    for row in rows:
        profile = row.get("driver_profile") if isinstance(row, dict) else None
        if not isinstance(profile, dict):
            result.skipped += 1
            continue

        driver_id = str(profile.get("id") or "").strip()
        if not driver_id:
            result.skipped += 1
            continue

        phone = _first_phone(profile)
        if not phone:
            result.skipped += 1
            continue

        name = _fio(profile) or phone
        ext = _external_id(driver_id)
        work_status = str(profile.get("work_status") or "").strip()
        employment = str(profile.get("employment_type") or "").strip()
        role = infer_performer_role(row if isinstance(row, dict) else {})

        contact: Contact | None = None
        cid = by_external.get(ext)
        if cid is not None:
            contact = by_id.get(cid)

        if contact is None:
            digits = _phone_digits(phone)
            contact = by_phone_digits.get(digits) if digits else None

        is_new = False
        changed = False
        if contact is None:
            contact = Contact(
                name=name,
                phone=phone,
                status=ContactStatus.NEW.value,
                created_by_id=changed_by_id,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(contact)
            await db.flush()
            by_id[contact.id] = contact
            digits = _phone_digits(phone)
            if digits:
                by_phone_digits[digits] = contact
            by_external[ext] = contact.id
            result.created += 1
            is_new = True
            changed = True
        else:
            if by_external.get(ext) != contact.id:
                changed = True
            if name and contact.name != name:
                contact.name = name
                changed = True
            if phone and contact.phone != phone:
                old_d = _phone_digits(contact.phone)
                new_d = _phone_digits(phone)
                if old_d and by_phone_digits.get(old_d) is contact:
                    del by_phone_digits[old_d]
                contact.phone = phone
                if new_d:
                    by_phone_digits[new_d] = contact
                changed = True
            if changed:
                contact.updated_at = utcnow()

        await upsert_field_value(
            db,
            scope=FieldScope.CONTACT.value,
            owner_id=contact.id,
            field_key="external_id",
            value=ext,
            changed_by_id=changed_by_id,
            source="yandex_fleet",
        )
        by_external[ext] = contact.id

        if role:
            await upsert_field_value(
                db,
                scope=FieldScope.CONTACT.value,
                owner_id=contact.id,
                field_key="fleet_role",
                value=role,
                changed_by_id=changed_by_id,
                source="yandex_fleet",
            )
        if work_status:
            await upsert_field_value(
                db,
                scope=FieldScope.CONTACT.value,
                owner_id=contact.id,
                field_key="fleet_work_status",
                value=work_status,
                changed_by_id=changed_by_id,
                source="yandex_fleet",
            )
        if employment:
            await upsert_field_value(
                db,
                scope=FieldScope.CONTACT.value,
                owner_id=contact.id,
                field_key="fleet_employment_type",
                value=employment,
                changed_by_id=changed_by_id,
                source="yandex_fleet",
            )

        if not is_new and changed:
            result.updated += 1

    await db.commit()
    logger.info(
        "Fleet sync done: purged=%s fetched=%s created=%s updated=%s skipped=%s",
        result.purged,
        result.fetched,
        result.created,
        result.updated,
        result.skipped,
    )
    return result
