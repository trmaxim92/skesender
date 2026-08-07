from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.push import delete_subscription, public_vapid_key, upsert_subscription
from app.rbac import SECTION_CHATS, require_permission

router = APIRouter(prefix="/push", tags=["push"])


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=8)
    auth: str = Field(min_length=8)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2048)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2048)


@router.get("/vapid-public-key")
async def vapid_public_key(
    _user: User = Depends(require_permission(SECTION_CHATS)),
) -> dict[str, str]:
    return {"publicKey": public_vapid_key()}


@router.post("/subscribe")
async def subscribe_push(
    body: PushSubscribeIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> dict[str, bool]:
    await upsert_subscription(
        db,
        user_id=user.id,
        endpoint=body.endpoint.strip(),
        p256dh=body.keys.p256dh.strip(),
        auth=body.keys.auth.strip(),
        user_agent=(user_agent or "")[:512] or None,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/subscribe")
async def unsubscribe_push(
    body: PushUnsubscribeIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_CHATS)),
) -> dict[str, bool]:
    removed = await delete_subscription(db, user_id=user.id, endpoint=body.endpoint.strip())
    await db.commit()
    return {"ok": removed}
