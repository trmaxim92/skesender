"""Mailing pacing helpers: jitter, quiet hours, per-channel caps."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MailingCampaign, MailingRecipient, MailingRecipientStatus


def jittered_delay(delay_sec: int, *, lo: float = 0.7, hi: float = 1.4) -> float:
    base = max(1, int(delay_sec or 5))
    return max(1.0, base * random.uniform(lo, hi))


def in_quiet_hours(
    now: datetime,
    quiet_start_hour: int | None,
    quiet_end_hour: int | None,
) -> bool:
    if quiet_start_hour is None or quiet_end_hour is None:
        return False
    start = int(quiet_start_hour) % 24
    end = int(quiet_end_hour) % 24
    hour = now.astimezone(timezone.utc).hour if now.tzinfo else now.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def channel_sent_count(
    session: AsyncSession,
    channel_id: int,
    *,
    since: datetime,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(MailingRecipient)
        .where(
            MailingRecipient.channel_id == channel_id,
            MailingRecipient.status == MailingRecipientStatus.SENT.value,
            MailingRecipient.sent_at.is_not(None),
            MailingRecipient.sent_at >= since,
        )
    )
    return int(result.scalar_one() or 0)


async def channel_under_caps(
    session: AsyncSession,
    channel_id: int,
    campaign: MailingCampaign,
    *,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    """Return (ok, reason_if_blocked). Caps are per channel across all campaigns."""
    now = now or datetime.now(timezone.utc)
    max_hour = int(getattr(campaign, "max_per_hour", 0) or 0)
    max_day = int(getattr(campaign, "max_per_day", 0) or 0)
    if max_hour > 0:
        hour_count = await channel_sent_count(session, channel_id, since=now - timedelta(hours=1))
        if hour_count >= max_hour:
            return False, f"Лимит {max_hour}/час на аккаунт"
    if max_day > 0:
        day_count = await channel_sent_count(session, channel_id, since=now - timedelta(days=1))
        if day_count >= max_day:
            return False, f"Лимит {max_day}/сутки на аккаунт"
    return True, None


def fail_rate_should_pause(sent: int, failed: int, pause_pct: int, *, min_samples: int = 10) -> bool:
    pct = max(0, min(100, int(pause_pct or 0)))
    if pct <= 0:
        return False
    total = int(sent or 0) + int(failed or 0)
    if total < min_samples:
        return False
    return (failed / total) * 100.0 >= pct
