"""In-memory WebSocket hub for website chat widget visitors."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class WidgetVisitorHub:
    def __init__(self) -> None:
        self._by_dialog: dict[int, set[WebSocket]] = {}

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
