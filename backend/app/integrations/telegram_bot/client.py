from __future__ import annotations

import json
from typing import Any

import httpx

from app.integrations.base import IntegrationError
from app.integrations.telegram_proxy import httpx_proxy

TELEGRAM_API_BASE = "https://api.telegram.org"


def _http_client(timeout: float, *, follow_redirects: bool = False) -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": follow_redirects}
    proxy = httpx_proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


class TelegramApiError(IntegrationError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _base_url(token: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{token.strip()}"


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


async def _call(
    token: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    url = f"{_base_url(token)}/{method}"
    try:
        async with _http_client(timeout) as client:
            if files is not None:
                response = await client.post(url, data=params or {}, files=files)
            elif json_body is not None:
                response = await client.post(url, json=json_body)
            else:
                response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise TelegramApiError(f"Telegram API {method} connection error: {exc}") from exc

    payload = _safe_json(response)
    if response.status_code >= 400:
        description = payload.get("description") if isinstance(payload, dict) else None
        raise TelegramApiError(
            description or f"Telegram API {method} failed: {response.status_code}",
            status_code=response.status_code,
            payload=payload,
        )
    if not isinstance(payload, dict) or not payload.get("ok"):
        description = payload.get("description") if isinstance(payload, dict) else None
        raise TelegramApiError(
            description or f"Telegram API {method} returned not ok",
            status_code=response.status_code,
            payload=payload,
        )
    result = payload.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"_list": result}
    return {"result": result}


async def get_me(token: str) -> dict[str, Any]:
    return await _call(token, "getMe")


async def get_chat(token: str, chat_id: int | str) -> dict[str, Any]:
    return await _call(token, "getChat", json_body={"chat_id": chat_id})


async def get_updates(
    token: str,
    *,
    offset: int | None = None,
    timeout: int = 25,
    limit: int = 100,
    allowed_updates: list[str] | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": timeout, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    if allowed_updates:
        # Telegram accepts JSON-serialized array in query for getUpdates
        params["allowed_updates"] = json.dumps(allowed_updates)
    payload = await _call(token, "getUpdates", params=params, timeout=float(timeout + 15))
    items = payload.get("_list")
    if isinstance(items, list):
        return [u for u in items if isinstance(u, dict)]
    return []


async def send_message(
    token: str,
    *,
    chat_id: int | str,
    text: str,
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_to_message_id is not None:
        body["reply_to_message_id"] = reply_to_message_id
    return await _call(token, "sendMessage", json_body=body, timeout=60.0)


async def send_photo(
    token: str,
    *,
    chat_id: int | str,
    data: bytes,
    filename: str,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    form: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        form["caption"] = caption
    if reply_to_message_id is not None:
        form["reply_to_message_id"] = str(reply_to_message_id)
    files = {"photo": (filename, data)}
    return await _call(token, "sendPhoto", params=form, files=files, timeout=120.0)


async def send_document(
    token: str,
    *,
    chat_id: int | str,
    data: bytes,
    filename: str,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    mime_type: str | None = None,
) -> dict[str, Any]:
    form: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        form["caption"] = caption
    if reply_to_message_id is not None:
        form["reply_to_message_id"] = str(reply_to_message_id)
    files = {"document": (filename, data, mime_type or "application/octet-stream")}
    return await _call(token, "sendDocument", params=form, files=files, timeout=120.0)


async def send_video(
    token: str,
    *,
    chat_id: int | str,
    data: bytes,
    filename: str,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    mime_type: str | None = None,
) -> dict[str, Any]:
    form: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        form["caption"] = caption
    if reply_to_message_id is not None:
        form["reply_to_message_id"] = str(reply_to_message_id)
    files = {"video": (filename, data, mime_type or "video/mp4")}
    return await _call(token, "sendVideo", params=form, files=files, timeout=120.0)


async def send_audio(
    token: str,
    *,
    chat_id: int | str,
    data: bytes,
    filename: str,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    mime_type: str | None = None,
) -> dict[str, Any]:
    form: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        form["caption"] = caption
    if reply_to_message_id is not None:
        form["reply_to_message_id"] = str(reply_to_message_id)
    files = {"audio": (filename, data, mime_type or "audio/mpeg")}
    return await _call(token, "sendAudio", params=form, files=files, timeout=120.0)


async def edit_message_text(
    token: str,
    *,
    chat_id: int | str,
    message_id: int,
    text: str,
) -> dict[str, Any]:
    return await _call(
        token,
        "editMessageText",
        json_body={"chat_id": chat_id, "message_id": message_id, "text": text},
        timeout=60.0,
    )


async def delete_message(
    token: str,
    *,
    chat_id: int | str,
    message_id: int,
) -> dict[str, Any]:
    return await _call(
        token,
        "deleteMessage",
        json_body={"chat_id": chat_id, "message_id": message_id},
        timeout=30.0,
    )


async def get_file(token: str, file_id: str) -> dict[str, Any]:
    return await _call(token, "getFile", params={"file_id": file_id})


async def download_file(token: str, file_path: str) -> bytes:
    url = f"{TELEGRAM_API_BASE}/file/bot{token.strip()}/{file_path.lstrip('/')}"
    try:
        async with _http_client(60.0, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise TelegramApiError(f"Telegram file download error: {exc}") from exc
    if response.status_code >= 400:
        raise TelegramApiError(f"Telegram file download failed: {response.status_code}")
    return response.content
