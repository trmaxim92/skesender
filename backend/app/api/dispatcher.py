from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.dispatcher.engine import SUPPORTED_TRIGGERS
from app.models import DispatcherRule, DispatcherRuleGroup, User
from app.rbac import ACTION_WRITE, SECTION_SETTINGS, require_permission, user_can
from app.schemas import (
    DispatcherActionIn,
    DispatcherConditionIn,
    DispatcherRuleGroupIn,
    DispatcherRuleGroupOut,
    DispatcherRuleIn,
    DispatcherRuleOut,
)

router = APIRouter(prefix="/dispatcher", tags=["dispatcher"])


def _require_write(user: User) -> None:
    if not user_can(user, ACTION_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет прав на изменение")


def _group_out(g: DispatcherRuleGroup, rules_count: int | None = None) -> DispatcherRuleGroupOut:
    count = rules_count if rules_count is not None else len(g.rules or [])
    return DispatcherRuleGroupOut(
        id=g.id,
        name=g.name,
        active=g.active,
        sort_order=g.sort_order,
        rules_count=count,
        created_at=g.created_at,
        updated_at=g.updated_at,
    )


def _rule_out(r: DispatcherRule) -> DispatcherRuleOut:
    try:
        conditions_raw = json.loads(r.conditions_json or "[]")
    except json.JSONDecodeError:
        conditions_raw = []
    try:
        actions_raw = json.loads(r.actions_json or "[]")
    except json.JSONDecodeError:
        actions_raw = []
    conditions = [
        DispatcherConditionIn.model_validate(c)
        for c in conditions_raw
        if isinstance(c, dict)
    ]
    actions = [
        DispatcherActionIn.model_validate(a) for a in actions_raw if isinstance(a, dict)
    ]
    return DispatcherRuleOut(
        id=r.id,
        group_id=r.group_id,
        name=r.name,
        description=r.description or "",
        active=r.active,
        sort_order=r.sort_order,
        trigger=r.trigger,
        conditions=conditions,
        actions=actions,
        last_applied_at=r.last_applied_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _dump_conditions(items: list[DispatcherConditionIn]) -> str:
    return json.dumps([c.model_dump() for c in items], ensure_ascii=False)


def _dump_actions(items: list[DispatcherActionIn]) -> str:
    return json.dumps([a.model_dump() for a in items], ensure_ascii=False)


async def _ensure_default_group(db: AsyncSession) -> None:
    existing = await db.scalar(select(func.count()).select_from(DispatcherRuleGroup))
    if existing and int(existing) > 0:
        return
    db.add(
        DispatcherRuleGroup(
            name="Основные правила",
            active=True,
            sort_order=0,
        )
    )
    await db.commit()


@router.get("/groups", response_model=list[DispatcherRuleGroupOut])
async def list_groups(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[DispatcherRuleGroupOut]:
    await _ensure_default_group(db)
    result = await db.execute(
        select(DispatcherRuleGroup)
        .options(selectinload(DispatcherRuleGroup.rules))
        .order_by(DispatcherRuleGroup.sort_order, DispatcherRuleGroup.id)
    )
    groups = list(result.scalars().unique().all())
    return [_group_out(g) for g in groups]


@router.post("/groups", response_model=DispatcherRuleGroupOut, status_code=201)
async def create_group(
    body: DispatcherRuleGroupIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> DispatcherRuleGroupOut:
    _require_write(user)
    g = DispatcherRuleGroup(
        name=body.name.strip(),
        active=body.active,
        sort_order=body.sort_order,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return _group_out(g, rules_count=0)


@router.patch("/groups/{group_id}", response_model=DispatcherRuleGroupOut)
async def update_group(
    group_id: int,
    body: DispatcherRuleGroupIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> DispatcherRuleGroupOut:
    _require_write(user)
    g = await db.get(
        DispatcherRuleGroup,
        group_id,
        options=(selectinload(DispatcherRuleGroup.rules),),
    )
    if g is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    g.name = body.name.strip()
    g.active = body.active
    g.sort_order = body.sort_order
    await db.commit()
    await db.refresh(g)
    return _group_out(g)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> None:
    _require_write(user)
    g = await db.get(DispatcherRuleGroup, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    count = await db.scalar(select(func.count()).select_from(DispatcherRuleGroup))
    if count is not None and int(count) <= 1:
        raise HTTPException(status_code=400, detail="Нельзя удалить последнюю группу")
    await db.delete(g)
    await db.commit()


@router.get("/rules", response_model=list[DispatcherRuleOut])
async def list_rules(
    group_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> list[DispatcherRuleOut]:
    await _ensure_default_group(db)
    stmt = select(DispatcherRule).order_by(DispatcherRule.sort_order, DispatcherRule.id)
    if group_id is not None:
        stmt = stmt.where(DispatcherRule.group_id == group_id)
    result = await db.execute(stmt)
    return [_rule_out(r) for r in result.scalars().all()]


@router.get("/rules/{rule_id}", response_model=DispatcherRuleOut)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> DispatcherRuleOut:
    r = await db.get(DispatcherRule, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    return _rule_out(r)


@router.post("/rules", response_model=DispatcherRuleOut, status_code=201)
async def create_rule(
    body: DispatcherRuleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> DispatcherRuleOut:
    _require_write(user)
    if body.trigger not in SUPPORTED_TRIGGERS:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый триггер: {body.trigger}")
    group = await db.get(DispatcherRuleGroup, body.group_id)
    if group is None:
        raise HTTPException(status_code=400, detail="Группа не найдена")
    if not body.actions:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы одно действие")
    r = DispatcherRule(
        group_id=body.group_id,
        name=body.name.strip(),
        description=(body.description or "").strip(),
        active=body.active,
        sort_order=body.sort_order,
        trigger=body.trigger,
        conditions_json=_dump_conditions(body.conditions),
        actions_json=_dump_actions(body.actions),
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return _rule_out(r)


@router.patch("/rules/{rule_id}", response_model=DispatcherRuleOut)
async def update_rule(
    rule_id: int,
    body: DispatcherRuleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> DispatcherRuleOut:
    _require_write(user)
    r = await db.get(DispatcherRule, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    if body.trigger not in SUPPORTED_TRIGGERS:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый триггер: {body.trigger}")
    group = await db.get(DispatcherRuleGroup, body.group_id)
    if group is None:
        raise HTTPException(status_code=400, detail="Группа не найдена")
    if not body.actions:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы одно действие")
    r.group_id = body.group_id
    r.name = body.name.strip()
    r.description = (body.description or "").strip()
    r.active = body.active
    r.sort_order = body.sort_order
    r.trigger = body.trigger
    r.conditions_json = _dump_conditions(body.conditions)
    r.actions_json = _dump_actions(body.actions)
    await db.commit()
    await db.refresh(r)
    return _rule_out(r)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(SECTION_SETTINGS)),
) -> None:
    _require_write(user)
    r = await db.get(DispatcherRule, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    await db.delete(r)
    await db.commit()
