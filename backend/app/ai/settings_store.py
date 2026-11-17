"""Load / save install-wide AI settings from DB (UI module, not .env)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import AiGlobalSettings, utcnow
from app.security import decrypt_secret, encrypt_secret

GLOBAL_SETTINGS_ID = 1


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@dataclass
class AiRuntimeConfig:
    enabled: bool
    client_id: str
    client_secret: str
    scope: str
    auth_url: str
    api_base: str
    default_model: str
    verify_ssl: bool
    temperature: float
    max_tokens: int
    repetition_penalty: float
    max_reply_words: int
    require_rag_for_auto: bool

    @property
    def configured(self) -> bool:
        # Secret may be raw Client Secret or ready Sber Authorization key (base64).
        secret = self.client_secret.strip()
        if not secret:
            return False
        if self.client_id.strip():
            return True
        # Authorization key alone is enough for OAuth.
        return len(secret) >= 40


def _row_to_runtime(row: AiGlobalSettings) -> AiRuntimeConfig:
    secret = ""
    if row.client_secret_enc:
        try:
            secret = decrypt_secret(row.client_secret_enc)
        except Exception:
            secret = ""
    return AiRuntimeConfig(
        enabled=bool(row.enabled),
        client_id=(row.client_id or "").strip(),
        client_secret=secret.strip(),
        scope=(row.scope or "GIGACHAT_API_PERS").strip(),
        auth_url=(
            row.auth_url or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        ).strip(),
        api_base=(row.api_base or "https://gigachat.devices.sberbank.ru/api/v1").strip(),
        default_model=(row.default_model or "GigaChat").strip(),
        verify_ssl=bool(row.verify_ssl),
        temperature=_as_float(getattr(row, "temperature", None), 0.3),
        max_tokens=max(16, min(_as_int(getattr(row, "max_tokens", None), 512), 4096)),
        repetition_penalty=_as_float(getattr(row, "repetition_penalty", None), 1.0),
        max_reply_words=max(20, min(_as_int(getattr(row, "max_reply_words", None), 80), 300)),
        require_rag_for_auto=bool(getattr(row, "require_rag_for_auto", True)),
    )


async def get_or_create_settings(session: AsyncSession) -> AiGlobalSettings:
    row = await session.get(AiGlobalSettings, GLOBAL_SETTINGS_ID)
    if row is None:
        row = AiGlobalSettings(id=GLOBAL_SETTINGS_ID)
        session.add(row)
        await session.flush()
    return row


async def load_runtime_config(session: AsyncSession | None = None) -> AiRuntimeConfig:
    if session is not None:
        row = await get_or_create_settings(session)
        return _row_to_runtime(row)
    async with SessionLocal() as db:
        row = await get_or_create_settings(db)
        await db.commit()
        return _row_to_runtime(row)


def settings_public_dict(row: AiGlobalSettings) -> dict:
    has_secret = bool(row.client_secret_enc)
    return {
        "enabled": bool(row.enabled),
        "client_id": row.client_id or "",
        "client_secret_set": has_secret,
        "scope": row.scope or "GIGACHAT_API_PERS",
        "auth_url": row.auth_url
        or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        "api_base": row.api_base or "https://gigachat.devices.sberbank.ru/api/v1",
        "default_model": row.default_model or "GigaChat",
        "verify_ssl": bool(row.verify_ssl),
        "temperature": _as_float(getattr(row, "temperature", None), 0.3),
        "max_tokens": _as_int(getattr(row, "max_tokens", None), 512),
        "repetition_penalty": _as_float(getattr(row, "repetition_penalty", None), 1.0),
        "max_reply_words": _as_int(getattr(row, "max_reply_words", None), 80),
        "require_rag_for_auto": bool(getattr(row, "require_rag_for_auto", True)),
        "updated_at": row.updated_at,
    }


async def update_settings(
    session: AsyncSession,
    *,
    enabled: bool | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    clear_secret: bool = False,
    scope: str | None = None,
    auth_url: str | None = None,
    api_base: str | None = None,
    default_model: str | None = None,
    verify_ssl: bool | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    repetition_penalty: float | None = None,
    max_reply_words: int | None = None,
    require_rag_for_auto: bool | None = None,
) -> AiGlobalSettings:
    row = await get_or_create_settings(session)
    if enabled is not None:
        row.enabled = enabled
    if client_id is not None:
        row.client_id = client_id.strip()
    if clear_secret:
        row.client_secret_enc = None
    elif client_secret is not None and client_secret.strip():
        row.client_secret_enc = encrypt_secret(client_secret.strip())
    if scope is not None:
        row.scope = scope.strip() or "GIGACHAT_API_PERS"
    if auth_url is not None:
        row.auth_url = auth_url.strip() or row.auth_url
    if api_base is not None:
        row.api_base = api_base.strip() or row.api_base
    if default_model is not None:
        row.default_model = default_model.strip() or "GigaChat"
    if verify_ssl is not None:
        row.verify_ssl = verify_ssl
    if temperature is not None:
        row.temperature = str(max(0.0, min(float(temperature), 2.0)))
    if max_tokens is not None:
        row.max_tokens = max(16, min(int(max_tokens), 4096))
    if repetition_penalty is not None:
        row.repetition_penalty = str(max(0.1, min(float(repetition_penalty), 2.0)))
    if max_reply_words is not None:
        row.max_reply_words = max(20, min(int(max_reply_words), 300))
    if require_rag_for_auto is not None:
        row.require_rag_for_auto = require_rag_for_auto
    row.updated_at = utcnow()
    await session.flush()
    return row
