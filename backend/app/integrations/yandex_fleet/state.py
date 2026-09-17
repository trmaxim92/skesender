"""Persistent settings + credentials + last sync snapshot for Yandex Fleet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.yandex_fleet.credentials import FleetCredentials
from app.models import FleetSyncState, utcnow
from app.security import decrypt_secret, encrypt_secret

if TYPE_CHECKING:
    from app.integrations.yandex_fleet.sync import FleetSyncResult

_STATE_ID = 1


@dataclass
class FleetRuntimeSettings:
    sync_enabled: bool
    interval_sec: int
    work_statuses: str
    credentials: FleetCredentials | None


def mask_secret(value: str, *, keep: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= keep:
        return "*" * len(raw)
    return "*" * (len(raw) - keep) + raw[-keep:]


def _env_credentials() -> FleetCredentials | None:
    s = get_settings()
    client_id = (s.fleet_client_id or "").strip()
    api_key = (s.fleet_api_key or "").strip()
    park_id = (s.fleet_park_id or "").strip()
    if client_id and api_key and park_id:
        return FleetCredentials(
            client_id=client_id, api_key=api_key, park_id=park_id, source="env"
        )
    return None


def credentials_from_row(row: FleetSyncState) -> FleetCredentials | None:
    client_id = (row.client_id or "").strip()
    park_id = (row.park_id or "").strip()
    enc = (row.api_key_enc or "").strip()
    if not (client_id and park_id and enc):
        return None
    try:
        api_key = decrypt_secret(enc).strip()
    except Exception:
        return None
    if not api_key:
        return None
    return FleetCredentials(
        client_id=client_id, api_key=api_key, park_id=park_id, source="db"
    )


def resolve_credentials(row: FleetSyncState) -> FleetCredentials | None:
    """Prefer DB credentials; fall back to env."""
    return credentials_from_row(row) or _env_credentials()


async def get_or_create_state(db: AsyncSession) -> FleetSyncState:
    row = await db.get(FleetSyncState, _STATE_ID)
    if row is not None:
        return row
    cfg = get_settings()
    row = FleetSyncState(
        id=_STATE_ID,
        client_id=(cfg.fleet_client_id or "").strip(),
        park_id=(cfg.fleet_park_id or "").strip(),
        api_key_enc=(
            encrypt_secret((cfg.fleet_api_key or "").strip())
            if (cfg.fleet_api_key or "").strip()
            else None
        ),
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
        credentials=resolve_credentials(row),
    )


async def update_runtime_settings(
    db: AsyncSession,
    *,
    sync_enabled: bool | None = None,
    interval_sec: int | None = None,
    work_statuses: str | None = None,
    client_id: str | None = None,
    park_id: str | None = None,
    api_key: str | None = None,
) -> FleetSyncState:
    row = await get_or_create_state(db)
    if sync_enabled is not None:
        row.sync_enabled = sync_enabled
    if interval_sec is not None:
        row.interval_sec = max(int(interval_sec), 60)
    if work_statuses is not None:
        cleaned = ",".join(s.strip() for s in work_statuses.split(",") if s.strip())
        row.work_statuses = cleaned or "working,not_working"
    if client_id is not None:
        row.client_id = client_id.strip()
    if park_id is not None:
        row.park_id = park_id.strip()
    if api_key is not None:
        key = api_key.strip()
        if key:
            row.api_key_enc = encrypt_secret(key)
    # First save from UI without re-pasting key: copy from env if DB has no key yet.
    if not (row.api_key_enc or "").strip():
        env = _env_credentials()
        if env is not None:
            row.api_key_enc = encrypt_secret(env.api_key)
            if not (row.client_id or "").strip():
                row.client_id = env.client_id
            if not (row.park_id or "").strip():
                row.park_id = env.park_id
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


def credentials_public(row: FleetSyncState) -> dict:
    creds = resolve_credentials(row)
    if creds is None:
        return {
            "configured": False,
            "client_id": (row.client_id or "").strip()
            or (get_settings().fleet_client_id or "").strip(),
            "park_id": (row.park_id or "").strip()
            or (get_settings().fleet_park_id or "").strip(),
            "api_key_masked": "",
            "has_api_key": False,
            "credentials_source": "none",
        }
    return {
        "configured": True,
        "client_id": creds.client_id,
        "park_id": creds.park_id,
        "api_key_masked": mask_secret(creds.api_key),
        "has_api_key": True,
        "credentials_source": creds.source,
    }
