from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from pymax import File, Photo, Video
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import IntegrationError, SendResult
from app.integrations.max_personal.runtime import runtime
from app.integrations.max_personal.upload_patch import apply_photo_upload_patch
from app.models import Channel, ChannelTransport, Dialog

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


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


def _is_photo_upload_url_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "photoids" in text or "photo upload url" in text


def _safe_image_name(filename: str, mime_type: str | None) -> str:
    """Keep a short image name with a known extension for pymax Photo validation."""
    raw = (filename or "photo.jpg").strip() or "photo.jpg"
    suffix = Path(raw).suffix.lower()
    if suffix not in _IMAGE_EXTS:
        if mime_type and "png" in mime_type:
            suffix = ".png"
        elif mime_type and "webp" in mime_type:
            suffix = ".webp"
        elif mime_type and "gif" in mime_type:
            suffix = ".gif"
        else:
            suffix = ".jpg"
        raw = f"{Path(raw).stem or 'photo'}{suffix}"
    # Android screenshots can be very long; keep basename short.
    stem = Path(raw).stem[:80] or "photo"
    return f"{stem}{Path(raw).suffix.lower()}"


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
        apply_photo_upload_patch()
        client = await runtime.ensure_client(channel.id)
        chat_id = int(dialog.external_chat_id)
        reply_to = _pymax_reply_id(reply_to_external_id)
        text = caption or ""

        if kind == "image":
            image_name = _safe_image_name(filename, mime_type)
            last_exc: Exception | None = None
            for attempt in range(1, 4):
                try:
                    message = await client.send_message(
                        chat_id=chat_id,
                        text=text,
                        attachments=[Photo(raw=data, name=image_name)],
                        reply_to=reply_to,
                    )
                    mid = getattr(message, "id", None) if message else None
                    return SendResult(
                        external_id=str(mid) if mid is not None else None,
                        raw={
                            "message_id": mid,
                            "text": text,
                            "kind": kind,
                            "attempt": attempt,
                        },
                    )
                except Exception as exc:
                    last_exc = exc
                    if not _is_photo_upload_url_error(exc):
                        raise IntegrationError(_format_pymax_error(exc)) from exc
                    logger.warning(
                        "MAX photo upload failed attempt=%s/3 chat=%s: %s",
                        attempt,
                        chat_id,
                        exc,
                    )
                    await asyncio.sleep(0.4 * attempt)

            # Last resort: send as generic file so the operator message still lands.
            logger.warning(
                "MAX photo upload exhausted retries; falling back to File chat=%s",
                chat_id,
            )
            try:
                message = await client.send_message(
                    chat_id=chat_id,
                    text=text,
                    attachments=[File(raw=data, name=image_name)],
                    reply_to=reply_to,
                )
            except Exception as exc:
                raise IntegrationError(
                    _format_pymax_error(last_exc or exc)
                ) from exc
            mid = getattr(message, "id", None) if message else None
            return SendResult(
                external_id=str(mid) if mid is not None else None,
                raw={
                    "message_id": mid,
                    "text": text,
                    "kind": "file",
                    "fallback_from": "image",
                },
            )

        if kind == "video":
            attachment = Video(raw=data, name=filename)
        else:
            attachment = File(raw=data, name=filename)
        try:
            message = await client.send_message(
                chat_id=chat_id,
                text=text,
                attachments=[attachment],
                reply_to=reply_to,
            )
        except Exception as exc:
            raise IntegrationError(_format_pymax_error(exc)) from exc
        mid = getattr(message, "id", None) if message else None
        return SendResult(
            external_id=str(mid) if mid is not None else None,
            raw={"message_id": mid, "text": text, "kind": kind},
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
        apply_photo_upload_patch()
        await runtime.restore_online_channels()

    async def stop_worker(self) -> None:
        await runtime.stop_all()

    async def on_channel_deleted(self, channel_id: int) -> None:
        await runtime.stop_channel(channel_id)
