from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError, SendResult
from app.models import Channel, ChannelTransport, Dialog


class VkAdapter:
    transport = ChannelTransport.VK

    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        raise IntegrationError("VK is not implemented yet")

    async def connect(
        self,
        session: AsyncSession,
        *,
        credentials: dict[str, Any],
        created_by_id: int | None,
        name: str | None = None,
    ) -> tuple[Channel, dict[str, Any] | None]:
        raise IntegrationError("VK is not implemented yet")

    async def send_text(
        self,
        channel: Channel,
        dialog: Dialog,
        text: str,
        *,
        reply_to_external_id: str | None = None,
    ) -> SendResult:
        raise IntegrationError("VK is not implemented yet")

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
        raise IntegrationError("VK is not implemented yet")

    async def edit_text(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
        text: str,
    ) -> None:
        raise IntegrationError("VK is not implemented yet")

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        raise IntegrationError("VK is not implemented yet")

    async def start_worker(self) -> None:
        return None

    async def stop_worker(self) -> None:
        return None

    async def on_channel_deleted(self, channel_id: int) -> None:
        return None
