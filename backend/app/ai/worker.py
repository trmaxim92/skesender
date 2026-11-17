"""Background AI worker — processes inbound messages on the leader process."""

from __future__ import annotations

import asyncio
import logging
from app.db import SessionLocal

logger = logging.getLogger(__name__)

# Wait for a short burst of client messages (привет + вопрос) then answer the latest.
_DEBOUNCE_SEC = 1.4


class AiWorker:
    def __init__(self) -> None:
        self._latest: dict[int, int] = {}  # dialog_id -> latest message_id
        self._debounce_tasks: dict[int, asyncio.Task] = {}
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._seen: set[int] = set()
        self._inflight: set[int] = set()  # dialog ids currently processing

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="ai-worker")
        logger.info("AI worker started")

    async def stop(self) -> None:
        for task in list(self._debounce_tasks.values()):
            task.cancel()
        self._debounce_tasks.clear()
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
            self._seen = set(list(self._seen)[-2500:])
        self._latest[dialog_id] = message_id
        # Restart debounce timer for this dialog.
        prev = self._debounce_tasks.get(dialog_id)
        if prev and not prev.done():
            prev.cancel()
        self._debounce_tasks[dialog_id] = asyncio.create_task(
            self._debounce_fire(dialog_id),
            name=f"ai-debounce-{dialog_id}",
        )
        self._wakeup.set()

    async def _debounce_fire(self, dialog_id: int) -> None:
        try:
            await asyncio.sleep(_DEBOUNCE_SEC)
        except asyncio.CancelledError:
            return
        self._wakeup.set()

    async def _run(self) -> None:
        while True:
            try:
                ready = [
                    did
                    for did, task in list(self._debounce_tasks.items())
                    if task.done() and did not in self._inflight and did in self._latest
                ]
                if not ready:
                    self._wakeup.clear()
                    await self._wakeup.wait()
                    continue
                for dialog_id in ready:
                    message_id = self._latest.pop(dialog_id, None)
                    self._debounce_tasks.pop(dialog_id, None)
                    if message_id is None:
                        continue
                    self._inflight.add(dialog_id)
                    try:
                        await self._handle(dialog_id, message_id)
                    finally:
                        self._inflight.discard(dialog_id)
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
