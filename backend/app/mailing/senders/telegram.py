from __future__ import annotations

from app.integrations.telegram_bot import client as tg_client
from app.mailing.types import MailingSendResult
from app.models import AttachmentKind, Channel, MailingTemplate
from app.outbound_start import ResolvedPeer
from app.security import decrypt_secret


class TelegramBotMailingSender:
    transport = "telegram"

    async def send(
        self,
        channel: Channel,
        *,
        peer: ResolvedPeer,
        template: MailingTemplate,
        media_bytes: bytes | None,
    ) -> MailingSendResult:
        if not channel.credentials_enc:
            return MailingSendResult(ok=False, error="Нет credentials у канала")

        chat_id = (peer.external_chat_id or "").strip()
        if not chat_id:
            return MailingSendResult(ok=False, error="Пустой chat_id получателя")
        if chat_id.startswith("@"):
            return MailingSendResult(
                ok=False,
                error="Telegram-бот требует числовой chat_id (не @username)",
            )

        token = decrypt_secret(channel.credentials_enc)
        body = (template.body or "").strip()
        try:
            if media_bytes and template.media_kind == AttachmentKind.IMAGE.value:
                payload = await tg_client.send_photo(
                    token,
                    chat_id=chat_id,
                    data=media_bytes,
                    filename=template.media_name or "image.jpg",
                    caption=body or None,
                )
            elif media_bytes and template.media_kind == AttachmentKind.VIDEO.value:
                payload = await tg_client.send_video(
                    token,
                    chat_id=chat_id,
                    data=media_bytes,
                    filename=template.media_name or "video.mp4",
                    caption=body or None,
                    mime_type=template.mime_type,
                )
            elif media_bytes:
                payload = await tg_client.send_document(
                    token,
                    chat_id=chat_id,
                    data=media_bytes,
                    filename=template.media_name or "file",
                    caption=body or None,
                    mime_type=template.mime_type,
                )
            elif body:
                payload = await tg_client.send_message(token, chat_id=chat_id, text=body)
            else:
                return MailingSendResult(ok=False, error="Пустой шаблон")
            mid = payload.get("message_id")
            return MailingSendResult(ok=True, external_id=str(mid) if mid is not None else None)
        except Exception as exc:
            return MailingSendResult(ok=False, error=str(exc))
