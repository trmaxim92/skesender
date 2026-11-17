"""AI decision pipeline: RAG + GigaChat → suggestion or auto-send."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.gigachat import GigaChatError, chat_completion
from app.ai.prompts import build_system_prompt, prompt_for_department_slug
from app.ai.rag import RagChunk, retrieve_context
from app.models import (
    AiAgentMode,
    AiDepartmentProfile,
    AiSuggestion,
    AiSuggestionStatus,
    Channel,
    ChannelStatus,
    ChatMessage,
    Department,
    Dialog,
    MessageDirection,
)

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{[\s\S]*\}")

PRIMARY_DEFAULT = {"faq", "status", "hours", "greeting", "thanks"}


@dataclass
class PipelineResult:
    suggestion: AiSuggestion
    auto_sent: bool = False


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {
        "reply": text[:4000],
        "confidence": 40,
        "intent": "other",
        "needs_human": True,
        "citations": [],
    }


def _normalize_confidence(value: Any) -> int:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= num <= 1:
        num *= 100
    return max(0, min(100, int(round(num))))


async def _load_profile(
    session: AsyncSession, department_id: int | None
) -> AiDepartmentProfile | None:
    if department_id is None:
        return None
    result = await session.execute(
        select(AiDepartmentProfile).where(AiDepartmentProfile.department_id == department_id)
    )
    return result.scalar_one_or_none()


async def _history(session: AsyncSession, dialog_id: int, *, limit: int = 12) -> list[ChatMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.dialog_id == dialog_id,
            ChatMessage.deleted_at.is_(None),
            ChatMessage.is_internal.is_(False),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return rows


def _build_prompt(
    *,
    profile: AiDepartmentProfile,
    dialog: Dialog,
    history: list[ChatMessage],
    chunks: list[RagChunk],
    department_slug: str | None,
    max_reply_words: int,
) -> list[dict[str, str]]:
    dept_prompt = (profile.system_prompt or "").strip() or prompt_for_department_slug(
        department_slug
    )
    has_rag = bool(chunks)
    system = build_system_prompt(
        department_prompt=dept_prompt,
        max_reply_words=max_reply_words,
        has_rag=has_rag,
    )
    kb_block = "\n\n".join(
        f"[{c.kind}:{c.ref_id}] {c.title}\n{c.text}" for c in chunks
    ) or "(нет фрагментов базы)"
    hist_lines = []
    for msg in history:
        role = "Клиент" if msg.direction == MessageDirection.IN.value else "Оператор"
        hist_lines.append(f"{role}: {(msg.text or '').strip()[:500]}")
    hist_block = "\n".join(hist_lines) or "(пусто)"
    contact = dialog.contact_name or "Клиент"
    user = (
        f"Контакт: {contact}\n"
        f"Телефон/username: {dialog.contact_phone or dialog.contact_username or '-'}\n\n"
        f"История:\n{hist_block}\n\n"
        f"База знаний и примеры:\n{kb_block}\n\n"
        "Сформулируй ответ клиенту строго по правилам system."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _count_auto_replies(session: AsyncSession, dialog_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(AiSuggestion)
        .where(
            AiSuggestion.dialog_id == dialog_id,
            AiSuggestion.status == AiSuggestionStatus.AUTO_SENT.value,
        )
    )
    return int(result.scalar_one() or 0)


async def process_inbound_message(
    session: AsyncSession,
    *,
    dialog_id: int,
    message_id: int,
) -> PipelineResult | None:
    from app.ai.outbound import send_ai_text
    from app.ai.settings_store import load_runtime_config

    runtime = await load_runtime_config(session)
    if not runtime.enabled:
        return None
    if not runtime.configured:
        logger.debug("AI skip: GigaChat not configured in module settings")
        return None

    dialog = await session.get(
        Dialog,
        dialog_id,
        options=[selectinload(Dialog.channel)],
    )
    if dialog is None:
        return None
    message = await session.get(ChatMessage, message_id)
    if message is None or message.dialog_id != dialog_id:
        return None
    if message.direction != MessageDirection.IN.value or message.is_internal:
        return None
    if not (message.text or "").strip():
        return None

    profile = await _load_profile(session, dialog.department_id)
    if profile is None or not profile.enabled:
        return None

    existing = await session.scalar(
        select(AiSuggestion.id).where(
            AiSuggestion.message_id == message_id,
            AiSuggestion.status.in_(
                [
                    AiSuggestionStatus.PENDING.value,
                    AiSuggestionStatus.AUTO_SENT.value,
                ]
            ),
        )
    )
    if existing:
        return None

    dept_slug = None
    if dialog.department_id is not None:
        dept = await session.get(Department, dialog.department_id)
        if dept is not None:
            dept_slug = dept.slug or dept.name

    history = await _history(session, dialog_id)
    chunks = await retrieve_context(
        session,
        department_id=dialog.department_id,
        query=message.text or "",
        limit=6,
    )
    has_rag = bool(chunks)
    prompt = _build_prompt(
        profile=profile,
        dialog=dialog,
        history=history,
        chunks=chunks,
        department_slug=dept_slug,
        max_reply_words=runtime.max_reply_words,
    )

    try:
        raw = await chat_completion(
            messages=prompt,
            model=(profile.gigachat_model or runtime.default_model or "GigaChat"),
            cfg=runtime,
        )
    except GigaChatError:
        logger.exception("GigaChat completion failed dialog=%s", dialog_id)
        return None

    parsed = _parse_llm_json(raw)
    reply = str(parsed.get("reply") or "").strip()
    if not reply:
        return None
    confidence = _normalize_confidence(parsed.get("confidence"))
    intent = str(parsed.get("intent") or "other").strip().lower()[:64]
    needs_human = bool(parsed.get("needs_human", True))
    # Sber-style RAG gate: no knowledge context → escalate, never auto.
    if not has_rag:
        needs_human = True
        confidence = min(confidence, 40)

    sources = [c.as_source() for c in chunks]

    suggestion = AiSuggestion(
        dialog_id=dialog_id,
        message_id=message_id,
        department_id=dialog.department_id,
        status=AiSuggestionStatus.PENDING.value,
        draft_text=reply[:4000],
        confidence=confidence,
        intent=intent,
        needs_human=needs_human,
        sources_json=json.dumps(sources, ensure_ascii=False),
        raw_response_json=raw[:8000],
    )
    session.add(suggestion)
    await session.flush()

    mode = (profile.mode or AiAgentMode.HYBRID.value).strip().lower()
    primary = {
        p.strip().lower()
        for p in (profile.primary_intents or "").split(",")
        if p.strip()
    } or set(PRIMARY_DEFAULT)

    can_auto = (
        mode in {AiAgentMode.HYBRID.value, AiAgentMode.AUTO.value}
        and not needs_human
        and confidence >= int(profile.auto_confidence_min or 75)
        and intent in primary
    )
    if runtime.require_rag_for_auto and not has_rag:
        can_auto = False
    if can_auto:
        auto_count = await _count_auto_replies(session, dialog_id)
        if auto_count >= int(profile.max_auto_replies_per_dialog or 3):
            can_auto = False

    channel = dialog.channel
    if channel is None:
        channel = await session.get(Channel, dialog.channel_id)
    if can_auto and channel is not None and channel.status == ChannelStatus.ONLINE.value:
        try:
            sent = await send_ai_text(
                session,
                dialog=dialog,
                channel=channel,
                text=reply,
                reply_to_message_id=message_id,
            )
            suggestion.status = AiSuggestionStatus.AUTO_SENT.value
            suggestion.auto_sent_message_id = sent.id
            suggestion.resolved_at = sent.created_at
            await session.flush()
            await session.commit()
            return PipelineResult(suggestion=suggestion, auto_sent=True)
        except Exception:
            logger.exception("AI auto-send failed dialog=%s", dialog_id)
            suggestion.status = AiSuggestionStatus.PENDING.value
            suggestion.auto_sent_message_id = None

    await session.commit()
    return PipelineResult(suggestion=suggestion, auto_sent=False)
