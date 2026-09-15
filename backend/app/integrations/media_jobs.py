"""Background attachment download after ingest commit (C2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_pending: set[asyncio.Task] = set()


def schedule_media_job(coro: Awaitable[None], *, name: str | None = None) -> None:
    """Fire-and-forget media backfill; errors are logged, never raised to poller."""

    async def _runner() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Media backfill job failed name=%s", name)

    task = asyncio.create_task(_runner(), name=name or "media-backfill")
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def wait_media_jobs(timeout: float = 5.0) -> None:
    """Used by tests / graceful shutdown."""
    if not _pending:
        return
    done, pending = await asyncio.wait(set(_pending), timeout=timeout)
    for task in pending:
        task.cancel()
