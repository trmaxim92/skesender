from __future__ import annotations

import io
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError, SendResult
from app.integrations.telegram_bot.result import parse_telegram_external_id
from app.integrations.telegram_user.inbox import message_external_id
from app.integrations.telegram_user.runtime import runtime
from app.models import Channel, ChannelTransport, Dialog


class TelegramUserAdapter:
    transport = ChannelTransport.TGAPI

    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "credentials_keys": list(credentials.keys())}

    async def connect(
        self,
        session: AsyncSession,
        *,
        credentials: dict[str, Any],
        created_by_id: int | None,
        name: str | None = None,
    ) -> tuple[Channel, dict[str, Any] | None]:
        raise IntegrationError("Use POST /channels/tgapi/qr/start for Telegram personal connect")

    async def send_text(
        self,
        channel: Channel,
        dialog: Dialog,
        text: str,
        *,
        reply_to_external_id: str | None = None,
    ) -> SendResult:
        client = await runtime.ensure_client(channel.id)
        chat_id = int(dialog.external_chat_id)
        reply_to = self._reply_id(reply_to_external_id)
        message = await client.send_message(chat_id, text, reply_to=reply_to)
        mid = getattr(message, "id", None)
        return SendResult(
            external_id=message_external_id(chat_id, int(mid)) if mid is not None else None,
            raw={"message_id": mid, "chat_id": chat_id, "text": text},
        )

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
        client = await runtime.ensure_client(channel.id)
        chat_id = int(dialog.external_chat_id)
        reply_to = self._reply_id(reply_to_external_id)
        file_obj = io.BytesIO(data)
        file_obj.name = filename
        message = await client.send_file(
            chat_id,
            file_obj,
            caption=caption or "",
            reply_to=reply_to,
            force_document=(kind == "file"),
        )
        mid = getattr(message, "id", None)
        return SendResult(
            external_id=message_external_id(chat_id, int(mid)) if mid is not None else None,
            raw={"message_id": mid, "chat_id": chat_id, "kind": kind},
        )

    async def edit_text(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
        text: str,
    ) -> None:
        client = await runtime.ensure_client(channel.id)
        chat_id, message_id = parse_telegram_external_id(external_id)
        resolved_chat = int(chat_id) if chat_id else int(dialog.external_chat_id)
        if message_id is None:
            raise IntegrationError("Invalid Telegram message id")
        await client.edit_message(resolved_chat, message_id, text)

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        client = await runtime.ensure_client(channel.id)
        chat_id, message_id = parse_telegram_external_id(external_id)
        resolved_chat = int(chat_id) if chat_id else int(dialog.external_chat_id)
        if message_id is None:
            raise IntegrationError("Invalid Telegram message id")
        await client.delete_messages(resolved_chat, [message_id])

    def _reply_id(self, reply_to_external_id: str | None) -> int | None:
        if not reply_to_external_id:
            return None
        _, message_id = parse_telegram_external_id(reply_to_external_id)
        return message_id

    async def start_worker(self) -> None:
        await runtime.restore_online_channels()

    async def stop_worker(self) -> None:
        await runtime.stop_all()

    async def on_channel_deleted(self, channel_id: int) -> None:
        await runtime.stop_channel(channel_id)
