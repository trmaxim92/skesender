from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings
from app.integrations.base import IntegrationError

FLEET_API_BASE = "https://fleet-api.taxi.yandex.net"
_PAGE_SIZE = 200
_PAGE_PAUSE_SEC = 0.35


class FleetApiError(IntegrationError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def fleet_configured() -> bool:
    s = get_settings()
    return bool(
        (s.fleet_client_id or "").strip()
        and (s.fleet_api_key or "").strip()
        and (s.fleet_park_id or "").strip()
    )


def _headers() -> dict[str, str]:
    s = get_settings()
    return {
        "Accept-Language": "ru",
        "Content-Type": "application/json",
        "X-Client-ID": (s.fleet_client_id or "").strip(),
        "X-API-Key": (s.fleet_api_key or "").strip(),
        "X-Park-ID": (s.fleet_park_id or "").strip(),
    }


async def list_driver_profiles_page(
    *,
    offset: int = 0,
    limit: int = _PAGE_SIZE,
) -> dict[str, Any]:
    """POST /v1/parks/driver-profiles/list — one page."""
    if not fleet_configured():
        raise FleetApiError("Fleet API не настроен (FLEET_CLIENT_ID / FLEET_API_KEY / FLEET_PARK_ID)")

    settings = get_settings()
    park_id = (settings.fleet_park_id or "").strip()
    # Skip fired roster by default — park can have 10k+ historical profiles.
    statuses = [
        s.strip()
        for s in (settings.fleet_work_statuses or "working,not_working").split(",")
        if s.strip()
    ]
    park_query: dict[str, Any] = {"id": park_id}
    if statuses:
        park_query["driver_profile"] = {"work_status": statuses}
    body: dict[str, Any] = {
        "limit": min(max(limit, 1), _PAGE_SIZE),
        "offset": max(offset, 0),
        "query": {"park": park_query},
        "fields": {
            "driver_profile": [
                "id",
                "park_id",
                "first_name",
                "last_name",
                "middle_name",
                "phones",
                "work_status",
                "work_rule_id",
                "employment_type",
                "created_date",
            ],
            "car": ["id", "status", "category", "brand", "model", "number"],
        },
        "sort_order": [{"direction": "asc", "field": "driver_profile.created_date"}],
    }

    last_error: FleetApiError | None = None
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(base_url=FLEET_API_BASE, timeout=60.0) as client:
                response = await client.post(
                    "/v1/parks/driver-profiles/list",
                    headers=_headers(),
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise FleetApiError(f"Fleet API connection error: {exc}") from exc

        if response.status_code == 429:
            last_error = FleetApiError(
                "Fleet API rate limit (429)",
                status_code=429,
                payload=response.text[:300],
            )
            await asyncio.sleep(1.5 * (attempt + 1))
            continue

        if response.status_code >= 400:
            payload: Any
            try:
                payload = response.json()
            except Exception:
                payload = response.text[:500]
            raise FleetApiError(
                f"Fleet API list failed: {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        return response.json()

    assert last_error is not None
    raise last_error


async def iter_all_driver_profiles() -> list[dict[str, Any]]:
    """Fetch all driver profiles for the configured park (paginated)."""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = await list_driver_profiles_page(offset=offset, limit=_PAGE_SIZE)
        batch = page.get("driver_profiles") or []
        if not isinstance(batch, list):
            break
        items.extend(batch)
        total = int(page.get("total") or 0)
        offset += len(batch)
        if not batch or (total and offset >= total) or len(batch) < _PAGE_SIZE:
            break
        await asyncio.sleep(_PAGE_PAUSE_SEC)
    return items
