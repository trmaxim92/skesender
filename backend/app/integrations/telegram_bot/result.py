from __future__ import annotations

from typing import Any

from app.integrations.base import SendResult


def telegram_message_external_id(message: dict[str, Any]) -> str | None:
    message_id = message.get("message_id")
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = chat.get("id")
    if message_id is None or chat_id is None:
        if message_id is not None:
            return str(message_id)
        return None
    return f"{chat_id}:{message_id}"


def parse_telegram_external_id(external_id: str) -> tuple[str | None, int | None]:
    """Return (chat_id, message_id) from stored external id."""
    value = (external_id or "").strip()
    if not value:
        return None, None
    if ":" in value:
        chat_part, msg_part = value.rsplit(":", 1)
        try:
            return chat_part, int(msg_part)
        except ValueError:
            return chat_part, None
    try:
        return None, int(value)
    except ValueError:
        return None, None


def telegram_payload_to_send_result(payload: dict[str, Any] | Any) -> SendResult:
    raw = payload if isinstance(payload, dict) else {"value": payload}
    return SendResult(external_id=telegram_message_external_id(raw), raw=raw)
