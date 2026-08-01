from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import SendResult
from app.integrations.maxbot import client as max_client
from app.integrations.maxbot.client import MaxApiError
from app.integrations.maxbot.connector import connect_by_token
from app.integrations.maxbot.poller import poller
from app.integrations.maxbot.result import max_payload_to_send_result
from app.models import Channel, ChannelTransport, Dialog
from app.security import decrypt_secret


class MaxBotAdapter:
    transport = ChannelTransport.MAXBOT

    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        token = str(credentials.get("token") or "").strip()
        if not token:
            raise MaxApiError("token is required")
        return await max_client.get_me(token)

    async def connect(
        self,
        session: AsyncSession,
        *,
        credentials: dict[str, Any],
        created_by_id: int | None,
        name: str | None = None,
    ) -> tuple[Channel, dict[str, Any] | None]:
        token = str(credentials.get("token") or "").strip()
        channel, bot_info = await connect_by_token(
            session,
            token=token,
            created_by_id=created_by_id,
            name=name,
        )
        return channel, bot_info

    async def send_text(
        self,
        channel: Channel,
        dialog: Dialog,
        text: str,
        *,
        reply_to_external_id: str | None = None,
    ) -> SendResult:
        if not channel.credentials_enc:
            raise MaxApiError("Channel has no credentials")
        token = decrypt_secret(channel.credentials_enc)
        user_id, chat_id = self._destination(dialog)
        if user_id is not None:
            payload = await max_client.send_message(
                token, text=text, user_id=user_id, reply_to_mid=reply_to_external_id
            )
        elif chat_id is not None:
            payload = await max_client.send_message(
                token, text=text, chat_id=chat_id, reply_to_mid=reply_to_external_id
            )
        else:
            raise MaxApiError("No Max destination id on dialog")
        return max_payload_to_send_result(payload)

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
        if not channel.credentials_enc:
            raise MaxApiError("Channel has no credentials")
        token = decrypt_secret(channel.credentials_enc)
        upload_type = kind if kind in {"image", "video", "audio", "file"} else "file"
        media_token = await max_client.upload_and_get_token(
            token,
            upload_type=upload_type,
            data=data,
            filename=filename,
        )
        attachments = [{"type": upload_type, "payload": {"token": media_token}}]
        user_id, chat_id = self._destination(dialog)
        if user_id is not None:
            payload = await max_client.send_message(
                token,
                text=caption or None,
                user_id=user_id,
                attachments=attachments,
                reply_to_mid=reply_to_external_id,
            )
        elif chat_id is not None:
            payload = await max_client.send_message(
                token,
                text=caption or None,
                chat_id=chat_id,
                attachments=attachments,
                reply_to_mid=reply_to_external_id,
            )
        else:
            raise MaxApiError("No Max destination id on dialog")
        return max_payload_to_send_result(payload)

    async def edit_text(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
        text: str,
    ) -> None:
        if not channel.credentials_enc:
            raise MaxApiError("Channel has no credentials")
        token = decrypt_secret(channel.credentials_enc)
        await max_client.edit_message(token, message_id=external_id, text=text)

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        if not channel.credentials_enc:
            raise MaxApiError("Channel has no credentials")
        token = decrypt_secret(channel.credentials_enc)
        await max_client.delete_message(token, message_id=external_id)

    def _destination(self, dialog: Dialog) -> tuple[int | None, int | None]:
        user_id = (
            int(dialog.contact_external_id)
            if dialog.contact_external_id and dialog.contact_external_id.isdigit()
            else None
        )
        chat_id = int(dialog.external_chat_id) if dialog.external_chat_id.isdigit() else None
        return user_id, chat_id

    async def start_worker(self) -> None:
        poller.start()

    async def stop_worker(self) -> None:
        await poller.stop()

    async def on_channel_deleted(self, channel_id: int) -> None:
        # Long-poll loads channels from DB each cycle — nothing to detach.
        return None
