"""QR / 2FA bridges between FastAPI UI and PyMax auth providers."""

from __future__ import annotations

import asyncio


class BridgeQrHandler:
    def __init__(self) -> None:
        self.qr_url: str | None = None
        self.shown = asyncio.Event()

    async def show_qr(self, qr_url: str) -> None:
        self.qr_url = qr_url
        self.shown.set()


class BridgePasswordProvider:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.waiting = asyncio.Event()
        self.hint: str | None = None

    async def get_password(self, hint: str | None = None) -> str:
        self.hint = hint
        self.waiting.set()
        password = await self._queue.get()
        self.waiting.clear()
        return password.strip()

    async def submit(self, password: str) -> None:
        await self._queue.put(password)
