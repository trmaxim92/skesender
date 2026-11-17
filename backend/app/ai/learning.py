"""Collect operator Q/A pairs for department RAG (moderation queue)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiLearningExample,
    AiLearningStatus,
    AiSuggestion,
    AiSuggestionStatus,
    ChatMessage,
    Dialog,
    MessageDirection,
    utcnow,
)

logger = logging.getLogger(__name__)


async def record_from_operator_reply(
    session: AsyncSession,
    *,
    dialog: Dialog,
    outbound: ChatMessage,
    suggestion: AiSuggestion | None = None,
    quality: str = "accepted",
    user_id: int | None = None,
) -> AiLearningExample | None:
    if dialog.department_id is None:
        return None
    answer = (outbound.text or "").strip()
    if len(answer) < 2:
        return None

    question = ""
    if suggestion is not None:
        inbound = await session.get(ChatMessage, suggestion.message_id)
        if inbound is not None:
            question = (inbound.text or "").strip()
    if not question:
        result = await session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.dialog_id == dialog.id,
                ChatMessage.direction == MessageDirection.IN.value,
                ChatMessage.deleted_at.is_(None),
                ChatMessage.is_internal.is_(False),
                ChatMessage.id < outbound.id,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        inbound = result.scalar_one_or_none()
        question = (inbound.text or "").strip() if inbound else ""
    if len(question) < 2:
        return None

    example = AiLearningExample(
        department_id=dialog.department_id,
        dialog_id=dialog.id,
        suggestion_id=suggestion.id if suggestion else None,
        user_question=question[:4000],
        operator_answer=answer[:4000],
        quality=quality if quality in {"accepted", "edited"} else "accepted",
        status=AiLearningStatus.PENDING_REVIEW.value,
    )
    session.add(example)
    await session.flush()
    return example


async def resolve_suggestion(
    session: AsyncSession,
    *,
    suggestion: AiSuggestion,
    status: str,
    user_id: int | None,
    edited_text: str | None = None,
) -> AiSuggestion:
    suggestion.status = status
    suggestion.resolved_at = utcnow()
    suggestion.resolved_by_id = user_id
    if edited_text is not None and status == AiSuggestionStatus.EDITED.value:
        suggestion.draft_text = edited_text.strip()[:4000]
    await session.flush()
    return suggestion
