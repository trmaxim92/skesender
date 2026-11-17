"""AI module API — department profiles, suggestions, learning queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gigachat import clear_token_cache, ping as gigachat_ping
from app.ai.learning import record_from_operator_reply, resolve_suggestion
from app.ai.settings_store import (
    get_or_create_settings,
    settings_public_dict,
    update_settings,
)
from app.db import get_db
from app.deps import get_current_user
from app.models import (
    AiAgentMode,
    AiDepartmentProfile,
    AiLearningExample,
    AiLearningStatus,
    AiSuggestion,
    AiSuggestionStatus,
    ChatMessage,
    Dialog,
    MessageDirection,
    User,
    utcnow,
)
from app.rbac import (
    ACTION_WRITE,
    SECTION_CHATS,
    SECTION_SETTINGS,
    require_permission,
    user_can,
)
from app.schemas import (
    AiGlobalSettingsOut,
    AiGlobalSettingsUpdateRequest,
    AiLearningExampleOut,
    AiLearningReviewRequest,
    AiMetricsOut,
    AiProfileOut,
    AiProfileUpdateRequest,
    AiStatusOut,
    AiSuggestionActionRequest,
    AiSuggestionOut,
)

router = APIRouter(prefix="/ai", tags=["ai"])


def _require_settings_write(user: User) -> None:
    if not user_can(user, SECTION_SETTINGS) or not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")


def _profile_out(row: AiDepartmentProfile | None, department_id: int) -> AiProfileOut:
    if row is None:
        return AiProfileOut(department_id=department_id)
    return AiProfileOut.model_validate(row)


@router.get("/status", response_model=AiStatusOut)
async def ai_status(
    ping: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> AiStatusOut:
    row = await get_or_create_settings(db)
    await db.commit()
    public = settings_public_dict(row)
    result_ping = None
    if ping:
        result_ping = await gigachat_ping()
    return AiStatusOut(
        ai_enabled=bool(public["enabled"]),
        gigachat_configured=bool(public["client_id"] and public["client_secret_set"]),
        gigachat_ping=result_ping,
    )


@router.get("/settings", response_model=AiGlobalSettingsOut)
async def get_global_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> AiGlobalSettingsOut:
    row = await get_or_create_settings(db)
    await db.commit()
    return AiGlobalSettingsOut.model_validate(settings_public_dict(row))


@router.put("/settings", response_model=AiGlobalSettingsOut)
async def put_global_settings(
    body: AiGlobalSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiGlobalSettingsOut:
    _require_settings_write(user)
    row = await update_settings(
        db,
        enabled=body.enabled,
        client_id=body.client_id,
        client_secret=body.client_secret,
        clear_secret=body.clear_secret,
        scope=body.scope,
        auth_url=body.auth_url,
        api_base=body.api_base,
        default_model=body.default_model,
        verify_ssl=body.verify_ssl,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        repetition_penalty=body.repetition_penalty,
        max_reply_words=body.max_reply_words,
        require_rag_for_auto=body.require_rag_for_auto,
    )
    await db.commit()
    await db.refresh(row)
    clear_token_cache()
    return AiGlobalSettingsOut.model_validate(settings_public_dict(row))


@router.get("/departments/{department_id}/profile", response_model=AiProfileOut)
async def get_profile(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> AiProfileOut:
    from app.ai.prompts import prompt_for_department_slug
    from app.models import Department

    row = await db.scalar(
        select(AiDepartmentProfile).where(AiDepartmentProfile.department_id == department_id)
    )
    out = _profile_out(row, department_id)
    if not (out.system_prompt or "").strip():
        dept = await db.get(Department, department_id)
        out.system_prompt = prompt_for_department_slug(
            (dept.slug if dept else None) or (dept.name if dept else None)
        )
    return out


@router.put("/departments/{department_id}/profile", response_model=AiProfileOut)
async def upsert_profile(
    department_id: int,
    body: AiProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiProfileOut:
    _require_settings_write(user)
    row = await db.scalar(
        select(AiDepartmentProfile).where(AiDepartmentProfile.department_id == department_id)
    )
    if row is None:
        row = AiDepartmentProfile(department_id=department_id)
        db.add(row)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.mode is not None:
        mode = body.mode.strip().lower()
        if mode not in {m.value for m in AiAgentMode}:
            raise HTTPException(status_code=400, detail="Invalid mode")
        row.mode = mode
    if body.system_prompt is not None:
        row.system_prompt = body.system_prompt
    if body.auto_confidence_min is not None:
        row.auto_confidence_min = body.auto_confidence_min
    if body.max_auto_replies_per_dialog is not None:
        row.max_auto_replies_per_dialog = body.max_auto_replies_per_dialog
    if body.gigachat_model is not None:
        row.gigachat_model = body.gigachat_model.strip() or "GigaChat"
    if body.primary_intents is not None:
        row.primary_intents = body.primary_intents.strip()
    row.updated_at = utcnow()
    await db.commit()
    await db.refresh(row)
    return _profile_out(row, department_id)


@router.get("/dialogs/{dialog_id}/suggestions", response_model=list[AiSuggestionOut])
async def list_dialog_suggestions(
    dialog_id: int,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> list[AiSuggestionOut]:
    stmt = (
        select(AiSuggestion)
        .where(AiSuggestion.dialog_id == dialog_id)
        .order_by(AiSuggestion.created_at.desc())
        .limit(20)
    )
    if status_filter:
        stmt = stmt.where(AiSuggestion.status == status_filter)
    rows = list((await db.execute(stmt)).scalars().all())
    return [AiSuggestionOut.model_validate(r) for r in rows]


@router.post("/suggestions/{suggestion_id}/accept", response_model=AiSuggestionOut)
async def accept_suggestion(
    suggestion_id: int,
    body: AiSuggestionActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> AiSuggestionOut:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    suggestion = await db.get(AiSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != AiSuggestionStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Suggestion already resolved")
    edited = (body.edited_text if body else None) or None
    status_value = (
        AiSuggestionStatus.EDITED.value
        if edited and edited.strip() != suggestion.draft_text.strip()
        else AiSuggestionStatus.ACCEPTED.value
    )
    await resolve_suggestion(
        db,
        suggestion=suggestion,
        status=status_value,
        user_id=user.id,
        edited_text=edited,
    )
    # Learning example is recorded when operator actually sends (chats hook)
    # or here if they only accept into draft — still capture pair for review.
    dialog = await db.get(Dialog, suggestion.dialog_id)
    if dialog is not None:
        fake_out = ChatMessage(
            dialog_id=dialog.id,
            channel_id=dialog.channel_id,
            direction=MessageDirection.OUT.value,
            text=(edited or suggestion.draft_text).strip(),
        )
        await record_from_operator_reply(
            db,
            dialog=dialog,
            outbound=fake_out,
            suggestion=suggestion,
            quality="edited" if status_value == AiSuggestionStatus.EDITED.value else "accepted",
            user_id=user.id,
        )
    await db.commit()
    await db.refresh(suggestion)
    return AiSuggestionOut.model_validate(suggestion)


@router.post("/suggestions/{suggestion_id}/reject", response_model=AiSuggestionOut)
async def reject_suggestion(
    suggestion_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> AiSuggestionOut:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=403, detail="Permission denied")
    suggestion = await db.get(AiSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != AiSuggestionStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Suggestion already resolved")
    await resolve_suggestion(
        db,
        suggestion=suggestion,
        status=AiSuggestionStatus.REJECTED.value,
        user_id=user.id,
    )
    from app.ai.handoff import pause_ai_for_dialog

    await pause_ai_for_dialog(db, suggestion.dialog_id, reason="suggestion_rejected")
    await db.commit()
    await db.refresh(suggestion)
    return AiSuggestionOut.model_validate(suggestion)


@router.get("/departments/{department_id}/learning", response_model=list[AiLearningExampleOut])
async def list_learning(
    department_id: int,
    status_filter: str | None = "pending_review",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[AiLearningExampleOut]:
    stmt = (
        select(AiLearningExample)
        .where(AiLearningExample.department_id == department_id)
        .order_by(AiLearningExample.created_at.desc())
        .limit(100)
    )
    if status_filter:
        stmt = stmt.where(AiLearningExample.status == status_filter)
    rows = list((await db.execute(stmt)).scalars().all())
    return [AiLearningExampleOut.model_validate(r) for r in rows]


@router.post("/learning/{example_id}/review", response_model=AiLearningExampleOut)
async def review_learning(
    example_id: int,
    body: AiLearningReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiLearningExampleOut:
    _require_settings_write(user)
    status_value = body.status.strip().lower()
    if status_value not in {
        AiLearningStatus.APPROVED.value,
        AiLearningStatus.REJECTED.value,
    }:
        raise HTTPException(status_code=400, detail="status must be approved|rejected")
    row = await db.get(AiLearningExample, example_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Example not found")
    row.status = status_value
    row.reviewed_at = utcnow()
    row.reviewed_by_id = user.id
    await db.commit()
    await db.refresh(row)
    return AiLearningExampleOut.model_validate(row)


@router.get("/departments/{department_id}/metrics", response_model=AiMetricsOut)
async def department_metrics(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> AiMetricsOut:
    async def _count_sug(st: str | None = None) -> int:
        stmt = select(func.count()).select_from(AiSuggestion).where(
            AiSuggestion.department_id == department_id
        )
        if st:
            stmt = stmt.where(AiSuggestion.status == st)
        return int(await db.scalar(stmt) or 0)

    async def _count_learn(st: str) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(AiLearningExample)
                .where(
                    AiLearningExample.department_id == department_id,
                    AiLearningExample.status == st,
                )
            )
            or 0
        )

    return AiMetricsOut(
        department_id=department_id,
        suggestions_total=await _count_sug(),
        pending=await _count_sug(AiSuggestionStatus.PENDING.value),
        accepted=await _count_sug(AiSuggestionStatus.ACCEPTED.value),
        edited=await _count_sug(AiSuggestionStatus.EDITED.value),
        rejected=await _count_sug(AiSuggestionStatus.REJECTED.value),
        auto_sent=await _count_sug(AiSuggestionStatus.AUTO_SENT.value),
        learning_pending=await _count_learn(AiLearningStatus.PENDING_REVIEW.value),
        learning_approved=await _count_learn(AiLearningStatus.APPROVED.value),
    )
