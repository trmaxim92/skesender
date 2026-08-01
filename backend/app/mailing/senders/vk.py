from __future__ import annotations

from app.mailing.types import MailingSendResult
from app.models import Channel, MailingTemplate
from app.outbound_start import ResolvedPeer


class VkMailingSender:
    transport = "vk"

    async def send(
        self,
        channel: Channel,
        *,
        peer: ResolvedPeer,
        template: MailingTemplate,
        media_bytes: bytes | None,
    ) -> MailingSendResult:
        return MailingSendResult(ok=False, error="VK рассылка пока не реализована")
