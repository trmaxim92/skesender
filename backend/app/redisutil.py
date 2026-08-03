"""Optional Redis helpers for multi-worker realtime + leader election."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_redis: Redis | None = None


def redis_enabled() -> bool:
    return get_settings().redis_enabled


async def get_redis() -> Redis | None:
    """Return a shared async Redis client, or None if REDIS_URL is empty."""
    global _redis
    if not redis_enabled():
        return None
    if _redis is not None:
        return _redis
    from redis.asyncio import Redis

    url = get_settings().redis_url.strip()
    _redis = Redis.from_url(url, decode_responses=True)
    try:
        await _redis.ping()
    except Exception:
        logger.exception("Redis ping failed url=%s", url)
        await _redis.aclose()
        _redis = None
        raise
    logger.info("Redis connected")
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis closed")
