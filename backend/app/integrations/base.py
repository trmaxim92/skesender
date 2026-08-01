from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelTransport, Dialog


class IntegrationError(Exception):
    """Base error for channel integrations."""


@dataclass
class SendResult:
    """Universal outbound send result — adapters map provider payloads here."""

    external_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(Protocol):
    """Contract every messenger package must implement."""

    transport: ChannelTransport

    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Validate token/session and return provider profile metadata."""

    async def connect(
        self,
        session: AsyncSession,
        *,
        credentials: dict[str, Any],
        created_by_id: int | None,
        name: str | None = None,
    ) -> tuple[Channel, dict[str, Any] | None]:
        """Create or update a Channel row with encrypted credentials."""

    async def send_text(
        self,
        channel: Channel,
        dialog: Dialog,
        text: str,
        *,
        reply_to_external_id: str | None = None,
    ) -> SendResult:
        """Send an outbound text message via the provider."""

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
        """Send an outbound media attachment via the provider."""

    async def edit_text(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
        text: str,
    ) -> None:
        """Edit an outbound text message via the provider."""

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        """Delete a message via the provider."""

    async def start_worker(self) -> None:
        """Start background receive loop (poller/webhook consumer)."""

    async def stop_worker(self) -> None:
        """Stop background worker."""

    async def on_channel_deleted(self, channel_id: int) -> None:
        """Release in-memory sessions/poller state for a deleted channel."""
