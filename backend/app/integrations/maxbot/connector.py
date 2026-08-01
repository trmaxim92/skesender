from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.maxbot.client import MaxApiError, get_me
from app.models import Channel, ChannelStatus, ChannelTransport, utcnow
from app.security import encrypt_secret


async def connect_by_token(
    session: AsyncSession,
    *,
    token: str,
    created_by_id: int | None,
    name: str | None = None,
) -> tuple[Channel, dict[str, Any]]:
    bot_info = await get_me(token.strip())
    external_id = str(bot_info.get("user_id") or "")
    username = bot_info.get("username")
    bot_name = name or bot_info.get("first_name") or bot_info.get("name") or "MAX бот"
    identity = f"@{username}" if username else bot_name

    result = await session.execute(
        select(Channel).where(
            Channel.transport == ChannelTransport.MAXBOT.value,
            Channel.external_id == external_id,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        channel = Channel(
            name=bot_name,
            transport=ChannelTransport.MAXBOT.value,
            created_by_id=created_by_id,
        )
        session.add(channel)

    channel.name = bot_name
    channel.status = ChannelStatus.ONLINE.value
    channel.identity = identity
    channel.external_id = external_id or None
    channel.credentials_enc = encrypt_secret(token.strip())
    channel.meta_json = json.dumps({"bot": bot_info}, ensure_ascii=False)
    channel.last_error = None
    channel.connected_at = utcnow()
    await session.flush()
    return channel, bot_info


async def upsert_seed_channel(
    session: AsyncSession,
    *,
    token: str,
    created_by_id: int | None,
) -> Channel:
    """Seed helper: save token even if /me fails."""
    bot_info: dict[str, Any] | None = None
    status = ChannelStatus.ONLINE.value
    identity = "max bot"
    external_id: str | None = None
    last_error: str | None = None

    try:
        bot_info = await get_me(token)
        external_id = str(bot_info.get("user_id") or bot_info.get("userId") or "") or None
        username = bot_info.get("username")
        name = bot_info.get("first_name") or bot_info.get("name") or "MAX бот"
        identity = f"@{username}" if username else name
    except MaxApiError as exc:
        status = ChannelStatus.ERROR.value
        last_error = str(exc)

    existing = await session.execute(
        select(Channel).where(Channel.transport == ChannelTransport.MAXBOT.value)
    )
    channel = existing.scalars().first()
    creds = encrypt_secret(token)
    meta = json.dumps({"bot": bot_info}, ensure_ascii=False) if bot_info else None

    if channel is None:
        channel = Channel(
            name="MAX бот",
            transport=ChannelTransport.MAXBOT.value,
            status=status,
            identity=identity,
            external_id=external_id,
            credentials_enc=creds,
            meta_json=meta,
            last_error=last_error,
            created_by_id=created_by_id,
            connected_at=utcnow() if status == ChannelStatus.ONLINE.value else None,
        )
        session.add(channel)
    else:
        channel.credentials_enc = creds
        channel.status = status
        channel.identity = identity
        channel.external_id = external_id or channel.external_id
        channel.meta_json = meta
        channel.last_error = last_error
        if status == ChannelStatus.ONLINE.value:
            channel.connected_at = channel.connected_at or utcnow()

    await session.flush()
    return channel
