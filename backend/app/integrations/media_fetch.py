"""HTTP fetch for provider CDN URLs (MAX okcdn, oneme, etc.)."""

from __future__ import annotations

import httpx

# okcdn / MAX video CDN returns 400 without a browser-like User-Agent.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


async def fetch_url_bytes(
    url: str,
    *,
    timeout: float = 120.0,
    verify: bool = True,
) -> bytes:
    async with httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=True,
        headers=BROWSER_HEADERS,
    ) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise RuntimeError(f"download failed: {response.status_code}")
    return response.content
