from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal
from app.integrations.yandex_fleet.client import fleet_configured
from app.integrations.yandex_fleet.state import load_runtime_settings, record_sync_result
from app.integrations.yandex_fleet.sync import sync_fleet_drivers_to_contacts
from app.models import utcnow

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SEC = 3600.0


class FleetSyncWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not fleet_configured():
            logger.info("Fleet sync worker not started (credentials missing)")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="fleet-sync-worker")
        logger.info("Fleet sync worker started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Fleet sync worker stopped")

    async def _interval(self) -> float:
        try:
            async with SessionLocal() as session:
                runtime = await load_runtime_settings(session)
                await session.commit()
                if not runtime.sync_enabled:
                    return max(_DEFAULT_INTERVAL_SEC, 60.0)
                return float(max(runtime.interval_sec, 60))
        except Exception:
            logger.exception("Failed to load Fleet sync interval")
            return _DEFAULT_INTERVAL_SEC

    async def _run(self) -> None:
        await self._sleep_interruptible(15.0)
        while not self._stop.is_set():
            try:
                async with SessionLocal() as session:
                    runtime = await load_runtime_settings(session)
                    if not runtime.sync_enabled:
                        await session.commit()
                    else:
                        started = utcnow()
                        result = await sync_fleet_drivers_to_contacts(session)
                        await record_sync_result(session, result, started_at=started)
                        if result.errors:
                            logger.warning("Fleet periodic sync errors: %s", result.errors[:3])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Fleet sync worker tick failed")
            await self._sleep_interruptible(await self._interval())

    async def _sleep_interruptible(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return


worker = FleetSyncWorker()
