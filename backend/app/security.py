from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def _fernet() -> Fernet:
    """Derive a stable Fernet key from SECRET_KEY."""
    import base64
    import hashlib

    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(
    subject: str,
    role: str,
    *,
    token_version: int = 0,
    expires_minutes: int | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "role": role, "ver": int(token_version), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None


def token_version_matches(payload: dict, user_token_version: int) -> bool:
    """Reject JWTs issued before password change / forced logout."""
    try:
        claim = int(payload.get("ver", 0))
    except (TypeError, ValueError):
        claim = 0
    return claim == int(user_token_version or 0)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt secret with current SECRET_KEY") from exc
