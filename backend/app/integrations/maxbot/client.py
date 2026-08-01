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


async def upload_file_bytes(
    upload_url: str,
    *,
    data: bytes,
    filename: str,
    token: str | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = token
    files = {"data": (filename, data)}
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=120.0, verify=settings.max_api_verify_ssl) as client:
            response = await client.post(upload_url, headers=headers, files=files)
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
        return response.json()
    except Exception:
        return {"raw": response.text}


async def upload_and_get_token(
    token: str,
    *,
    upload_type: str,
    data: bytes,
    filename: str,
) -> str:
    created = await create_upload(token, upload_type)
    upload_url = created.get("url")
    if not upload_url:
        raise MaxApiError("MAX /uploads did not return url", payload=created)

    # video/audio may already include token at create step
    early_token = created.get("token")
    uploaded = await upload_file_bytes(str(upload_url), data=data, filename=filename, token=token)
    payload = uploaded.get("payload") if isinstance(uploaded.get("payload"), dict) else {}
    final_token = uploaded.get("token") or early_token or payload.get("token")
    if not final_token:
        raise MaxApiError("MAX upload did not return token", payload={"created": created, "uploaded": uploaded})
    return str(final_token)


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
