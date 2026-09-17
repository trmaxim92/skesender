"""Persistent settings + last sync snapshot for Yandex Fleet integration."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.yandex_fleet.client import fleet_configured
from app.integrations.yandex_fleet.sync import FleetSyncResult
from app.models import FleetSyncState, utcnow

_STATE_ID = 1


@dataclass
class FleetRuntimeSettings:
    sync_enabled: bool
    interval_sec: int
    work_statuses: str


async def get_or_create_state(db: AsyncSession) -> FleetSyncState:
    row = await db.get(FleetSyncState, _STATE_ID)
    if row is not None:
        return row
    cfg = get_settings()
    row = FleetSyncState(
        id=_STATE_ID,
        sync_enabled=True,
        interval_sec=max(int(cfg.fleet_sync_interval_sec or 3600), 60),
        work_statuses=(cfg.fleet_work_statuses or "working,not_working").strip()
        or "working,not_working",
    )
    db.add(row)
    await db.flush()
    return row


async def load_runtime_settings(db: AsyncSession) -> FleetRuntimeSettings:
    row = await get_or_create_state(db)
    return FleetRuntimeSettings(
        sync_enabled=bool(row.sync_enabled),
        interval_sec=max(int(row.interval_sec or 3600), 60),
        work_statuses=(row.work_statuses or "working,not_working").strip()
        or "working,not_working",
    )


async def update_runtime_settings(
    db: AsyncSession,
    *,
    sync_enabled: bool | None = None,
    interval_sec: int | None = None,
    work_statuses: str | None = None,
) -> FleetSyncState:
    row = await get_or_create_state(db)
    if sync_enabled is not None:
        row.sync_enabled = sync_enabled
    if interval_sec is not None:
        row.interval_sec = max(int(interval_sec), 60)
    if work_statuses is not None:
        cleaned = ",".join(s.strip() for s in work_statuses.split(",") if s.strip())
        row.work_statuses = cleaned or "working,not_working"
    row.updated_at = utcnow()
    await db.commit()
    await db.refresh(row)
    return row


async def record_sync_result(
    db: AsyncSession,
    result: FleetSyncResult,
    *,
    started_at=None,
) -> FleetSyncState:
    row = await get_or_create_state(db)
    finished = utcnow()
    row.last_started_at = started_at or finished
    row.last_finished_at = finished
    row.last_ok = not bool(result.errors) or result.fetched > 0 or result.created > 0
    if result.errors and result.fetched == 0 and result.created == 0:
        row.last_ok = False
    row.last_fetched = result.fetched
    row.last_created = result.created
    row.last_updated = result.updated
    row.last_skipped = result.skipped
    row.last_purged = result.purged
    row.last_error = "; ".join(result.errors[:3]) if result.errors else ""
    row.updated_at = finished
    await db.commit()
    await db.refresh(row)
    return row


def mask_secret(value: str, *, keep: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= keep:
        return "*" * len(raw)
    return "*" * (len(raw) - keep) + raw[-keep:]


def credentials_public() -> dict:
    s = get_settings()
    configured = fleet_configured()
    return {
        "configured": configured,
        "client_id": (s.fleet_client_id or "").strip(),
        "park_id": (s.fleet_park_id or "").strip(),
        "api_key_masked": mask_secret(s.fleet_api_key or ""),
        "credentials_source": "env",
    }
