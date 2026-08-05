from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect

from app.models import Appeal, ChannelTransport, ChatMessage, Dialog
from app.realtime.hub import hub
from app.realtime.webhooks import dispatch_webhook_event
from app.schemas import DialogOut
from app.serializers import message_to_out

logger = logging.getLogger(__name__)


def _safe_current_appeal(dialog: Dialog) -> Appeal | None:
    """Avoid async lazy-load outside a greenlet (e.g. pymax callbacks)."""
    try:
        insp = sa_inspect(dialog)
        if "current_appeal" in insp.unloaded:
            return None
        return dialog.current_appeal
    except Exception:
        return None


def dialog_to_out(dialog: Dialog, transport: str | ChannelTransport | None = None) -> DialogOut:
    resolved = transport
    if resolved is None:
        try:
            insp = sa_inspect(dialog)
            if "channel" not in insp.unloaded and dialog.channel is not None:
                resolved = dialog.channel.transport
        except Exception:
            resolved = None
    transport_enum = None
    if resolved is not None:
        transport_enum = resolved if isinstance(resolved, ChannelTransport) else ChannelTransport(resolved)
    appeal = _safe_current_appeal(dialog)
    return DialogOut(
        id=dialog.id,
        channel_id=dialog.channel_id,
        contact_name=dialog.contact_name,
        contact_phone=getattr(dialog, "contact_phone", None),
        contact_username=dialog.contact_username,
        contact_avatar_url=dialog.contact_avatar_url,
        last_message=dialog.last_message,
        last_at=dialog.last_at,
        last_direction=dialog.last_direction,  # type: ignore[arg-type]
        last_status=dialog.last_status,  # type: ignore[arg-type]
        unread=dialog.unread,
        assignee_id=dialog.assignee_id,
        transport=transport_enum,
        appeal_id=appeal.id if appeal else dialog.current_appeal_id,
        appeal_number=appeal.number if appeal else None,
        appeal_status=appeal.status if appeal else None,  # type: ignore[arg-type]
        department_id=getattr(dialog, "department_id", None),
    )


def message_created_event(
    dialog: Dialog,
    message: ChatMessage,
    transport: str | ChannelTransport | None = None,
) -> dict[str, Any]:
    return {
        "type": "message.created",
        "message": message_to_out(message).model_dump(mode="json"),
        "dialog": dialog_to_out(dialog, transport).model_dump(mode="json"),
    }


def message_updated_event(
    dialog: Dialog,
    message: ChatMessage,
    transport: str | ChannelTransport | None = None,
) -> dict[str, Any]:
    return {
        "type": "message.updated",
        "message": message_to_out(message).model_dump(mode="json"),
        "dialog": dialog_to_out(dialog, transport).model_dump(mode="json"),
    }


def message_deleted_event(
    dialog: Dialog,
    message: ChatMessage,
    transport: str | ChannelTransport | None = None,
) -> dict[str, Any]:
    return {
        "type": "message.deleted",
        "message": message_to_out(message).model_dump(mode="json"),
        "dialog": dialog_to_out(dialog, transport).model_dump(mode="json"),
    }


def dialog_updated_event(
    dialog: Dialog,
    transport: str | ChannelTransport | None = None,
) -> dict[str, Any]:
    return {
        "type": "dialog.updated",
        "dialog": dialog_to_out(dialog, transport).model_dump(mode="json"),
    }


def dialog_assigned_event(
    dialog: Dialog,
    transport: str | ChannelTransport | None = None,
    *,
    assigned_by_id: int | None = None,
    assigned_by_name: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "dialog.assigned",
        "dialog": dialog_to_out(dialog, transport).model_dump(mode="json"),
    }
    if assigned_by_id is not None:
        event["assigned_by"] = {
            "id": assigned_by_id,
            "name": (assigned_by_name or "").strip() or None,
        }
    return event


def channel_status_event(channel_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "channel.status",
        "channel": channel_payload,
    }


async def emit_event(event: dict[str, Any]) -> None:
    """Broadcast to WS clients and fan-out to outbound webhooks."""
    import asyncio

    try:
        await hub.broadcast(event)
    except Exception:
        logger.exception("WS broadcast failed for %s", event.get("type"))
    event_type = event.get("type")
    message = event.get("message")
    if isinstance(message, dict) and message.get("is_internal"):
        # Internal notes stay inside the CRM — do not fan out to webhooks.
        return
    if isinstance(event_type, str):
        payload = {k: v for k, v in event.items() if k != "type"}

        async def _fanout() -> None:
            try:
                await dispatch_webhook_event(event_type, payload)
            except Exception:
                logger.exception("Webhook fan-out failed for %s", event_type)

        asyncio.create_task(_fanout())


async def publish_message_created(
    dialog: Dialog,
    message: ChatMessage,
    transport: str | ChannelTransport | None = None,
) -> None:
    await emit_event(message_created_event(dialog, message, transport))


async def publish_dialog_updated(
    dialog: Dialog,
    transport: str | ChannelTransport | None = None,
) -> None:
    await emit_event(dialog_updated_event(dialog, transport))

