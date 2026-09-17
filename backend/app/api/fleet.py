from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.integrations.yandex_fleet.state import (
    credentials_public,
    get_or_create_state,
    load_runtime_settings,
    record_sync_result,
    update_runtime_settings,
)
from app.integrations.yandex_fleet.sync import sync_fleet_drivers_to_contacts
from app.models import User, utcnow
from app.rbac import (
    ACTION_WRITE,
    SECTION_CONTACTS,
    SECTION_SETTINGS,
    load_user_rbac,
    user_can,
)
from app.schemas import FleetSettingsUpdateRequest, FleetStatusOut, FleetSyncResultOut

router = APIRouter(prefix="/fleet", tags=["fleet"])


async def _fleet_user(db: AsyncSession, user: User) -> User:
    return await load_user_rbac(db, user)


def _require_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


async def _status_out(db: AsyncSession) -> FleetStatusOut:
    row = await get_or_create_state(db)
    await db.commit()
    creds = credentials_public(row)
    return FleetStatusOut(
        configured=bool(creds["configured"]),
        client_id=str(creds["client_id"]),
        park_id=str(creds["park_id"]),
        api_key_masked=str(creds["api_key_masked"]),
        has_api_key=bool(creds["has_api_key"]),
        credentials_source=str(creds["credentials_source"]),
        sync_enabled=bool(row.sync_enabled),
        interval_sec=int(row.interval_sec or 3600),
        work_statuses=row.work_statuses or "working,not_working",
        last_started_at=row.last_started_at,
        last_finished_at=row.last_finished_at,
        last_ok=row.last_ok,
        last_fetched=int(row.last_fetched or 0),
        last_created=int(row.last_created or 0),
        last_updated=int(row.last_updated or 0),
        last_skipped=int(row.last_skipped or 0),
        last_purged=int(row.last_purged or 0),
        last_error=row.last_error or "",
    )


@router.get("/status", response_model=FleetStatusOut)
async def fleet_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FleetStatusOut:
    loaded = await _fleet_user(db, user)
    if not (user_can(loaded, SECTION_SETTINGS) or user_can(loaded, SECTION_CONTACTS)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    return await _status_out(db)


@router.patch("/settings", response_model=FleetStatusOut)
async def fleet_update_settings(
    body: FleetSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FleetStatusOut:
    loaded = await _fleet_user(db, user)
    _require_write(loaded)
    if not user_can(loaded, SECTION_SETTINGS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    await update_runtime_settings(
        db,
        sync_enabled=body.sync_enabled,
        interval_sec=body.interval_sec,
        work_statuses=body.work_statuses,
        client_id=body.client_id,
        park_id=body.park_id,
        api_key=body.api_key,
    )
    return await _status_out(db)


@router.post("/sync", response_model=FleetSyncResultOut)
async def fleet_sync(
    purge: bool = Query(False, description="Удалить все контакты перед загрузкой из Fleet"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FleetSyncResultOut:
    loaded = await _fleet_user(db, user)
    _require_write(loaded)
    if not (user_can(loaded, SECTION_CONTACTS) or user_can(loaded, SECTION_SETTINGS)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    runtime = await load_runtime_settings(db)
    if not runtime.credentials:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fleet API не настроен — укажите Client-ID, API-Key и Park ID в настройках",
        )
    started = utcnow()
    result = await sync_fleet_drivers_to_contacts(
        db, changed_by_id=loaded.id, purge_before=purge
    )
    await record_sync_result(db, result, started_at=started)
    if result.errors and result.fetched == 0 and result.created == 0 and result.updated == 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.errors[0],
        )
    return FleetSyncResultOut(
        fetched=result.fetched,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        purged=result.purged,
        errors=result.errors[:20],
    )
