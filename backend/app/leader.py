"""Redis leader election for background workers (pollers / mailing / outbox)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.redisutil import get_redis, redis_enabled

logger = logging.getLogger(__name__)

LOCK_KEY = "skysender:bg_leader"
LOCK_TTL_SEC = 12
RENEW_EVERY_SEC = 4


class BackgroundLeader:
    """Hold a Redis lock; start/stop callbacks when leadership changes.

    Without Redis every process acts as leader (single-worker mode).
    """

    def __init__(
        self,
        *,
        on_start: Callable[[], Awaitable[None]],
        on_stop: Callable[[], Awaitable[None]],
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._instance_id = uuid.uuid4().hex
        self._is_leader = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="bg-leader")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._is_leader:
            await self._relinquish()

    async def _run(self) -> None:
        if not redis_enabled():
            logger.info("No REDIS_URL — this process runs background workers (single-worker mode)")
            await self._become_leader()
            try:
                await self._stop.wait()
            except asyncio.CancelledError:
                raise
            finally:
                await self._relinquish()
            return

        logger.info("Redis leader election enabled instance=%s", self._instance_id[:8])
        while not self._stop.is_set():
            try:
                held = await self._try_hold_lock()
                if held and not self._is_leader:
                    await self._become_leader()
                elif held and self._is_leader:
                    pass
                elif not held and self._is_leader:
                    logger.warning("Lost background leadership instance=%s", self._instance_id[:8])
                    await self._relinquish()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Leader election loop error")
                if self._is_leader:
                    try:
                        await self._relinquish()
                    except Exception:
                        logger.exception("Failed to stop workers after leader error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=RENEW_EVERY_SEC)
            except asyncio.TimeoutError:
                pass

    async def _try_hold_lock(self) -> bool:
        r = await get_redis()
        if r is None:
            return False
        # Acquire or renew if we already own it.
        owned = await r.get(LOCK_KEY)
        if owned == self._instance_id:
            await r.expire(LOCK_KEY, LOCK_TTL_SEC)
            return True
        ok = await r.set(LOCK_KEY, self._instance_id, nx=True, ex=LOCK_TTL_SEC)
        return bool(ok)

    async def _become_leader(self) -> None:
        logger.info("Acquired background leadership instance=%s", self._instance_id[:8])
        self._is_leader = True
        await self._on_start()

    async def _relinquish(self) -> None:
        was = self._is_leader
        self._is_leader = False
        if was:
            await self._on_stop()
        if redis_enabled():
            try:
                r = await get_redis()
                if r is not None:
                    current = await r.get(LOCK_KEY)
                    if current == self._instance_id:
                        await r.delete(LOCK_KEY)
            except Exception:
                logger.exception("Failed to release leader lock")
