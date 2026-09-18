from typing import Any

import asyncio
import httpx

from app.config import get_settings
from app.integrations.base import IntegrationError


class MaxApiError(IntegrationError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _client(timeout: float = 20.0) -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.max_api_base,
        timeout=timeout,
        verify=settings.max_api_verify_ssl,
    )


async def get_me(token: str) -> dict[str, Any]:
    try:
        async with _client() as client:
            response = await client.get("/me", headers={"Authorization": token})
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API connection error: {exc}") from exc

    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API /me failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    return response.json()


async def get_updates(
    token: str,
    *,
    marker: int | None = None,
    timeout: int = 30,
    limit: int = 100,
    types: list[str] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"timeout": timeout, "limit": limit}
    if marker is not None:
        params["marker"] = marker
    if types:
        params["types"] = ",".join(types)

    try:
        async with _client(timeout=float(timeout + 15)) as client:
            response = await client.get("/updates", headers={"Authorization": token}, params=params)
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API /updates error: {exc}") from exc

    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API /updates failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    return response.json()


async def get_subscriptions(token: str) -> list[dict[str, Any]]:
    """List active Max webhook subscriptions (blocks long-poll while present)."""
    try:
        async with _client() as client:
            response = await client.get("/subscriptions", headers={"Authorization": token})
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API /subscriptions error: {exc}") from exc

    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API /subscriptions failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    data = response.json()
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        subs = data.get("subscriptions") or []
        return [item for item in subs if isinstance(item, dict)]
    return []


async def delete_subscription(token: str, url: str) -> dict[str, Any]:
    try:
        async with _client() as client:
            response = await client.delete(
                "/subscriptions",
                headers={"Authorization": token},
                params={"url": url},
            )
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API DELETE /subscriptions error: {exc}") from exc

    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API DELETE /subscriptions failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    if not response.content:
        return {"success": True}
    payload = _safe_json(response)
    return payload if isinstance(payload, dict) else {"raw": payload}


async def clear_subscriptions(token: str) -> list[str]:
    """Remove all webhook subscriptions so GET /updates (long-poll) works again."""
    cleared: list[str] = []
    for sub in await get_subscriptions(token):
        url = sub.get("url")
        if not url:
            continue
        await delete_subscription(token, str(url))
        cleared.append(str(url))
    return cleared


async def create_upload(token: str, upload_type: str) -> dict[str, Any]:
    try:
        async with _client() as client:
            response = await client.post(
                "/uploads",
                headers={"Authorization": token},
                params={"type": upload_type},
            )
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API /uploads error: {exc}") from exc

    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API /uploads failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    return response.json()


def _extract_upload_token(created: dict[str, Any], uploaded: dict[str, Any]) -> str | None:
    """Token may come from create step (video/audio), body, nested payload, or photos map."""
    for source in (uploaded, created):
        token = source.get("token")
        if token:
            return str(token)
        nested = source.get("payload")
        if isinstance(nested, dict) and nested.get("token"):
            return str(nested["token"])
    photos = uploaded.get("photos")
    if isinstance(photos, dict):
        for photo in photos.values():
            if isinstance(photo, dict) and photo.get("token"):
                return str(photo["token"])
    return None


async def upload_file_bytes(
    upload_url: str,
    *,
    data: bytes,
    filename: str,
    content_type: str | None = None,
) -> dict[str, Any]:
    """POST multipart to the CDN upload URL.

    Do not send the bot Authorization header — the URL already carries apiToken/photoIds.
    """
    mime = content_type or "application/octet-stream"
    files = {"data": (filename or "file", data, mime)}
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=120.0, verify=settings.max_api_verify_ssl) as client:
            response = await client.post(upload_url, files=files)
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX upload error: {exc}") from exc

    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX upload failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    if not response.content:
        return {}
    try:
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    except Exception:
        # video/audio often return tiny non-JSON bodies (e.g. retval); caller uses early token
        text = (response.text or "").strip()
        return {"raw": text} if text else {}


async def upload_attachment_payload(
    token: str,
    *,
    upload_type: str,
    data: bytes,
    filename: str,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Two-step Max upload → attachment payload for POST /messages.

    Images preferably use ``{"photos": {...}}``; other types use ``{"token": "..."}``.
    """
    created = await create_upload(token, upload_type)
    upload_url = created.get("url")
    if not upload_url:
        raise MaxApiError("MAX /uploads did not return url", payload=created)

    uploaded = await upload_file_bytes(
        str(upload_url),
        data=data,
        filename=filename,
        content_type=content_type,
    )

    photos = uploaded.get("photos") if isinstance(uploaded, dict) else None
    if upload_type == "image" and isinstance(photos, dict) and photos:
        return {"photos": photos}

    media_token = _extract_upload_token(created, uploaded if isinstance(uploaded, dict) else {})
    if not media_token:
        raise MaxApiError(
            "MAX upload did not return token",
            payload={"created": created, "uploaded": uploaded, "type": upload_type},
        )
    return {"token": media_token}


async def upload_and_get_token(
    token: str,
    *,
    upload_type: str,
    data: bytes,
    filename: str,
    content_type: str | None = None,
) -> str:
    payload = await upload_attachment_payload(
        token,
        upload_type=upload_type,
        data=data,
        filename=filename,
        content_type=content_type,
    )
    media_token = payload.get("token")
    if media_token:
        return str(media_token)
    photos = payload.get("photos")
    if isinstance(photos, dict):
        for photo in photos.values():
            if isinstance(photo, dict) and photo.get("token"):
                return str(photo["token"])
    raise MaxApiError("MAX upload did not return token", payload=payload)


async def send_message(
    token: str,
    *,
    text: str | None = None,
    user_id: int | None = None,
    chat_id: int | None = None,
    attachments: list[dict[str, Any]] | None = None,
    reply_to_mid: str | None = None,
) -> dict[str, Any]:
    if user_id is None and chat_id is None:
        raise MaxApiError("user_id or chat_id required")

    params: dict[str, Any] = {}
    if user_id is not None:
        params["user_id"] = user_id
    if chat_id is not None:
        params["chat_id"] = chat_id

    body: dict[str, Any] = {}
    if text:
        body["text"] = text
    if attachments:
        body["attachments"] = attachments
    if reply_to_mid:
        body["link"] = {"type": "reply", "mid": reply_to_mid}

    last_error: MaxApiError | None = None
    for attempt in range(5):
        try:
            async with _client(timeout=60.0) as client:
                response = await client.post(
                    "/messages",
                    headers={"Authorization": token, "Content-Type": "application/json"},
                    params=params,
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise MaxApiError(f"MAX API /messages error: {exc}") from exc

        if response.status_code < 400:
            return response.json()

        payload = _safe_json(response)
        code = None
        if isinstance(payload, dict):
            code = payload.get("code") or (payload.get("error") or {}).get("code") if isinstance(payload.get("error"), dict) else payload.get("code")
        if code == "attachment.not.ready" and attempt < 4:
            await asyncio.sleep(1.5 * (attempt + 1))
            last_error = MaxApiError(
                f"MAX API /messages failed: {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
            continue
        raise MaxApiError(
            f"MAX API /messages failed: {response.status_code}",
            status_code=response.status_code,
            payload=payload,
        )

    assert last_error is not None
    raise last_error


async def edit_message(
    token: str,
    *,
    message_id: str,
    text: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if text is not None:
        body["text"] = text
    if attachments is not None:
        body["attachments"] = attachments
    try:
        async with _client(timeout=60.0) as client:
            response = await client.put(
                "/messages",
                headers={"Authorization": token, "Content-Type": "application/json"},
                params={"message_id": message_id},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API edit /messages error: {exc}") from exc
    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API edit /messages failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    if not response.content:
        return {"success": True}
    return response.json()


async def delete_message(token: str, *, message_id: str) -> dict[str, Any]:
    try:
        async with _client(timeout=30.0) as client:
            response = await client.delete(
                "/messages",
                headers={"Authorization": token},
                params={"message_id": message_id},
            )
    except httpx.HTTPError as exc:
        raise MaxApiError(f"MAX API delete /messages error: {exc}") from exc
    if response.status_code >= 400:
        raise MaxApiError(
            f"MAX API delete /messages failed: {response.status_code}",
            status_code=response.status_code,
            payload=_safe_json(response),
        )
    if not response.content:
        return {"success": True}
    return response.json()


async def download_url(url: str) -> bytes:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=settings.max_api_verify_ssl, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise MaxApiError(f"Download failed: {exc}") from exc
    if response.status_code >= 400:
        raise MaxApiError(f"Download failed: {response.status_code}")
    return response.content


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text
