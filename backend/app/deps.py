from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import AccessRole, User
from app.security import decode_access_token, token_version_matches

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.access_role).selectinload(AccessRole.permissions),
            selectinload(User.channel_access),
        )
        .where(User.email == payload["sub"])
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not token_version_matches(payload, user.token_version):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    return user
