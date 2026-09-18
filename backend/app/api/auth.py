from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import PresenceStatus, PresenceStatusSlug, User
from app.presence import get_status_by_slug, set_user_presence, should_promote_to_online_on_login
from app.ratelimit import client_ip, limiter
from app.rbac import load_user_rbac
from app.realtime.hub import hub
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeUpdateRequest,
    TokenResponse,
    UserOut,
)
from app.security import create_access_token, hash_password, verify_password
from app.serializers_user import user_to_out

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    ip = client_ip(request)
    email = body.email.lower().strip()
    await limiter.check(f"login:ip:{ip}", limit=20, window_sec=300, detail="Слишком много попыток входа")
    await limiter.check(
        f"login:email:{email}",
        limit=10,
        window_sec=300,
        detail="Слишком много попыток входа для этого email",
    )

    result = await db.execute(
        select(User).options(selectinload(User.presence_status)).where(User.email == email)
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")

    # Offline / unset → Online. Keep custom statuses (training, etc.).
    current_slug = user.presence_status.slug if user.presence_status else None
    if should_promote_to_online_on_login(current_slug):
        online = await get_status_by_slug(db, PresenceStatusSlug.ONLINE.value)
        if online is not None:
            await set_user_presence(db, user, online)
            await db.commit()

    token = create_access_token(
        subject=user.email,
        role=user.role,
        token_version=user.token_version,
    )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    loaded = await load_user_rbac(db, user)
    return user_to_out(loaded)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: MeUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    loaded = await load_user_rbac(db, user)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Укажите имя")
        loaded.name = name
    if body.presence_status_id is not None:
        status_row = await db.get(PresenceStatus, body.presence_status_id)
        if status_row is None or not status_row.is_active:
            raise HTTPException(status_code=400, detail="Статус недоступен")
        await set_user_presence(db, loaded, status_row)
    if body.send_mode is not None:
        loaded.send_mode = body.send_mode
    await db.commit()
    loaded = await load_user_rbac(db, loaded)
    return user_to_out(loaded)


@router.post("/me/password", response_model=TokenResponse)
async def change_my_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Rotate password and return a fresh JWT so this session stays logged in."""
    loaded = await db.get(User, user.id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, loaded.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    new_password = body.new_password.strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий (мин. 6)")
    loaded.password_hash = hash_password(new_password)
    loaded.token_version = int(loaded.token_version or 0) + 1
    await db.commit()
    # Drop other devices' WS; caller replaces the token before reconnecting.
    await hub.disconnect_user(loaded.id)
    token = create_access_token(
        subject=loaded.email,
        role=loaded.role,
        token_version=loaded.token_version,
    )
    return TokenResponse(access_token=token)
