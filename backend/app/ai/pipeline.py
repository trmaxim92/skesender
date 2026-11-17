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
from app.ai.rag import RagChunk, is_tariff_query, retrieve_context
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

PRIMARY_DEFAULT = {
    "faq",
    "status",
    "hours",
    "greeting",
    "thanks",
    "commission",
    "conditions",
    "tariff",
    "tariffs",
}


def _intent_tokens(intent: str) -> set[str]:
    return {
        part.strip().lower()
        for part in re.split(r"[|,/;]+", intent or "")
        if part.strip()
    }


def _intent_allows_auto(intent: str, primary: set[str]) -> bool:
    tokens = _intent_tokens(intent)
    if not tokens:
        return False
    if tokens & primary:
        return True
    # Models often return "faq|commission" — treat faq-family as auto-eligible.
    if "faq" in tokens and primary & {"faq", "commission", "conditions", "tariff", "tariffs"}:
        return True
    return False

# If the model admits it has no answer, never auto-send.
_ESCALATE_MARKERS = (
    "нет в базе",
    "отсутствует в нашей базе",
    "отсутствует в базе",
    "нет информации",
    "не могу найти",
    "данных нет",
    "дождаться оператора",
    "передам оператору",
    "нужна помощь оператора",
    "обратитесь к оператору",
)

# Explicit handoff phrases from the client (not park-specific).
_OPERATOR_CMD_RE = re.compile(
    r"(?i)(?<![а-яёa-z0-9])("
    r"оператор(?:а|у|ом|ы)?|"
    r"менеджер(?:а|у|ом|ы)?|"
    r"живой\s+человек|"
    r"позови(?:те)?\s+(?:оператора|менеджера|человека)|"
    r"свяжи(?:те)?\s+с\s+(?:оператором|менеджером)|"
    r"перевед(?:и|ите)\s+на\s+(?:оператора|менеджера)|"
    r"human|operator"
    r")(?![а-яёa-z0-9])"
)

_FLUFF_SENTENCE_RE = re.compile(
    r"(?i)\s*(?:"
    r"точная сумма комиссии зависит[^.!?]*[.!?]"
    r"|для получения подробной информации[^.!?]*[.!?]"
    r"|пожалуйста,?\s*обратитесь к[^.!?]*[.!?]"
    r"|обратитесь к вашему личному менеджеру[^.!?]*[.!?]"
    r"|если у вас есть другие вопросы[^.!?]*[.!?]"
    r"|общая процентная комиссия[^.!?]*[.!?]"
    r"|общая комиссия по двум составляющим[^.!?]*[.!?]"
    r")"
)


def _wants_operator(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if low in {
        "оператор",
        "оператора",
        "менеджер",
        "менеджера",
        "человек",
        "operator",
        "human",
    }:
        return True
    return bool(_OPERATOR_CMD_RE.search(raw))


def _trim_fluff(reply: str) -> str:
    cleaned = _FLUFF_SENTENCE_RE.sub(" ", reply or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or (reply or "").strip()


def _normalize_for_sim(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[\wа-яёА-ЯЁ]{3,}", (text or "").lower(), flags=re.IGNORECASE)
    }


def _too_similar(a: str, b: str, *, threshold: float = 0.72) -> bool:
    ta, tb = _normalize_for_sim(a), _normalize_for_sim(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return (inter / union) >= threshold if union else False


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
    tariff_mode: bool = False,
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
    last_inbound = ""
    for msg in history:
        role = "Клиент" if msg.direction == MessageDirection.IN.value else "Оператор"
        text = (msg.text or "").strip()[:500]
        hist_lines.append(f"{role}: {text}")
        if msg.direction == MessageDirection.IN.value and text:
            last_inbound = text
    hist_block = "\n".join(hist_lines) or "(пусто)"
    contact = dialog.contact_name or "Клиент"
    extra = ""
    if tariff_mode:
        extra = (
            "\nВажно: в базе могут быть несколько тарифов. Ответь только фактами из блока базы. "
            "Разделяй тарифы. Не смешивай комиссию парка и комиссию банка/вывода. "
            "Не считай «общую комиссию» суммированием разных строк.\n"
        )
    user = (
        f"Контакт: {contact}\n"
        f"Телефон/username: {dialog.contact_phone or dialog.contact_username or '-'}\n\n"
        f"История:\n{hist_block}\n\n"
        f"База знаний и примеры:\n{kb_block}\n"
        f"{extra}\n"
        f"Текущий вопрос клиента (ответь ИМЕННО на него, не на прошлую тему):\n{last_inbound or '(см. историю)'}\n\n"
        "Сформулируй ответ клиенту строго по правилам system. "
        "Не повторяй предыдущий ответ бота, если вопрос изменился."
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
    if bool(getattr(dialog, "ai_paused", False)):
        logger.debug("AI skip: paused for human dialog=%s", dialog_id)
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

    inbound_text = (message.text or "").strip()
    operator_request = _wants_operator(inbound_text)

    # Explicit «оператор» / «менеджер» → handoff without waiting for LLM.
    if operator_request:
        reply = "Передаю ваш диалог менеджеру. Ожидайте ответа."
        confidence = 100
        intent = "operator"
        needs_human = True
        has_rag = False
        sources: list[dict] = []
        raw = json.dumps(
            {
                "reply": reply,
                "confidence": confidence,
                "intent": intent,
                "needs_human": True,
                "citations": [],
            },
            ensure_ascii=False,
        )
        suggestion = AiSuggestion(
            dialog_id=dialog_id,
            message_id=message_id,
            department_id=dialog.department_id,
            status=AiSuggestionStatus.PENDING.value,
            draft_text=reply,
            confidence=confidence,
            intent=intent,
            needs_human=True,
            sources_json="[]",
            raw_response_json=raw,
        )
        session.add(suggestion)
        await session.flush()
        from app.ai.handoff import pause_ai_for_dialog

        await pause_ai_for_dialog(session, dialog, reason="operator_command")

        mode = (profile.mode or AiAgentMode.HYBRID.value).strip().lower()
        can_auto = mode in {AiAgentMode.HYBRID.value, AiAgentMode.AUTO.value}
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
                logger.exception("AI operator handoff send failed dialog=%s", dialog_id)
                suggestion.status = AiSuggestionStatus.PENDING.value
                suggestion.auto_sent_message_id = None
        await session.commit()
        return PipelineResult(suggestion=suggestion, auto_sent=False)

    dept_slug = None
    if dialog.department_id is not None:
        dept = await session.get(Department, dialog.department_id)
        if dept is not None:
            dept_slug = dept.slug or dept.name

    history = await _history(session, dialog_id)
    chunks = await retrieve_context(
        session,
        department_id=dialog.department_id,
        query=inbound_text,
        limit=5 if is_tariff_query(inbound_text) else 4,
    )
    has_rag = bool(chunks)
    tariff_mode = is_tariff_query(inbound_text)
    reply_words = int(runtime.max_reply_words or 80)
    # Listing tariffs from KB may need a bit more room — still no hard-coded facts.
    if tariff_mode:
        reply_words = max(reply_words, 180)
    else:
        # Prefer short factual answers for ordinary FAQ.
        reply_words = min(reply_words, 60)
    prompt = _build_prompt(
        profile=profile,
        dialog=dialog,
        history=history,
        chunks=chunks,
        department_slug=dept_slug,
        max_reply_words=reply_words,
        tariff_mode=tariff_mode,
    )

    try:
        raw = await chat_completion(
            messages=prompt,
            model=(profile.gigachat_model or runtime.default_model or "GigaChat"),
            # Factual tariff/commission answers: stick closer to KB text.
            temperature=0.1 if tariff_mode else None,
            max_tokens=max(int(runtime.max_tokens or 512), 900) if tariff_mode else None,
            cfg=runtime,
        )
    except GigaChatError:
        logger.exception("GigaChat completion failed dialog=%s", dialog_id)
        return None

    parsed = _parse_llm_json(raw)
    reply = _trim_fluff(str(parsed.get("reply") or "").strip())
    if not reply:
        return None
    confidence = _normalize_confidence(parsed.get("confidence"))
    intent = str(parsed.get("intent") or "other").strip().lower()[:64]
    needs_human = bool(parsed.get("needs_human", True))
    # Sber-style RAG gate: no knowledge context → escalate, never auto.
    if not has_rag:
        needs_human = True
        confidence = min(confidence, 40)
    reply_l = reply.lower()
    if any(marker in reply_l for marker in _ESCALATE_MARKERS):
        needs_human = True

    last_ai_text = ""
    for msg in reversed(history):
        if msg.direction == MessageDirection.OUT.value and bool(getattr(msg, "is_ai", False)):
            last_ai_text = (msg.text or "").strip()
            break
    # Never auto-spam the same tariff blurb when the client changed the topic.
    block_duplicate_auto = bool(last_ai_text and _too_similar(reply, last_ai_text))

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

    # Handoff to human: keep this draft visible, but stop further AI on this dialog.
    if needs_human:
        from app.ai.handoff import pause_ai_for_dialog

        await pause_ai_for_dialog(session, dialog, reason="needs_human")

    mode = (profile.mode or AiAgentMode.HYBRID.value).strip().lower()
    primary = {
        p.strip().lower()
        for p in (profile.primary_intents or "").split(",")
        if p.strip()
    } or set(PRIMARY_DEFAULT)

    confidence_min = int(profile.auto_confidence_min or 55)
    intent_tokens = _intent_tokens(intent)
    # Safe short intents: slightly lower bar when RAG matched.
    if intent_tokens & {"greeting", "thanks"} and has_rag:
        confidence_min = min(confidence_min, 50)
    can_auto = (
        mode in {AiAgentMode.HYBRID.value, AiAgentMode.AUTO.value}
        and not needs_human
        and confidence >= confidence_min
        and _intent_allows_auto(intent, primary)
        and not block_duplicate_auto
    )
    if runtime.require_rag_for_auto and not has_rag:
        can_auto = False
    if can_auto:
        auto_count = await _count_auto_replies(session, dialog_id)
        if auto_count >= int(profile.max_auto_replies_per_dialog or 10):
            can_auto = False

    channel = dialog.channel
    if channel is None:
        channel = await session.get(Channel, dialog.channel_id)
    if can_auto and channel is not None and channel.status == ChannelStatus.ONLINE.value:
        suggestion_id = suggestion.id
        try:
            sent = await send_ai_text(
                session,
                dialog=dialog,
                channel=channel,
                text=reply,
                reply_to_message_id=message_id,
            )
            # send_ai_text commits its own session work — reload suggestion row.
            suggestion = await session.get(AiSuggestion, suggestion_id)
            if suggestion is None:
                await session.commit()
                return None
            suggestion.status = AiSuggestionStatus.AUTO_SENT.value
            suggestion.auto_sent_message_id = sent.id
            suggestion.resolved_at = sent.created_at
            await session.flush()
            await session.commit()
            return PipelineResult(suggestion=suggestion, auto_sent=True)
        except Exception:
            logger.exception("AI auto-send failed dialog=%s", dialog_id)
            suggestion = await session.get(AiSuggestion, suggestion_id)
            if suggestion is not None:
                suggestion.status = AiSuggestionStatus.PENDING.value
                suggestion.auto_sent_message_id = None

    await session.commit()
    return PipelineResult(suggestion=suggestion, auto_sent=False)
