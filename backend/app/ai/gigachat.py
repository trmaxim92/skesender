"""GigaChat OAuth + chat completions client (credentials from AI module settings)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from app.ai.settings_store import AiRuntimeConfig, load_runtime_config

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {
    "access_token": None,
    "expires_at": 0.0,
    "fingerprint": None,
}


class GigaChatError(RuntimeError):
    pass


def clear_token_cache() -> None:
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0.0
    _token_cache["fingerprint"] = None


def _fingerprint(cfg: AiRuntimeConfig) -> str:
    return f"{cfg.client_id}|{cfg.scope}|{cfg.auth_url}|{bool(cfg.client_secret)}"


async def get_runtime() -> AiRuntimeConfig:
    return await load_runtime_config()


async def gigachat_configured() -> bool:
    cfg = await load_runtime_config()
    return cfg.configured


async def _fetch_token(client: httpx.AsyncClient, cfg: AiRuntimeConfig) -> str:
    now = time.time()
    fp = _fingerprint(cfg)
    cached = _token_cache.get("access_token")
    expires_at = float(_token_cache.get("expires_at") or 0)
    if cached and _token_cache.get("fingerprint") == fp and expires_at > now + 60:
        return str(cached)

    auth = (cfg.client_id, cfg.client_secret)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
    }
    data = {"scope": cfg.scope or "GIGACHAT_API_PERS"}
    response = await client.post(
        cfg.auth_url,
        data=data,
        headers=headers,
        auth=auth,
    )
    if response.status_code >= 400:
        raise GigaChatError(f"GigaChat OAuth failed: {response.status_code} {response.text[:300]}")
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise GigaChatError("GigaChat OAuth response missing access_token")
    expires_raw = payload.get("expires_at") or payload.get("expires_in") or 1800
    try:
        expires_val = float(expires_raw)
    except (TypeError, ValueError):
        expires_val = 1800.0
    if expires_val > 1e12:
        expires_at = expires_val / 1000.0
    elif expires_val > 1e10:
        expires_at = expires_val
    else:
        expires_at = now + expires_val
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = expires_at
    _token_cache["fingerprint"] = fp
    return str(token)


async def chat_completion(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    repetition_penalty: float | None = None,
    cfg: AiRuntimeConfig | None = None,
) -> str:
    runtime = cfg or await load_runtime_config()
    if not runtime.configured:
        raise GigaChatError("GigaChat credentials are not configured in AI settings")

    async with httpx.AsyncClient(timeout=60.0, verify=runtime.verify_ssl) as client:
        token = await _fetch_token(client, runtime)
        body = {
            "model": (model or runtime.default_model or "GigaChat").strip(),
            "messages": messages,
            "temperature": float(
                runtime.temperature if temperature is None else temperature
            ),
            "max_tokens": int(runtime.max_tokens if max_tokens is None else max_tokens),
            "repetition_penalty": float(
                runtime.repetition_penalty
                if repetition_penalty is None
                else repetition_penalty
            ),
        }
        response = await client.post(
            f"{runtime.api_base.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
        )
        if response.status_code >= 400:
            raise GigaChatError(
                f"GigaChat chat failed: {response.status_code} {response.text[:400]}"
            )
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise GigaChatError("GigaChat returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GigaChatError("GigaChat returned empty content")
        return content.strip()


async def ping() -> dict[str, Any]:
    """Lightweight connectivity check for settings UI."""
    runtime = await load_runtime_config()
    if not runtime.configured:
        return {"ok": False, "detail": "Укажите Client ID и Secret в настройках ИИ"}
    if not runtime.enabled:
        return {"ok": False, "detail": "Модуль ИИ выключен (включите в настройках)"}
    try:
        text = await chat_completion(
            messages=[
                {"role": "system", "content": "Ответь одним словом: ok"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=16,
            temperature=0,
            cfg=runtime,
        )
        return {"ok": True, "detail": text[:120]}
    except Exception as exc:
        logger.warning("GigaChat ping failed: %s", exc)
        return {"ok": False, "detail": str(exc)[:300]}
