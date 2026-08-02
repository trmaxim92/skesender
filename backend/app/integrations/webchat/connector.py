from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelStatus, ChannelTransport, utcnow
from app.security import encrypt_secret


def new_public_key() -> str:
    return f"wc_{secrets.token_urlsafe(18)}"


def new_channel_secret() -> str:
    return secrets.token_urlsafe(32)


async def connect_webchat(
    session: AsyncSession,
    *,
    created_by_id: int | None,
    name: str | None = None,
    allowed_origins: list[str] | None = None,
) -> tuple[Channel, dict[str, Any]]:
    public_key = new_public_key()
    secret = new_channel_secret()
    origins = [o.strip() for o in (allowed_origins or []) if o and o.strip()]
    channel_name = (name or "").strip() or "Виджет на сайт"

    channel = Channel(
        name=channel_name,
        transport=ChannelTransport.WEBCHAT.value,
        created_by_id=created_by_id,
    )
    session.add(channel)

    channel.status = ChannelStatus.ONLINE.value
    channel.identity = "Виджет сайта"
    channel.external_id = public_key
    channel.credentials_enc = encrypt_secret(secret)
    channel.meta_json = json.dumps(
        {
            "public_key": public_key,
            "allowed_origins": origins,
        },
        ensure_ascii=False,
    )
    channel.last_error = None
    channel.connected_at = utcnow()
    await session.flush()

    info = {
        "public_key": public_key,
        "allowed_origins": origins,
    }
    return channel, info
