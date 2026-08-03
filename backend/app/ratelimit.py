"""Rate limiter: Redis cluster-wide when REDIS_URL is set, else in-process."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

from app.redisutil import get_redis, redis_enabled

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    """Allow `limit` events per `window_sec` for a key (local process only)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, *, limit: int, window_sec: float) -> bool:
        now = time.monotonic()
        cutoff = now - window_sec
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


class RateLimiter:
    def __init__(self) -> None:
        self._local = SlidingWindowLimiter()

    async def hit(self, key: str, *, limit: int, window_sec: float) -> bool:
        """Record an attempt. Returns True if allowed."""
        if redis_enabled():
            try:
                r = await get_redis()
                if r is not None:
                    # Fixed window counter shared across workers.
                    bucket = int(time.time() // max(window_sec, 1))
                    redis_key = f"skysender:rl:{key}:{bucket}"
                    count = await r.incr(redis_key)
                    if count == 1:
                        await r.expire(redis_key, int(max(window_sec, 1)) + 1)
                    return int(count) <= limit
            except Exception:
                logger.exception("Redis rate-limit failed — local fallback key=%s", key)
        return self._local.hit(key, limit=limit, window_sec=window_sec)

    async def check(self, key: str, *, limit: int, window_sec: float, detail: str) -> None:
        if not await self.hit(key, limit=limit, window_sec=window_sec):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
                headers={"Retry-After": str(max(1, int(window_sec)))},
            )


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
