import asyncio

import httpx
import pytest

from apps.api.routers import settings
from pengucoach.common import releases


@pytest.fixture
def github(monkeypatch):
    releases._cache.clear()
    clock = [1000.0]
    monkeypatch.setattr(releases, "monotonic", lambda: clock[0])
    original = httpx.AsyncClient
    seen = []
    replies = []

    async def respond(request):
        seen.append(request)
        await asyncio.sleep(0)
        code, content = replies.pop(0)
        return httpx.Response(code, json=content if code != 304 else None, headers={"ETag": '"release"'})

    monkeypatch.setattr(releases.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    yield clock, seen, replies
    releases._cache.clear()


def item(tag):
    return {"tag_name": tag, "prerelease": True, "html_url": releases.RELEASES_URL + "/tag/" + tag}


async def test_manual_check_bypasses_six_hour_cache_after_short_cooldown(github):
    clock, seen, replies = github
    replies.append((200, [item("v0.1.0-alpha.68")]))
    first = await releases.update_status("0.1.0-alpha.68")
    assert first["status"] == "current" and first["checked_at"] and first["check_interval_hours"] == 6
    clock[0] += 61
    assert (await releases.update_status("0.1.0-alpha.68"))["status"] == "current"
    assert len(seen) == 1
    replies.append((200, [item("v0.1.0-alpha.69")]))
    result = await releases.update_status("0.1.0-alpha.68", refresh=True)
    assert len(seen) == 2 and result["status"] == "available"
    assert result["latest_version"] == "v0.1.0-alpha.69" and result["retry_after_seconds"] == 60
    assert (await releases.update_status("0.1.0-alpha.68"))["latest_version"] == "v0.1.0-alpha.69"


async def test_concurrent_manual_clicks_share_one_github_request(github):
    _, seen, replies = github
    replies.append((200, [item("v0.1.0-alpha.69")]))
    results = await asyncio.gather(*(releases.update_status("0.1.0-alpha.68", refresh=True) for _ in range(8)))
    assert len(seen) == 1 and all(result["status"] == "available" for result in results)
    assert all("authorization" not in request.headers for request in seen)


async def test_automatic_check_refreshes_after_six_hours(github):
    clock, seen, replies = github
    replies.extend([(200, [item("v0.1.0-alpha.68")]), (200, [item("v0.1.0-alpha.69")])])
    await releases.update_status("0.1.0-alpha.68")
    clock[0] += 21599
    assert (await releases.update_status("0.1.0-alpha.68"))["status"] == "current"
    clock[0] += 1
    assert (await releases.update_status("0.1.0-alpha.68"))["status"] == "available"
    assert len(seen) == 2


async def test_manual_etag_and_failure_retain_last_known_release_without_claiming_freshness(github):
    clock, seen, replies = github
    replies.append((200, [item("v0.1.0-alpha.69")]))
    await releases.update_status("0.1.0-alpha.68")
    clock[0] += 60
    replies.append((304, None))
    fresh = await releases.update_status("0.1.0-alpha.68", refresh=True)
    assert seen[-1].headers["If-None-Match"] == '"release"' and not fresh["stale"]
    clock[0] += 60
    replies.append((503, {}))
    failed = await releases.update_status("0.1.0-alpha.68", refresh=True)
    assert failed["stale"] and failed["checked_at"] == fresh["checked_at"]
    assert failed["latest_version"] == "v0.1.0-alpha.69"
    assert len(seen) == 3


async def test_offline_initial_check_is_unknown_and_clicks_are_throttled(github):
    _, seen, replies = github
    replies.append((503, {}))
    result = await releases.update_status("0.1.0-alpha.69", refresh=True)
    assert result["status"] == "unavailable" and result["checked_at"] is None
    assert (await releases.update_status("0.1.0-alpha.69", refresh=True))["status"] == "unavailable"
    assert len(seen) == 1


async def test_authenticated_endpoint_requests_a_manual_refresh(monkeypatch):
    from unittest.mock import AsyncMock
    check = AsyncMock(return_value={"status": "available"})
    monkeypatch.setattr(releases, "update_status", check)
    assert await settings.check_update_now(user=object()) == {"status": "available"}
    check.assert_awaited_once_with(settings.settings.resolved_app_version, refresh=True)
