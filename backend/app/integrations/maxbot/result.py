from __future__ import annotations

from typing import Any

from app.integrations.base import SendResult


def max_payload_to_send_result(payload: dict[str, Any] | Any) -> SendResult:
    """Map Max Bot API /messages response into universal SendResult."""
    raw = payload if isinstance(payload, dict) else {"value": payload}
    message_obj = raw.get("message") if isinstance(raw.get("message"), dict) else None
    external_id = None
    if message_obj:
        body_obj = message_obj.get("body") if isinstance(message_obj.get("body"), dict) else {}
        mid = body_obj.get("mid") or message_obj.get("id")
        if mid is not None:
            external_id = str(mid)
    return SendResult(external_id=external_id, raw=raw)
