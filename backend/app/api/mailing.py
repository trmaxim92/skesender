from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.mailing.recipients import parse_recipients_text
from app.models import (
    AttachmentKind,
    Channel,
    ChannelStatus,
    MailingCampaign,
    MailingCampaignChannel,
    MailingCampaignStatus,
    MailingRecipient,
    MailingRecipientStatus,
    MailingTemplate,
    User,
    utcnow,
)
from app.rbac import (
    ACTION_WRITE,
    SECTION_MAILING,
    ensure_channel_access,
    require_permission,
    user_can,
)
from app.schemas import (
    MailingCampaignCreateRequest,
    MailingCampaignDetailOut,
    MailingCampaignOut,
    MailingCampaignChannelOut,
    MailingRecipientOut,
    MailingTemplateOut,
)
from app.storage.attachments import absolute_path, guess_kind, save_bytes

router = APIRouter(prefix="/mailing", tags=["mailing"])


def _template_out(t: MailingTemplate) -> MailingTemplateOut:
    return MailingTemplateOut(
        id=t.id,
        name=t.name,
        body=t.body,
        media_kind=t.media_kind,
        media_name=t.media_name,
        mime_type=t.mime_type,
        has_media=bool(t.media_path),
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _campaign_out(c: MailingCampaign) -> MailingCampaignOut:
    channels: list[MailingCampaignChannelOut] = []
    for link in c.channels or []:
        ch = link.channel
        channels.append(
            MailingCampaignChannelOut(
                channel_id=link.channel_id,
                channel_name=ch.name if ch else None,
                transport=ch.transport if ch else None,
                identity=ch.identity if ch else None,
                paused_until=getattr(link, "paused_until", None),
                pause_reason=getattr(link, "pause_reason", None),
            )
        )
    return MailingCampaignOut(
        id=c.id,
        name=c.name,
        template_id=c.template_id,
        template_name=c.template.name if c.template else None,
        status=c.status,
        delay_sec=c.delay_sec,
        max_per_hour=int(getattr(c, "max_per_hour", 30) or 0),
        max_per_day=int(getattr(c, "max_per_day", 150) or 0),
        fail_pause_pct=int(getattr(c, "fail_pause_pct", 40) or 0),
        quiet_start_hour=getattr(c, "quiet_start_hour", None),
        quiet_end_hour=getattr(c, "quiet_end_hour", None),
        write_to_crm=bool(getattr(c, "write_to_crm", True)),
        total=c.total,
        sent=c.sent,
        failed=c.failed,
        channels=channels,
        started_at=c.started_at,
        finished_at=c.finished_at,
        created_at=c.created_at,
    )


def _require_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


@router.get("/templates", response_model=list[MailingTemplateOut])
async def list_mailing_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(SECTION_MAILING)),
) -> list[MailingTemplateOut]:
    result = await db.execute(select(MailingTemplate).order_by(MailingTemplate.id.desc()))
    return [_template_out(t) for t in result.scalars().all()]


@router.post("/templates", response_model=MailingTemplateOut)
async def create_mailing_template(
    name: str = Form(...),
    body: str = Form(""),
    media: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_MAILING)),
) -> MailingTemplateOut:
    _require_write(user)
    name = name.strip()
    body = (body or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название обязательно")
    if not body and media is None:
        raise HTTPException(status_code=400, detail="Нужен текст или медиа")

    template = MailingTemplate(
        name=name,
        body=body,
        created_by_id=user.id,
    )
    db.add(template)
    await db.flush()

    if media is not None and media.filename:
        data = await media.read()
        if data:
            kind = guess_kind(media.content_type, media.filename)
            if kind not in {AttachmentKind.IMAGE, AttachmentKind.VIDEO}:
                raise HTTPException(status_code=400, detail="Медиа: только изображение или видео")
            relative, safe_name, mime, _size = save_bytes(
                data=data,
                file_name=media.filename,
                message_id=None,
                mime_type=media.content_type,
            )
            # store under mailing/ folder name via relative already in attachments
            template.media_kind = kind.value
            template.media_path = relative
            template.media_name = safe_name
            template.mime_type = mime

    await db.commit()
    await db.refresh(template)
    return _template_out(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailing_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_MAILING)),
) -> None:
    _require_write(user)
    template = await db.get(MailingTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    used = (
        await db.execute(
            select(MailingCampaign.id).where(MailingCampaign.template_id == template_id).limit(1)
        )
    ).scalar_one_or_none()
    if used is not None:
        raise HTTPException(status_code=400, detail="Шаблон используется в кампании")
    await db.delete(template)
    await db.commit()


@router.get("/templates/{template_id}/media")
async def mailing_template_media(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(SECTION_MAILING)),
):
    template = await db.get(MailingTemplate, template_id)
    if template is None or not template.media_path:
        raise HTTPException(status_code=404, detail="Медиа не найдено")
    path = absolute_path(template.media_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(
        path,
        media_type=template.mime_type or "application/octet-stream",
        filename=template.media_name or path.name,
    )


@router.get("/campaigns", response_model=list[MailingCampaignOut])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(SECTION_MAILING)),
) -> list[MailingCampaignOut]:
    result = await db.execute(
        select(MailingCampaign)
        .options(
            selectinload(MailingCampaign.template),
            selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
        )
        .order_by(MailingCampaign.id.desc())
    )
    return [_campaign_out(c) for c in result.scalars().all()]


@router.post("/campaigns", response_model=MailingCampaignOut)
async def create_campaign(
    body: MailingCampaignCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_MAILING)),
) -> MailingCampaignOut:
    _require_write(user)
    template = await db.get(MailingTemplate, body.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    for cid in body.channel_ids:
        await ensure_channel_access(user, cid, db)

    channels = list(
        (
            await db.execute(select(Channel).where(Channel.id.in_(body.channel_ids)))
        )
        .scalars()
        .all()
    )
    if len(channels) != len(set(body.channel_ids)):
        raise HTTPException(status_code=400, detail="Один или несколько каналов не найдены")
    offline = [c.name for c in channels if c.status != ChannelStatus.ONLINE.value]
    if offline:
        raise HTTPException(
            status_code=400,
            detail=f"Каналы не online: {', '.join(offline)}",
        )

    parsed = parse_recipients_text(body.recipients_text)
    if not parsed:
        raise HTTPException(status_code=400, detail="Список получателей пуст")

    campaign = MailingCampaign(
        name=body.name.strip(),
        template_id=template.id,
        status=MailingCampaignStatus.DRAFT.value,
        delay_sec=body.delay_sec,
        max_per_hour=body.max_per_hour,
        max_per_day=body.max_per_day,
        fail_pause_pct=body.fail_pause_pct,
        quiet_start_hour=body.quiet_start_hour,
        quiet_end_hour=body.quiet_end_hour,
        write_to_crm=body.write_to_crm,
        total=len(parsed),
        created_by_id=user.id,
    )
    db.add(campaign)
    await db.flush()

    for ch in channels:
        db.add(MailingCampaignChannel(campaign_id=campaign.id, channel_id=ch.id))
    for raw, normalized, kind in parsed:
        db.add(
            MailingRecipient(
                campaign_id=campaign.id,
                raw=raw[:255],
                normalized=normalized[:255],
                kind=kind,
                status=MailingRecipientStatus.PENDING.value,
            )
        )

    await db.commit()
    result = await db.execute(
        select(MailingCampaign)
        .options(
            selectinload(MailingCampaign.template),
            selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
        )
        .where(MailingCampaign.id == campaign.id)
    )
    return _campaign_out(result.scalar_one())


@router.get("/campaigns/{campaign_id}", response_model=MailingCampaignDetailOut)
async def get_campaign(
    campaign_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(SECTION_MAILING)),
) -> MailingCampaignDetailOut:
    campaign = (
        await db.execute(
            select(MailingCampaign)
            .options(
                selectinload(MailingCampaign.template),
                selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
            )
            .where(MailingCampaign.id == campaign_id)
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")

    total_recipients = (
        await db.execute(
            select(func.count()).select_from(MailingRecipient).where(
                MailingRecipient.campaign_id == campaign_id
            )
        )
    ).scalar_one()
    recipients = list(
        (
            await db.execute(
                select(MailingRecipient)
                .where(MailingRecipient.campaign_id == campaign_id)
                .order_by(MailingRecipient.id.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    base = _campaign_out(campaign)
    return MailingCampaignDetailOut(
        **base.model_dump(),
        recipients=[
            MailingRecipientOut(
                id=r.id,
                raw=r.raw,
                normalized=r.normalized,
                kind=r.kind,
                status=r.status,
                channel_id=r.channel_id,
                error=r.error,
                sent_at=r.sent_at,
            )
            for r in recipients
        ],
        recipients_total=int(total_recipients),
    )


@router.post("/campaigns/{campaign_id}/start", response_model=MailingCampaignOut)
async def start_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_MAILING)),
) -> MailingCampaignOut:
    _require_write(user)
    campaign = (
        await db.execute(
            select(MailingCampaign)
            .options(
                selectinload(MailingCampaign.template),
                selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
            )
            .where(MailingCampaign.id == campaign_id)
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if campaign.status not in {
        MailingCampaignStatus.DRAFT.value,
        MailingCampaignStatus.PAUSED.value,
        MailingCampaignStatus.FAILED.value,
    }:
        raise HTTPException(status_code=400, detail=f"Нельзя запустить из статуса {campaign.status}")
    if campaign.total <= 0:
        raise HTTPException(status_code=400, detail="Нет получателей")

    # Закрепляем каждого pending-получателя за одним аккаунтом (без дублей).
    # Resume с паузы не перетирает уже назначенный channel_id.
    channel_ids = [link.channel_id for link in campaign.channels]
    if not channel_ids:
        raise HTTPException(status_code=400, detail="Нет каналов-отправителей")
    # Clear expired channel quarantines on resume.
    now = utcnow()
    for link in campaign.channels:
        if link.paused_until and link.paused_until <= now:
            link.paused_until = None
            link.pause_reason = None
    pending = list(
        (
            await db.execute(
                select(MailingRecipient)
                .where(
                    MailingRecipient.campaign_id == campaign_id,
                    MailingRecipient.status == MailingRecipientStatus.PENDING.value,
                )
                .order_by(MailingRecipient.id.asc())
            )
        )
        .scalars()
        .all()
    )
    unassigned = [r for r in pending if r.channel_id is None or r.channel_id not in channel_ids]
    for idx, recipient in enumerate(unassigned):
        recipient.channel_id = channel_ids[idx % len(channel_ids)]
        recipient.next_attempt_at = None

    campaign.status = MailingCampaignStatus.RUNNING.value
    campaign.started_at = campaign.started_at or utcnow()
    campaign.finished_at = None
    await db.commit()
    await db.refresh(campaign)
    result = await db.execute(
        select(MailingCampaign)
        .options(
            selectinload(MailingCampaign.template),
            selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
        )
        .where(MailingCampaign.id == campaign_id)
    )
    return _campaign_out(result.scalar_one())


@router.post("/campaigns/{campaign_id}/pause", response_model=MailingCampaignOut)
async def pause_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_MAILING)),
) -> MailingCampaignOut:
    _require_write(user)
    campaign = (
        await db.execute(
            select(MailingCampaign)
            .options(
                selectinload(MailingCampaign.template),
                selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
            )
            .where(MailingCampaign.id == campaign_id)
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if campaign.status != MailingCampaignStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Кампания не запущена")
    campaign.status = MailingCampaignStatus.PAUSED.value
    await db.commit()
    result = await db.execute(
        select(MailingCampaign)
        .options(
            selectinload(MailingCampaign.template),
            selectinload(MailingCampaign.channels).selectinload(MailingCampaignChannel.channel),
        )
        .where(MailingCampaign.id == campaign_id)
    )
    return _campaign_out(result.scalar_one())
