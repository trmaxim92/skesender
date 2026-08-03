"""WebSocket hub for website chat widget visitors (Redis-aware)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.redisutil import get_redis, redis_enabled

logger = logging.getLogger(__name__)

WIDGET_CHANNEL = "skysender:widget"


class WidgetVisitorHub:
    def __init__(self) -> None:
        self._by_dialog: dict[int, set[WebSocket]] = {}
        self._sub_task: asyncio.Task | None = None
        self._pubsub: Any = None

    async def start_pubsub(self) -> None:
        if not redis_enabled():
            return
        if self._sub_task and not self._sub_task.done():
            return
        self._sub_task = asyncio.create_task(self._subscribe_loop(), name="widget-hub-pubsub")

    async def stop_pubsub(self) -> None:
        if self._sub_task:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except asyncio.CancelledError:
                pass
            self._sub_task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except Exception:
                pass
            self._pubsub = None

    async def _subscribe_loop(self) -> None:
        while True:
            try:
                r = await get_redis()
                if r is None:
                    await asyncio.sleep(2)
                    continue
                pubsub = r.pubsub()
                self._pubsub = pubsub
                await pubsub.subscribe(WIDGET_CHANNEL)
                logger.info("Widget hub subscribed to %s", WIDGET_CHANNEL)
                async for message in pubsub.listen():
                    if message is None or message.get("type") != "message":
                        continue
                    data = message.get("data")
                    if not isinstance(data, str):
                        continue
                    try:
                        envelope = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(envelope, dict):
                        continue
                    dialog_id = envelope.get("dialog_id")
                    event = envelope.get("event")
                    if not isinstance(dialog_id, int) or not isinstance(event, dict):
                        continue
                    await self._local_publish(dialog_id, event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Widget hub pubsub loop error — reconnecting")
                await asyncio.sleep(2)

    async def connect(self, dialog_id: int, websocket: WebSocket) -> None:
        self._by_dialog.setdefault(dialog_id, set()).add(websocket)

    def disconnect(self, dialog_id: int, websocket: WebSocket) -> None:
        sockets = self._by_dialog.get(dialog_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._by_dialog.pop(dialog_id, None)

    async def publish(self, dialog_id: int, event: dict[str, Any]) -> None:
        if redis_enabled():
            try:
                r = await get_redis()
                if r is not None:
                    await r.publish(
                        WIDGET_CHANNEL,
                        json.dumps(
                            {"dialog_id": dialog_id, "event": event},
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                    return
            except Exception:
                logger.exception("Widget Redis publish failed — local fallback")
        await self._local_publish(dialog_id, event)

    async def _local_publish(self, dialog_id: int, event: dict[str, Any]) -> None:
        sockets = list(self._by_dialog.get(dialog_id) or ())
        if not sockets:
            return
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                if ws.client_state != WebSocketState.CONNECTED:
                    dead.append(ws)
                    continue
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(ws)
            except Exception:
                logger.exception("Widget WS publish failed dialog=%s", dialog_id)
                dead.append(ws)
        for ws in dead:
            self.disconnect(dialog_id, ws)


visitor_hub = WidgetVisitorHub()
