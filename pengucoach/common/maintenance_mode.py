"""Maintenance mode set by the host agent while it drains background work.

During an update, restore or full backup the agent sets a short-lived Redis key.
The API then rejects new state-changing requests and the scheduler queues no new
syncs, so the agent only waits for work that was already running. Any Redis
problem fails open: maintenance mode never blocks a normal installation.
"""
from functools import lru_cache
from time import monotonic

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from pengucoach.common.config import settings

KEY = "pengucoach:maintenance"
_CACHE_SECONDS = 2.0
_cache = {"at": -_CACHE_SECONDS, "value": False}
_async_client = None


@lru_cache(maxsize=1)
def _redis() -> Redis:
    return Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)


def active() -> bool:
    try:
        return bool(_redis().exists(KEY))
    except Exception:
        return False


async def active_async() -> bool:
    global _async_client
    now = monotonic()
    if now - _cache["at"] < _CACHE_SECONDS:
        return _cache["value"]
    try:
        if _async_client is None:
            _async_client = AsyncRedis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)
        value = bool(await _async_client.exists(KEY))
    except Exception:
        value = False
    _cache.update(at=now, value=value)
    return value
