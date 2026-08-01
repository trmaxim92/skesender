from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.telegram_bot.client import get_me
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
    external_id = str(bot_info.get("id") or "")
    username = bot_info.get("username")
    bot_name = name or bot_info.get("first_name") or "Telegram бот"
    identity = f"@{username}" if username else bot_name

    result = await session.execute(
        select(Channel).where(
            Channel.transport == ChannelTransport.TELEGRAM.value,
            Channel.external_id == external_id,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        channel = Channel(
            name=bot_name,
            transport=ChannelTransport.TELEGRAM.value,
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
