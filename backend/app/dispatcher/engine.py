"""Dispatcher: event → conditions → actions (HelpdeskEddy-style automation)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.integrations.base import ChannelNotReadyError, IntegrationError
from app.integrations.registry import get_adapter
from app.models import (
    Channel,
    ChatMessage,
    Dialog,
    DispatcherRule,
    DispatcherRuleGroup,
    DispatcherRuleRun,
    MessageDirection,
    MessageStatus,
    utcnow,
)
from app.realtime.publish import dialog_updated_event, emit_event, message_created_event

logger = logging.getLogger(__name__)

TRIGGER_APPEAL_OPENED = "appeal.opened"
SUPPORTED_TRIGGERS = {TRIGGER_APPEAL_OPENED}

# Fields allowed in conditions for MVP.
_CONDITION_FIELDS = {"channel_id", "department_id", "transport"}


def schedule_appeal_opened(*, dialog_id: int, appeal_id: int) -> None:
    """Fire-and-forget after inbound create; waits briefly so caller can commit."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running loop — skip dispatcher appeal.opened")
        return
    loop.create_task(
        _run_appeal_opened_deferred(dialog_id, appeal_id),
        name=f"dispatcher-appeal-opened-{appeal_id}",
    )


async def _run_appeal_opened_deferred(dialog_id: int, appeal_id: int) -> None:
    await asyncio.sleep(0.4)
    try:
        async with SessionLocal() as session:
            await process_trigger(
                session,
                TRIGGER_APPEAL_OPENED,
                dialog_id=dialog_id,
                appeal_id=appeal_id,
            )
    except Exception:
        logger.exception(
            "Dispatcher appeal.opened failed dialog=%s appeal=%s",
            dialog_id,
            appeal_id,
        )


async def process_trigger(
    session: AsyncSession,
    trigger: str,
    *,
    dialog_id: int,
    appeal_id: int,
) -> int:
    """Match active rules and run actions. Returns number of rules applied."""
    if trigger not in SUPPORTED_TRIGGERS:
        return 0

    result = await session.execute(
        select(Dialog)
        .options(selectinload(Dialog.channel))
        .where(Dialog.id == dialog_id)
    )
    dialog = result.scalar_one_or_none()
    if dialog is None or dialog.channel is None:
        return 0

    channel = dialog.channel
    appeal_number = appeal_id
    from app.models import Appeal

    appeal_row = await session.get(Appeal, appeal_id)
    if appeal_row is not None:
        appeal_number = appeal_row.number

    ctx = {
        "channel_id": channel.id,
        "department_id": dialog.department_id,
        "transport": channel.transport,
        "contact_name": dialog.contact_name or "Клиент",
        "appeal_id": appeal_id,
        "appeal_number": appeal_number,
    }

    rules = await _load_matching_rules(session, trigger)
    applied = 0
    for rule in rules:
        if not _conditions_match(rule, ctx):
            continue
        ok = await _apply_rule(session, rule, dialog=dialog, channel=channel, ctx=ctx)
        if ok:
            applied += 1
    return applied


async def _load_matching_rules(session: AsyncSession, trigger: str) -> list[DispatcherRule]:
    result = await session.execute(
        select(DispatcherRule)
        .join(DispatcherRuleGroup)
        .where(
            DispatcherRule.active.is_(True),
            DispatcherRuleGroup.active.is_(True),
            DispatcherRule.trigger == trigger,
        )
        .order_by(DispatcherRuleGroup.sort_order, DispatcherRule.sort_order, DispatcherRule.id)
    )
    return list(result.scalars().all())


def _parse_json_list(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _conditions_match(rule: DispatcherRule, ctx: dict[str, Any]) -> bool:
    conditions = _parse_json_list(rule.conditions_json)
    if not conditions:
        return True
    for cond in conditions:
        field = str(cond.get("field") or "")
        op = str(cond.get("op") or "eq")
        expected = cond.get("value")
        if field not in _CONDITION_FIELDS:
            continue
        actual = ctx.get(field)
        if op == "eq":
            if actual != expected:
                return False
        elif op == "in":
            if not isinstance(expected, list) or actual not in expected:
                return False
        elif op == "neq":
            if actual == expected:
                return False
        else:
            return False
    return True


async def _apply_rule(
    session: AsyncSession,
    rule: DispatcherRule,
    *,
    dialog: Dialog,
    channel: Channel,
    ctx: dict[str, Any],
) -> bool:
    appeal_id = int(ctx["appeal_id"])
    # Idempotency claim
    run = DispatcherRuleRun(
        rule_id=rule.id,
        appeal_id=appeal_id,
        dialog_id=dialog.id,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        return False

    actions = _parse_json_list(rule.actions_json)
    any_ok = False
    for action in actions:
        atype = str(action.get("type") or "")
        if atype == "send_reply":
            text = str(action.get("text") or "").strip()
            if not text:
                continue
            text = (
                text.replace("{{contact}}", str(ctx.get("contact_name") or "Клиент"))
                .replace("{{appeal}}", str(ctx.get("appeal_number") or ctx.get("appeal_id") or ""))
            )
            ok = await _send_system_reply(
                session,
                dialog=dialog,
                channel=channel,
                appeal_id=appeal_id,
                text=text,
            )
            any_ok = any_ok or ok
        else:
            logger.warning("Dispatcher unknown action type=%s rule=%s", atype, rule.id)

    if any_ok:
        rule.last_applied_at = utcnow()
        await session.commit()
        return True

    # No successful action — release claim so a later retry can run.
    stored = await session.get(DispatcherRuleRun, run.id)
    if stored is not None:
        await session.delete(stored)
        await session.commit()
    return False


async def _send_system_reply(
    session: AsyncSession,
    *,
    dialog: Dialog,
    channel: Channel,
    appeal_id: int,
    text: str,
) -> bool:
    if not channel.credentials_enc and channel.transport != "webchat":
        logger.warning(
            "Dispatcher skip send: channel %s has no credentials", channel.id
        )
        return False

    msg = ChatMessage(
        dialog_id=dialog.id,
        channel_id=channel.id,
        appeal_id=appeal_id,
        direction=MessageDirection.OUT.value,
        text=text,
        status=MessageStatus.SENT.value,
        operator_id=None,
        operator_name="Система",
        created_at=utcnow(),
    )
    session.add(msg)
    dialog.last_message = text[:500]
    dialog.last_direction = MessageDirection.OUT.value
    dialog.last_status = MessageStatus.SENT.value
    dialog.last_at = utcnow()
    await session.flush()
    msg_id = msg.id
    await session.commit()

    adapter = get_adapter(channel.transport)

    async def _send():
        # Re-load channel/dialog in case session expired — adapter uses ORM objects.
        ch = await session.get(Channel, channel.id)
        dlg = await session.get(Dialog, dialog.id)
        if ch is None or dlg is None:
            raise IntegrationError("Channel/dialog missing for dispatcher send")
        return await adapter.send_text(ch, dlg, text)

    try:
        send_result = await _send()
    except (ChannelNotReadyError, IntegrationError) as exc:
        msg = await session.get(ChatMessage, msg_id)
        if msg is not None:
            msg.status = MessageStatus.FAILED.value
            msg.delivery_error = str(exc)[:2000]
            await session.commit()
        logger.warning(
            "Dispatcher send_reply failed dialog=%s: %s", dialog.id, exc
        )
        return False
    except Exception as exc:
        msg = await session.get(ChatMessage, msg_id)
        if msg is not None:
            msg.status = MessageStatus.FAILED.value
            msg.delivery_error = str(exc)[:2000]
            await session.commit()
        logger.exception("Dispatcher send_reply error dialog=%s", dialog.id)
        return False

    external_id = getattr(send_result, "external_id", None)
    if external_id is not None:
        external_id = str(external_id)

    msg = await session.get(ChatMessage, msg_id)
    if msg is None:
        return False
    msg.external_id = external_id
    msg.status = MessageStatus.DELIVERED.value
    msg.delivery_error = None
    dialog_row = await session.get(Dialog, dialog.id)
    if dialog_row is not None:
        dialog_row.last_status = MessageStatus.DELIVERED.value
    await session.commit()

    result = await session.execute(
        select(Dialog)
        .options(selectinload(Dialog.channel), selectinload(Dialog.current_appeal))
        .where(Dialog.id == dialog.id)
    )
    dialog_loaded = result.scalar_one_or_none()
    msg = await session.get(
        ChatMessage,
        msg_id,
        options=(selectinload(ChatMessage.attachments),),
    )
    if dialog_loaded is not None and msg is not None:
        transport = dialog_loaded.channel.transport if dialog_loaded.channel else channel.transport
        await emit_event(message_created_event(dialog_loaded, msg, transport))
        await emit_event(dialog_updated_event(dialog_loaded, transport))
    return True
