"""Persist channel connection lifecycle for the Diagnostics UI."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import ChannelEvent, utcnow

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 14
_MAX_ROWS = 3000


def _infer_level(*, kind: str, status: str | None = None, last_error: str | None = None) -> str:
    if kind in {"error", "reconnect_failed", "gave_up"} or (status == "error"):
        return "error"
    # Successful soft-reconnect is informational; attempts/disconnects stay warn.
    if kind in {"disconnect", "reconnect_attempt"} or last_error:
        return "warn"
    return "info"


async def record_channel_event(
    channel_id: int,
    *,
    kind: str,
    message: str,
    detail: str | None = None,
    level: str | None = None,
) -> None:
    """Best-effort append; never raises into callers."""
    try:
        lvl = level or _infer_level(kind=kind)
        async with SessionLocal() as session:
            session.add(
                ChannelEvent(
                    channel_id=channel_id,
                    level=lvl,
                    kind=kind[:32],
                    message=(message or "")[:2000],
                    detail=(detail[:4000] if detail else None),
                    created_at=utcnow(),
                )
            )
            await session.commit()
            # Lightweight prune: drop old rows when table grows.
            count = (
                await session.execute(select(ChannelEvent.id).limit(_MAX_ROWS + 1))
            ).all()
            if len(count) > _MAX_ROWS:
                cutoff = utcnow() - timedelta(days=_RETENTION_DAYS)
                await session.execute(
                    delete(ChannelEvent).where(ChannelEvent.created_at < cutoff)
                )
                await session.commit()
    except Exception:
        logger.exception("Failed to record channel event channel=%s kind=%s", channel_id, kind)


async def record_status_change(
    channel_id: int,
    *,
    old_status: str | None,
    new_status: str | None,
    old_error: str | None,
    new_error: str | None,
    identity: str | None = None,
) -> None:
    if new_status and new_status != old_status:
        kind = {
            "online": "online",
            "offline": "offline",
            "connecting": "connecting",
            "qr_pending": "qr",
            "error": "error",
        }.get(new_status, "status")
        msg = f"Статус: {old_status or '—'} → {new_status}"
        if identity and new_status == "online":
            msg = f"Онлайн как {identity}"
        await record_channel_event(
            channel_id,
            kind=kind,
            message=msg,
            detail=new_error,
            level="error" if new_status == "error" else ("warn" if new_status != "online" else "info"),
        )
    elif new_error != old_error and new_error:
        await record_channel_event(
            channel_id,
            kind="error" if (new_status or old_status) == "error" else "note",
            message=new_error[:500],
            level="warn",
        )
