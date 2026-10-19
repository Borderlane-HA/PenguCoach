"""Read the project's public changelog without sending account or health data."""
import asyncio
import re
from datetime import datetime, timezone
from time import monotonic

import httpx

SOURCE_URL = "https://github.com/Borderlane-HA/PenguCoach/blob/main/CHANGELOG.md"
RAW_URL = "https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/CHANGELOG.md"
MAX_BYTES = 1024 * 1024
_cache = {}
_lock = asyncio.Lock()


async def changelog(*, refresh=False):
    async with _lock:
        now = monotonic()
        if now >= _cache.get("expires", 0) or (refresh and now >= _cache.get("manual_after", 0)):
            _cache["manual_after"] = now + 60
            try:
                headers = {"Accept": "text/plain", "User-Agent": "PenguCoach-changelog"}
                if _cache.get("etag"):
                    headers["If-None-Match"] = _cache["etag"]
                # Bound the entire fetch as well as individual reads and bytes.
                async with asyncio.timeout(6):
                    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                        async with client.stream("GET", RAW_URL, headers=headers) as response:
                            if response.status_code == 304:
                                if "content" not in _cache:
                                    raise ValueError("CHANGELOG_CACHE_MISSING")
                            else:
                                response.raise_for_status()
                                if "text/plain" not in response.headers.get("content-type", "").lower():
                                    raise ValueError("CHANGELOG_CONTENT_TYPE")
                                body = bytearray()
                                async for chunk in response.aiter_bytes():
                                    body.extend(chunk)
                                    if len(body) > MAX_BYTES:
                                        raise ValueError("CHANGELOG_TOO_LARGE")
                                content = body.decode("utf-8-sig")
                                if not re.search(r"(?m)^##\s+\S", content):
                                    raise ValueError("CHANGELOG_INVALID")
                                _cache.update(content=content, etag=response.headers.get("etag"))
                _cache.update(expires=now + 21600, stale=False,
                              checked_at=datetime.now(timezone.utc).isoformat())
            except (httpx.HTTPError, ValueError, TimeoutError):
                _cache.update(expires=now + 600, stale=True)
        return {"status": "available" if "content" in _cache else "unavailable",
                "content": _cache.get("content"), "url": SOURCE_URL,
                "checked_at": _cache.get("checked_at"), "stale": _cache.get("stale", False),
                "check_interval_hours": 6,
                "retry_after_seconds": max(0, int(_cache.get("manual_after", 0) - monotonic() + .999))}
