from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.redisutil import get_redis, redis_enabled

logger = logging.getLogger(__name__)

CHATS_CHANNEL = "skysender:chats"
CONTROL_DISCONNECT = "control.disconnect_user"


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
        self._sub_task: asyncio.Task | None = None
        self._pubsub: Any = None

    async def start_pubsub(self) -> None:
        """Subscribe to Redis so events from other workers reach local WS clients."""
        if not redis_enabled():
            return
        if self._sub_task and not self._sub_task.done():
            return
        self._sub_task = asyncio.create_task(self._subscribe_loop(), name="chats-hub-pubsub")

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
                await pubsub.subscribe(CHATS_CHANNEL)
                logger.info("Chat hub subscribed to %s", CHATS_CHANNEL)
                async for message in pubsub.listen():
                    if message is None or message.get("type") != "message":
                        continue
                    data = message.get("data")
                    if not isinstance(data, str):
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") == CONTROL_DISCONNECT:
                        uid = event.get("user_id")
                        if isinstance(uid, int):
                            await self._local_disconnect_user(uid)
                        continue
                    await self._local_broadcast(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chat hub pubsub loop error — reconnecting")
                await asyncio.sleep(2)

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

    async def update_acl(
        self,
        websocket: WebSocket,
        *,
        channel_ids: list[int] | None,
        department_ids: list[int] | None,
    ) -> None:
        async with self._lock:
            info = self._clients.get(websocket)
            if info is None:
                return
            info.channel_ids = channel_ids
            info.department_ids = department_ids

    async def disconnect_user(self, user_id: int) -> None:
        """Force-close sockets for a user on every worker (via Redis when enabled)."""
        if redis_enabled():
            try:
                r = await get_redis()
                if r is not None:
                    await r.publish(
                        CHATS_CHANNEL,
                        json.dumps({"type": CONTROL_DISCONNECT, "user_id": user_id}),
                    )
                    return
            except Exception:
                logger.exception("Failed to publish disconnect_user — falling back to local")
        await self._local_disconnect_user(user_id)

    async def _local_disconnect_user(self, user_id: int) -> None:
        async with self._lock:
            targets = [info.ws for info in self._clients.values() if info.user_id == user_id]
        for ws in targets:
            try:
                await ws.close(code=1008)
            except Exception:
                pass
            await self.disconnect(ws)

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
        """Fan-out to all workers via Redis, or local-only without REDIS_URL."""
        if redis_enabled():
            try:
                r = await get_redis()
                if r is not None:
                    await r.publish(
                        CHATS_CHANNEL,
                        json.dumps(event, ensure_ascii=False, default=str),
                    )
                    return
            except Exception:
                logger.exception("Redis publish failed — local broadcast fallback")
        await self._local_broadcast(event)

    async def _local_broadcast(self, event: dict[str, Any]) -> None:
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
