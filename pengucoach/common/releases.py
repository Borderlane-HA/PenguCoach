"""Bounded, anonymous GitHub release checks, cached independently of dashboards."""
import asyncio
import re
from datetime import datetime, timezone
from time import monotonic

import httpx

RELEASES_URL = "https://github.com/Borderlane-HA/PenguCoach/releases"
API_URL = "https://api.github.com/repos/Borderlane-HA/PenguCoach/releases"
_cache = {}
_lock = asyncio.Lock()


def version_key(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|rc)[.-]?(\d+(?:\.\d+)*))?", str(value).strip(), re.I)
    if not match:
        return None
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch), {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage.lower() if stage else None],
            tuple(map(int, number.split("."))) if number else ())


def select_release(items, installed):
    current = version_key(installed)
    if current is None:
        return {"status": "unknown", "installed_version": installed, "url": RELEASES_URL}
    candidates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = version_key(item.get("tag_name"))
        if key is None or item.get("draft") or (current[3] == 3 and (item.get("prerelease") or key[3] < 3)):
            continue
        url = item.get("html_url", "")
        if not url.startswith(RELEASES_URL + "/tag/"):
            continue
        candidates.append((key, item))
    newest = max(candidates, key=lambda x: x[0])[1] if candidates else None
    return {"status": "available" if newest and version_key(newest["tag_name"]) > current else "current" if newest else "unknown",
            "installed_version": installed, "latest_version": newest["tag_name"] if newest else None,
            "url": newest["html_url"] if newest else RELEASES_URL}


async def update_status(installed, *, refresh=False):
    async with _lock:
        now = monotonic()
        # Manual checks bypass six-hour results, with a shared one-minute
        # cooldown to prevent repeated clicks from flooding GitHub.
        manual_due = refresh and now >= _cache.get("manual_after", 0)
        if now >= _cache.get("expires", 0) or manual_due:
            _cache["manual_after"] = now + 60
            try:
                headers = {"Accept": "application/vnd.github+json", "User-Agent": "PenguCoach-update-check"}
                if _cache.get("etag"):
                    headers["If-None-Match"] = _cache["etag"]
                async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
                    response = await client.get(API_URL, params={"per_page": 100}, headers=headers)
                if response.status_code != 304:
                    response.raise_for_status()
                    items = response.json()
                    if not isinstance(items, list):
                        raise ValueError("INVALID_RELEASE_LIST")
                    _cache.update(items=items, etag=response.headers.get("etag"))
                _cache.update(expires=now + 21600, stale=False,
                              checked_at=datetime.now(timezone.utc).isoformat())
            except (httpx.HTTPError, ValueError):
                _cache.update(expires=now + 600, stale=True)
        meta = {"checked_at": _cache.get("checked_at"), "check_interval_hours": 6,
                "retry_after_seconds": max(0, int(_cache.get("manual_after", 0) - now + .999)),
                "stale": _cache.get("stale", False)}
        if "items" not in _cache:
            return {"status": "unavailable", "installed_version": installed, "url": RELEASES_URL, **meta}
        return {**select_release(_cache["items"], installed), **meta}
