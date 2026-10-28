from __future__ import annotations

from functools import lru_cache

from redis import Redis

from pengucoach.common.config import settings

_CANCEL_PREFIX = "pengucoach:ai-cancel:"
_CANCEL_TTL_SECONDS = 24 * 60 * 60


@lru_cache(maxsize=1)
def _redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def request_cancel(task_id: str) -> None:
    """Request cooperative cancellation of an AI background job."""
    _redis().setex(_CANCEL_PREFIX + task_id, _CANCEL_TTL_SECONDS, "1")


def cancel_requested(task_id: str) -> bool:
    """Return whether cancellation has been requested for this task id."""
    try:
        return bool(_redis().get(_CANCEL_PREFIX + task_id))
    except Exception:
        # A Redis control-key failure must not make an otherwise valid AI job fail.
        return False


def clear_cancel(task_id: str) -> None:
    try:
        _redis().delete(_CANCEL_PREFIX + task_id)
    except Exception:
        pass
