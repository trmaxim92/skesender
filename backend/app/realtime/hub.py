from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ClientInfo:
    ws: WebSocket
    user_id: int
    # None = all channels / departments
    channel_ids: list[int] | None
    department_ids: list[int] | None


class ChatHub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, ClientInfo] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        *,
        user_id: int,
        channel_ids: list[int] | None,
        department_ids: list[int] | None,
        accepted: bool = False,
    ) -> None:
        if not accepted:
            await websocket.accept()
        info = ClientInfo(
            ws=websocket,
            user_id=user_id,
            channel_ids=channel_ids,
            department_ids=department_ids,
        )
        async with self._lock:
            self._clients[websocket] = info
        logger.info("WS client connected user=%s (%s total)", user_id, len(self._clients))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(websocket, None)
        logger.info("WS client disconnected (%s total)", len(self._clients))

    def _allowed(self, info: ClientInfo, event: dict[str, Any]) -> bool:
        event_type = event.get("type")
        if event_type == "ping":
            return True

        channel_id: int | None = None
        department_id: int | None = None

        dialog = event.get("dialog")
        if isinstance(dialog, dict):
            channel_id = dialog.get("channel_id")
            department_id = dialog.get("department_id")
        elif event_type == "dialog.typing":
            channel_id = event.get("channel_id")
            department_id = event.get("department_id")
        elif event_type == "channel.status":
            channel = event.get("channel")
            if isinstance(channel, dict):
                channel_id = channel.get("id")
                department_id = channel.get("department_id")

        if info.channel_ids is not None:
            if channel_id is None or int(channel_id) not in info.channel_ids:
                return False
        if info.department_ids is not None:
            if department_id is None or int(department_id) not in info.department_ids:
                return False
        return True

    async def broadcast(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        async with self._lock:
            clients = list(self._clients.values())
        if not clients:
            return
        dead: list[WebSocket] = []
        for info in clients:
            if not self._allowed(info, event):
                continue
            try:
                await info.ws.send_text(payload)
            except Exception:
                dead.append(info.ws)
        for ws in dead:
            await self.disconnect(ws)


hub = ChatHub()
