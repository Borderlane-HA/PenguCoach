import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.api.routers import settings
from pengucoach.common import changelog as module

NOTES = '# Changelog\n\n## 0.1.0-alpha.72\n\n- Neue **Ansicht**.\n'


@pytest.fixture
def github(monkeypatch):
    module._cache.clear()
    monkeypatch.setattr(module, '_lock', asyncio.Lock())
    clock = [1000.]
    monkeypatch.setattr(module, 'monotonic', lambda:clock[0])
    original = httpx.AsyncClient
    seen, replies = [], []
    async def respond(request):
        seen.append(request)
        await asyncio.sleep(0)
        reply = replies.pop(0)
        if isinstance(reply, Exception):raise reply
        code, content, headers = reply
        return httpx.Response(code, content=content, headers={'content-type':'text/plain; charset=utf-8', **headers})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kw:original(**kw, transport=httpx.MockTransport(respond)))
    yield clock, seen, replies
    module._cache.clear()


def ok(content=NOTES):return 200, content.encode('utf-8'), {'etag':'"notes"'}


async def test_changelog_is_anonymous_fixed_source_and_cached_for_six_hours(github):
    clock, seen, replies = github
    replies.append(ok())
    result = await module.changelog()
    assert result['status'] == 'available' and result['content'] == NOTES and not result['stale']
    assert result['checked_at'] and result['check_interval_hours'] == 6
    assert str(seen[0].url) == module.RAW_URL
    assert not seen[0].url.query and 'authorization' not in seen[0].headers and 'cookie' not in seen[0].headers
    clock[0] += 21599
    assert (await module.changelog())['content'] == NOTES and len(seen) == 1
    clock[0] += 1
    replies.append(ok(NOTES.replace('72', '73')))
    assert 'alpha.73' in (await module.changelog())['content'] and len(seen) == 2


async def test_manual_refresh_uses_etag_and_concurrent_clicks_are_deduplicated(github):
    clock, seen, replies = github
    replies.append(ok())
    await module.changelog()
    assert (await module.changelog(refresh=True))['retry_after_seconds'] == 60
    assert len(seen) == 1
    clock[0] += 60
    replies.append((304, b'', {}))
    results = await asyncio.gather(*(module.changelog(refresh=True) for _ in range(8)))
    assert len(seen) == 2 and seen[-1].headers['If-None-Match'] == '"notes"'
    assert all(r['content'] == NOTES and not r['stale'] for r in results)


async def test_failure_keeps_last_known_content_and_check_time(github):
    clock, seen, replies = github
    replies.append(ok())
    first = await module.changelog()
    clock[0] += 61
    replies.append((503, b'upstream error', {}))
    stale = await module.changelog(refresh=True)
    assert stale['content'] == NOTES and stale['stale']
    assert stale['checked_at'] == first['checked_at'] and len(seen) == 2
    await module.changelog()
    assert len(seen) == 2


@pytest.mark.parametrize('reply', [
    (503, b'error', {}), (302, b'', {'location':'http://127.0.0.1/private'}),
    (200, b'<html>not markdown</html>', {'content-type':'text/html'}),
    (200, b'no release headings', {}), (200, b'## release\n\xff', {}),
    (200, b'## release\n' + b'x'*(module.MAX_BYTES+1), {}), (304, b'', {}),
    httpx.ReadTimeout('offline'), TimeoutError('deadline'),
])
async def test_invalid_or_unreachable_source_is_reported_without_fake_content(github, reply):
    _, seen, replies = github
    replies.append(reply)
    result = await module.changelog()
    assert result['status'] == 'unavailable' and result['content'] is None and result['stale']
    assert result['checked_at'] is None and result['url'] == module.SOURCE_URL
    assert (await module.changelog(refresh=True))['status'] == 'unavailable' and len(seen) == 1


async def test_authenticated_settings_endpoint_passes_refresh(monkeypatch):
    fetch = AsyncMock(return_value={'status':'available', 'content':NOTES})
    monkeypatch.setattr(module, 'changelog', fetch)
    assert (await settings.get_changelog(refresh=True, user=object()))['content'] == NOTES
    fetch.assert_awaited_once_with(refresh=True)
    route = next(route for route in settings.router.routes if route.path == '/settings/changelog')
    assert any(dependency.call is settings.safety_confirmed_user for dependency in route.dependant.dependencies)
