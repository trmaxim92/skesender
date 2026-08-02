from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError, SendResult
from app.integrations.webchat.connector import connect_webchat
from app.integrations.webchat.visitor_hub import visitor_hub
from app.models import Channel, ChannelTransport, Dialog, utcnow


class WebchatAdapter:
    transport = ChannelTransport.WEBCHAT

    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    async def connect(
        self,
        session: AsyncSession,
        *,
        credentials: dict[str, Any],
        created_by_id: int | None,
        name: str | None = None,
    ) -> tuple[Channel, dict[str, Any] | None]:
        origins = credentials.get("allowed_origins")
        if not isinstance(origins, list):
            origins = []
        channel, info = await connect_webchat(
            session,
            created_by_id=created_by_id,
            name=name,
            allowed_origins=[str(o) for o in origins],
        )
        return channel, info

    async def send_text(
        self,
        channel: Channel,
        dialog: Dialog,
        text: str,
        *,
        reply_to_external_id: str | None = None,
    ) -> SendResult:
        if channel.status != "online":
            raise IntegrationError("Виджет выключен — включите канал, чтобы писать посетителю")
        external_id = f"out-{uuid.uuid4().hex[:16]}"
        await visitor_hub.publish(
            dialog.id,
            {
                "type": "message",
                "message": {
                    "external_id": external_id,
                    "direction": "out",
                    "text": text,
                    "created_at": utcnow().isoformat(),
                    "reply_to_external_id": reply_to_external_id,
                },
            },
        )
        return SendResult(external_id=external_id, raw={"webchat": True})

    async def send_media(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        kind: str,
        data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
        reply_to_external_id: str | None = None,
    ) -> SendResult:
        raise IntegrationError("Вложения в виджет пока не поддерживаются")

    async def edit_text(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
        text: str,
    ) -> None:
        await visitor_hub.publish(
            dialog.id,
            {
                "type": "message_edited",
                "external_id": external_id,
                "text": text,
            },
        )

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        await visitor_hub.publish(
            dialog.id,
            {
                "type": "message_deleted",
                "external_id": external_id,
            },
        )

    async def start_worker(self) -> None:
        return None

    async def stop_worker(self) -> None:
        return None

    async def on_channel_deleted(self, channel_id: int) -> None:
        return None
