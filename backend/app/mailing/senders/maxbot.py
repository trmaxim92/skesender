from __future__ import annotations

from app.integrations.maxbot import client as max_client
from app.mailing.types import MailingSendResult
from app.models import AttachmentKind, Channel, MailingTemplate
from app.outbound_start import ResolvedPeer
from app.security import decrypt_secret


class MaxBotMailingSender:
    transport = "maxbot"

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

        user_raw = (peer.contact_external_id or peer.external_chat_id or "").strip()
        if not user_raw.isdigit():
            return MailingSendResult(
                ok=False,
                error="MAX-бот принимает числовой user_id",
            )

        token = decrypt_secret(channel.credentials_enc)
        user_id = int(user_raw)
        body = (template.body or "").strip()
        try:
            attachments = None
            if media_bytes and template.media_kind:
                upload_type = (
                    "image"
                    if template.media_kind == AttachmentKind.IMAGE.value
                    else "video"
                    if template.media_kind == AttachmentKind.VIDEO.value
                    else "file"
                )
                media_token = await max_client.upload_and_get_token(
                    token,
                    upload_type=upload_type,
                    data=media_bytes,
                    filename=template.media_name or f"{upload_type}",
                )
                attachments = [{"type": upload_type, "payload": {"token": media_token}}]
            if not body and not attachments:
                return MailingSendResult(ok=False, error="Пустой шаблон")
            payload = await max_client.send_message(
                token,
                text=body or None,
                user_id=user_id,
                attachments=attachments,
            )
            message_obj = payload.get("message") if isinstance(payload, dict) else None
            mid = None
            if isinstance(message_obj, dict):
                body_obj = message_obj.get("body") if isinstance(message_obj.get("body"), dict) else {}
                mid = body_obj.get("mid") or message_obj.get("id")
            return MailingSendResult(ok=True, external_id=str(mid) if mid is not None else None)
        except Exception as exc:
            return MailingSendResult(ok=False, error=str(exc))
