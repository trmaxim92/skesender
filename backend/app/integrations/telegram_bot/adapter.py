from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import SendResult
from app.integrations.telegram_bot import client as tg_client
from app.integrations.telegram_bot.client import TelegramApiError
from app.integrations.telegram_bot.connector import connect_by_token
from app.integrations.telegram_bot.poller import poller
from app.integrations.telegram_bot.result import parse_telegram_external_id, telegram_payload_to_send_result
from app.models import Channel, ChannelTransport, Dialog
from app.security import decrypt_secret


class TelegramBotAdapter:
    transport = ChannelTransport.TELEGRAM

    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        token = str(credentials.get("token") or "").strip()
        if not token:
            raise TelegramApiError("token is required")
        return await tg_client.get_me(token)

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
        token = self._token(channel)
        chat_id = self._chat_id(dialog)
        reply_id = self._reply_message_id(reply_to_external_id)
        payload = await tg_client.send_message(
            token,
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_id,
        )
        return telegram_payload_to_send_result(payload)

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
        token = self._token(channel)
        chat_id = self._chat_id(dialog)
        reply_id = self._reply_message_id(reply_to_external_id)
        media_kind = kind if kind in {"image", "video", "audio", "file"} else "file"

        if media_kind == "image":
            payload = await tg_client.send_photo(
                token,
                chat_id=chat_id,
                data=data,
                filename=filename,
                caption=caption,
                reply_to_message_id=reply_id,
            )
        elif media_kind == "video":
            payload = await tg_client.send_video(
                token,
                chat_id=chat_id,
                data=data,
                filename=filename,
                caption=caption,
                reply_to_message_id=reply_id,
                mime_type=mime_type,
            )
        elif media_kind == "audio":
            payload = await tg_client.send_audio(
                token,
                chat_id=chat_id,
                data=data,
                filename=filename,
                caption=caption,
                reply_to_message_id=reply_id,
                mime_type=mime_type,
            )
        else:
            payload = await tg_client.send_document(
                token,
                chat_id=chat_id,
                data=data,
                filename=filename,
                caption=caption,
                reply_to_message_id=reply_id,
                mime_type=mime_type,
            )
        return telegram_payload_to_send_result(payload)

    async def edit_text(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
        text: str,
    ) -> None:
        token = self._token(channel)
        chat_id, message_id = parse_telegram_external_id(external_id)
        if message_id is None:
            raise TelegramApiError("Invalid Telegram message id")
        resolved_chat = chat_id or self._chat_id(dialog)
        await tg_client.edit_message_text(
            token,
            chat_id=resolved_chat,
            message_id=message_id,
            text=text,
        )

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        token = self._token(channel)
        chat_id, message_id = parse_telegram_external_id(external_id)
        if message_id is None:
            raise TelegramApiError("Invalid Telegram message id")
        resolved_chat = chat_id or self._chat_id(dialog)
        await tg_client.delete_message(
            token,
            chat_id=resolved_chat,
            message_id=message_id,
        )

    def _token(self, channel: Channel) -> str:
        if not channel.credentials_enc:
            raise TelegramApiError("Channel has no credentials")
        return decrypt_secret(channel.credentials_enc)

    def _chat_id(self, dialog: Dialog) -> str:
        if not dialog.external_chat_id:
            raise TelegramApiError("No Telegram chat id on dialog")
        return dialog.external_chat_id

    def _reply_message_id(self, reply_to_external_id: str | None) -> int | None:
        if not reply_to_external_id:
            return None
        _, message_id = parse_telegram_external_id(reply_to_external_id)
        return message_id

    async def start_worker(self) -> None:
        poller.start()

    async def stop_worker(self) -> None:
        await poller.stop()

    async def on_channel_deleted(self, channel_id: int) -> None:
        return None
