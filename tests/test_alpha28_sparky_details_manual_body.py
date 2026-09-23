from pathlib import Path

import pytest

from pengucoach.sparkyfitness.sync import _distance_m, _duration_seconds, _enrich_activity_item


class FakeSparkyClient:
    def __init__(self):
        self.paths: list[str] = []

    async def request(self, path: str, *, params=None):
        self.paths.append(path)
        if path.startswith('/exercise-entries/'):
            return {
                'id': 'hk-1',
                'exercise_name': 'Hiking',
                'source': 'healthkit',
                'duration_minutes': 21.86,
                'distance': 1.86,
                'calories_burned': 86.3,
                'avg_heart_rate': None,
            }
        if path.startswith('/exercises/activity-details/'):
            return {
                'telemetry': {
                    'avg_heart_rate': 118,
                    'max_heart_rate': 142,
                    'elevation_gain_meters': 36,
                }
            }
        raise AssertionError(f'unexpected detail request: {path}')


@pytest.mark.asyncio
async def test_sparky_history_is_enriched_from_relational_exercise_entry():
    history = {
        'id': 'hk-1',
        'exercise_name': 'Hiking',
        'category': 'Hiking',
        'source': 'healthkit',
        'entry_date': '2026-09-10',
        # Compact history can carry a different/session duration and omit distance.
        'duration_seconds': 1635,
    }
    client = FakeSparkyClient()
    enriched, requests = await _enrich_activity_item(client, history)
    assert requests == 2
    assert client.paths == ['/exercise-entries/hk-1', '/exercises/activity-details/hk-1/healthkit']
    assert _duration_seconds(enriched) == 1312  # 21.86 min rounded to seconds
    assert _distance_m(enriched) == pytest.approx(1860.0)
    assert enriched['exercise_entry_details']['calories_burned'] == pytest.approx(86.3)
    assert enriched['provider_activity_details']['telemetry']['avg_heart_rate'] == 118


def test_manual_body_fallback_and_sparky_detail_surfaces_are_shipped():
    api = Path('apps/api/routers/health.py').read_text()
    health = Path('apps/web/app/health/page.tsx').read_text()
    sync = Path('pengucoach/sparkyfitness/sync.py').read_text()
    docs = Path('docs/SPARKYFITNESS.md').read_text()

    assert '@router.put("/body/manual")' in api
    assert 'source": "manual_body"' in api
    assert 'body_all_rows = await _body_rows' in api
    assert 'Manuell erfassen' in health
    assert 'source==="manual"' in health
    assert '/exercise-entries/{id}' in docs
    assert 'exercise_entry_details' in sync
    assert 'activities_enriched' in sync


def test_alpha28_version_surface():
    import re
    pyproject = Path('pyproject.toml').read_text()
    package = Path('apps/web/package.json').read_text()
    py_version = re.search(r'version = \"([^\"]+)\"', pyproject).group(1)
    web_version = re.search(r'\"version\": \"([^\"]+)\"', package).group(1)
    assert py_version == web_version
    assert re.fullmatch(r'0\.1\.0-alpha\.\d+', py_version)

