from __future__ import annotations

import io
import logging

from telethon.errors import FloodWaitError, PeerFloodError

from app.integrations.telegram_user.runtime import runtime
from app.mailing.types import MailingSendResult
from app.models import AttachmentKind, Channel, MailingTemplate
from app.outbound_start import ResolvedPeer

logger = logging.getLogger(__name__)


def _map_telethon_error(exc: BaseException) -> str:
    name = type(exc).__name__
    if isinstance(exc, FloodWaitError) or name == "FloodWaitError":
        return f"FloodWait:{int(getattr(exc, 'seconds', 30) or 30)}"
    if name == "SlowModeWaitError":
        return f"SlowModeWait:{int(getattr(exc, 'seconds', 30) or 30)}"
    if isinstance(exc, PeerFloodError) or name == "PeerFloodError":
        return f"PeerFlood:{exc}"
    if name in {
        "UserBannedInChannelError",
        "ChatWriteForbiddenError",
        "UserIsBlockedError",
    }:
        return f"UserBanned:{exc}"
    if name in {
        "AuthKeyUnregisteredError",
        "UserDeactivatedBanError",
        "UserDeactivatedError",
        "SessionRevokedError",
    }:
        return f"AuthDead:{exc}"
    return str(exc)


class TelegramUserMailingSender:
    transport = "tgapi"

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
            return MailingSendResult(ok=False, error=_map_telethon_error(exc))

        target = (peer.external_chat_id or "").strip()
        if not target:
            return MailingSendResult(ok=False, error="Пустой id получателя")

        entity: object
        try:
            if target.lstrip("-").isdigit():
                entity = int(target)
            else:
                entity = await client.get_entity(target)
        except FloodWaitError as exc:
            return MailingSendResult(ok=False, error=_map_telethon_error(exc))
        except Exception as exc:
            return MailingSendResult(
                ok=False, error=f"Не удалось найти получателя: {_map_telethon_error(exc)}"
            )

        body = (template.body or "").strip()
        try:
            if media_bytes and template.media_kind:
                file_obj = io.BytesIO(media_bytes)
                file_obj.name = template.media_name or (
                    "video.mp4" if template.media_kind == AttachmentKind.VIDEO.value else "image.jpg"
                )
                message = await client.send_file(
                    entity,
                    file_obj,
                    caption=body or None,
                    force_document=False,
                )
            elif body:
                message = await client.send_message(entity, body)
            else:
                return MailingSendResult(ok=False, error="Пустой шаблон")
            mid = getattr(message, "id", None)
            return MailingSendResult(ok=True, external_id=str(mid) if mid is not None else None)
        except FloodWaitError as exc:
            return MailingSendResult(ok=False, error=_map_telethon_error(exc))
        except PeerFloodError as exc:
            return MailingSendResult(ok=False, error=_map_telethon_error(exc))
        except Exception as exc:
            return MailingSendResult(ok=False, error=_map_telethon_error(exc))
