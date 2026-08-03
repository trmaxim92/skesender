from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import OutboundWebhook, User
from app.rbac import ACTION_WRITE, SECTION_WEBHOOKS, require_permission, user_can
from app.schemas import WEBHOOK_EVENT_TYPES, WebhookCreateRequest, WebhookOut, WebhookUpdateRequest

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _require_webhook_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


def _validate_events(events: list[str]) -> list[str]:
    cleaned = []
    for ev in events:
        if ev not in WEBHOOK_EVENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown event: {ev}")
        if ev not in cleaned:
            cleaned.append(ev)
    if not cleaned:
        raise HTTPException(status_code=400, detail="At least one event required")
    return cleaned


def _to_out(row: OutboundWebhook) -> WebhookOut:
    try:
        events = json.loads(row.events_json or "[]")
    except json.JSONDecodeError:
        events = []
    if not isinstance(events, list):
        events = []
    return WebhookOut(
        id=row.id,
        url=row.url,
        events=[str(e) for e in events],
        active=row.active,
        has_secret=bool(row.secret),
        created_at=row.created_at,
    )


@router.get("", response_model=list[WebhookOut])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(SECTION_WEBHOOKS)),
) -> list[WebhookOut]:
    result = await db.execute(select(OutboundWebhook).order_by(OutboundWebhook.id.desc()))
    return [_to_out(row) for row in result.scalars().all()]


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_WEBHOOKS)),
) -> WebhookOut:
    _require_webhook_write(user)
    events = _validate_events(body.events)
    row = OutboundWebhook(
        url=body.url.strip(),
        events_json=json.dumps(events),
        active=True,
        secret=body.secret,
        created_by_id=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.patch("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: int,
    body: WebhookUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_WEBHOOKS)),
) -> WebhookOut:
    _require_webhook_write(user)
    row = await db.get(OutboundWebhook, webhook_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    if body.url is not None:
        row.url = body.url.strip()
    if body.events is not None:
        row.events_json = json.dumps(_validate_events(body.events))
    if body.active is not None:
        row.active = body.active
    if body.secret is not None:
        row.secret = body.secret or None
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_WEBHOOKS)),
) -> None:
    _require_webhook_write(user)
    row = await db.get(OutboundWebhook, webhook_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(row)
    await db.commit()
