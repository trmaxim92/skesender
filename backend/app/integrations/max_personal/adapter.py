from __future__ import annotations

from typing import Any

from pymax import File, Photo, Video
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError, SendResult
from app.integrations.max_personal.runtime import runtime
from app.models import Channel, ChannelTransport, Dialog


def _pymax_reply_id(external_id: str | None) -> int | None:
    if not external_id:
        return None
    raw = str(external_id).strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _format_pymax_error(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    low = text.lower()
    if "not.found" in low or "не найден" in low:
        return (
            "MAX не нашёл получателя по этому id. Нужен user/chat id из MAX, "
            "не номер телефона."
        )
    return f"MAX: {text}"


class MaxPersonalAdapter:
    transport = ChannelTransport.MAX

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
        raise IntegrationError("Use POST /channels/max/qr/start for MAX personal connect")

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
        reply_to = _pymax_reply_id(reply_to_external_id)
        try:
            message = await client.send_message(chat_id=chat_id, text=text, reply_to=reply_to)
        except Exception as exc:
            raise IntegrationError(_format_pymax_error(exc)) from exc
        mid = getattr(message, "id", None) if message else None
        return SendResult(
            external_id=str(mid) if mid is not None else None,
            raw={"message_id": mid, "text": text},
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
        if kind == "image":
            attachment = Photo(raw=data, name=filename)
        elif kind == "video":
            attachment = Video(raw=data, name=filename)
        else:
            attachment = File(raw=data, name=filename)
        reply_to = _pymax_reply_id(reply_to_external_id)
        try:
            message = await client.send_message(
                chat_id=chat_id,
                text=caption or "",
                attachments=[attachment],
                reply_to=reply_to,
            )
        except Exception as exc:
            raise IntegrationError(_format_pymax_error(exc)) from exc
        mid = getattr(message, "id", None) if message else None
        return SendResult(
            external_id=str(mid) if mid is not None else None,
            raw={"message_id": mid, "text": caption or "", "kind": kind},
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
        chat_id = int(dialog.external_chat_id)
        mid = _pymax_reply_id(external_id)
        if mid is None:
            raise IntegrationError("Invalid message id for edit")
        await client.edit_message(chat_id=chat_id, message_id=mid, text=text)

    async def delete_message(
        self,
        channel: Channel,
        dialog: Dialog,
        *,
        external_id: str,
    ) -> None:
        client = await runtime.ensure_client(channel.id)
        chat_id = int(dialog.external_chat_id)
        mid = _pymax_reply_id(external_id)
        if mid is None:
            raise IntegrationError("Invalid message id for delete")
        ok = await client.delete_message(chat_id=chat_id, message_ids=[mid], for_me=False)
        if not ok:
            raise IntegrationError("Provider rejected delete")

    async def start_worker(self) -> None:
        await runtime.restore_online_channels()

    async def stop_worker(self) -> None:
        await runtime.stop_all()

    async def on_channel_deleted(self, channel_id: int) -> None:
        await runtime.stop_channel(channel_id)
