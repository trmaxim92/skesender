from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.rbac import load_user_rbac
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
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(subject=user.email, role=user.role)
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
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите имя")
    loaded.name = name
    await db.commit()
    loaded = await load_user_rbac(db, loaded)
    return user_to_out(loaded)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    loaded = await db.get(User, user.id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, loaded.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    new_password = body.new_password.strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий (мин. 6)")
    loaded.password_hash = hash_password(new_password)
    await db.commit()
