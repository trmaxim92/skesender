from __future__ import annotations

from typing import Protocol

from app.mailing.types import MailingSendResult
from app.models import Channel, MailingTemplate


class MailingSender(Protocol):
    transport: str

    async def send(
        self,
        channel: Channel,
        *,
        normalized: str,
        kind: str,
        template: MailingTemplate,
        media_bytes: bytes | None,
    ) -> MailingSendResult: ...
