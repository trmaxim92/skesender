from __future__ import annotations

import logging

from pymax import File, Photo, Video

from app.integrations.max_personal.runtime import runtime
from app.mailing.types import MailingSendResult
from app.models import AttachmentKind, Channel, MailingTemplate
from app.outbound_start import ResolvedPeer

logger = logging.getLogger(__name__)


class MaxPersonalMailingSender:
    transport = "max"

    async def send(
        self,
        channel: Channel,
        *,
        peer: ResolvedPeer,
        template: MailingTemplate,
        media_bytes: bytes | None,
    ) -> MailingSendResult:
        try:
            client = await runtime.ensure_client(channel.id)
        except Exception as exc:
            return MailingSendResult(ok=False, error=str(exc))

        chat_raw = (peer.external_chat_id or "").strip()
        if not chat_raw.lstrip("-").isdigit():
            return MailingSendResult(
                ok=False,
                error="MAX · аккаунт: не удалось получить chat_id получателя",
            )

        chat_id = int(chat_raw)
        body = (template.body or "").strip()
        try:
            attachments = []
            if media_bytes and template.media_kind:
                name = template.media_name or "file"
                if template.media_kind == AttachmentKind.IMAGE.value:
                    attachments = [Photo(raw=media_bytes, name=name)]
                elif template.media_kind == AttachmentKind.VIDEO.value:
                    attachments = [Video(raw=media_bytes, name=name)]
                else:
                    attachments = [File(raw=media_bytes, name=name)]
            if not body and not attachments:
                return MailingSendResult(ok=False, error="Пустой шаблон")
            message = await client.send_message(
                chat_id=chat_id,
                text=body or "",
                attachments=attachments or None,
            )
            mid = getattr(message, "id", None) if message else None
            return MailingSendResult(ok=True, external_id=str(mid) if mid is not None else None)
        except Exception as exc:
            return MailingSendResult(ok=False, error=str(exc))
