"""Background AI worker — processes inbound messages on the leader process."""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from app.db import SessionLocal

logger = logging.getLogger(__name__)


class AiWorker:
    def __init__(self) -> None:
        self._queue: deque[tuple[int, int]] = deque()
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._seen: set[int] = set()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="ai-worker")
        logger.info("AI worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("AI worker stopped")

    def enqueue(self, dialog_id: int, message_id: int) -> None:
        if message_id in self._seen:
            return
        self._seen.add(message_id)
        if len(self._seen) > 5000:
            # drop oldest half
            self._seen = set(list(self._seen)[-2500:])
        self._queue.append((dialog_id, message_id))
        self._wakeup.set()

    async def _run(self) -> None:
        while True:
            try:
                if not self._queue:
                    self._wakeup.clear()
                    await self._wakeup.wait()
                    continue
                dialog_id, message_id = self._queue.popleft()
                await self._handle(dialog_id, message_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AI worker loop error")
                await asyncio.sleep(1.0)

    async def _handle(self, dialog_id: int, message_id: int) -> None:
        from app.ai.pipeline import process_inbound_message
        from app.realtime.publish import emit_event

        async with SessionLocal() as session:
            result = await process_inbound_message(
                session, dialog_id=dialog_id, message_id=message_id
            )
            if result is None:
                return
            suggestion = result.suggestion
            await emit_event(
                {
                    "type": "ai.suggestion",
                    "suggestion": {
                        "id": suggestion.id,
                        "dialog_id": suggestion.dialog_id,
                        "message_id": suggestion.message_id,
                        "status": suggestion.status,
                        "draft_text": suggestion.draft_text,
                        "confidence": suggestion.confidence,
                        "intent": suggestion.intent,
                        "needs_human": suggestion.needs_human,
                        "auto_sent": result.auto_sent,
                    },
                }
            )


worker = AiWorker()
