"""Pause AI for a dialog after human handoff until a new dialog is opened."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dialog

logger = logging.getLogger(__name__)


async def pause_ai_for_dialog(
    session: AsyncSession,
    dialog: Dialog | int | None,
    *,
    reason: str,
) -> None:
    """Mark dialog so subsequent inbound messages skip the AI worker pipeline."""
    if dialog is None:
        return
    row = dialog if isinstance(dialog, Dialog) else await session.get(Dialog, int(dialog))
    if row is None:
        return
    if row.ai_paused:
        return
    row.ai_paused = True
    await session.flush()
    logger.info("AI paused for dialog=%s reason=%s", row.id, reason)
