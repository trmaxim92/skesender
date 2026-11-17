"""Helpers for unique (transport, external_id) when reconnecting accounts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelStatus


async def claim_channel_external_id(
    session: AsyncSession,
    *,
    channel: Channel,
    external_id: str,
) -> list[int]:
    """Assign external_id to ``channel``, releasing the same key from siblings.

    Returns ids of displaced channels (caller should stop their workers).
    """
    ext = (external_id or "").strip()
    if not ext:
        channel.external_id = None
        return []

    result = await session.execute(
        select(Channel).where(
            Channel.transport == channel.transport,
            Channel.external_id == ext,
            Channel.id != channel.id,
        )
    )
    displaced: list[int] = []
    for other in result.scalars().all():
        displaced.append(other.id)
        other.external_id = None
        other.credentials_enc = None
        if other.status in {
            ChannelStatus.ONLINE.value,
            ChannelStatus.CONNECTING.value,
            ChannelStatus.QR_PENDING.value,
            ChannelStatus.ERROR.value,
        }:
            other.status = ChannelStatus.OFFLINE.value
            other.last_error = f"Аккаунт переподключён на канал #{channel.id}"
    channel.external_id = ext
    return displaced
