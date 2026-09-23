from datetime import date
from pathlib import Path

from pengucoach.sparkyfitness.sync import (
    _date_chunks,
    _distance_m,
    _duration_seconds,
    _session_started_at,
    _sport,
    _synthetic_activity_id,
)


def test_sparky_session_parsing_accepts_common_api_shapes():
    item = {
        "activityName": "Morning Ride",
        "activityType": "road_biking",
        "startTime": "2026-09-21T08:30:00Z",
        "durationMinutes": 75,
        "distanceKm": 32.4,
    }
    assert _sport(item) == "cycling"
    assert _duration_seconds(item) == 4500
    assert _distance_m(item) == 32400
    assert _session_started_at(item) is not None


def test_sparky_synthetic_activity_ids_are_stable_and_negative():
    first = _synthetic_activity_id("abc-123")
    assert first < 0
    assert first == _synthetic_activity_id("abc-123")
    assert first != _synthetic_activity_id("abc-124")


def test_long_sparky_ranges_are_chunked_inclusively():
    chunks = list(_date_chunks(date(2024, 1, 1), date(2026, 9, 22), chunk_days=366))
    assert chunks[0][0] == date(2024, 1, 1)
    assert chunks[-1][1] == date(2026, 9, 22)
    for left, right in zip(chunks, chunks[1:]):
        assert (right[0] - left[1]).days == 1


def test_activity_diary_exposes_sparky_provenance_and_filtering():
    api = Path("apps/api/routers/activities.py").read_text()
    page = Path("apps/web/app/activities/page.tsx").read_text()
    sync = Path("pengucoach/sparkyfitness/sync.py").read_text()
    assert 'source: str | None = Query' in api
    assert '"sparky_total"' in api
    assert '"sources": sources' in api
    assert 'sourceFilter' in page
    assert 'SparkyFitness' in page
    assert 'raw={\n            "source": "sparkyfitness"' in sync
    assert 'Activity.garmin_activity_id > 0' in sync


def test_health_cards_keep_source_provenance_and_period_aggregation():
    page = Path("apps/web/app/health/page.tsx").read_text()
    assert "function metricAverage" in page
    assert 'metricAverage(data.sleep??[],"duration_seconds")' in page
    assert 'metricAverage(data.health??[],"resting_hr")' in page
    assert "Garmin + SparkyFitness" in page


def test_sparky_sync_supports_multi_year_and_all_data():
    router = Path("apps/api/routers/sparkyfitness.py").read_text()
    page = Path("apps/web/app/settings/sparkyfitness/page.tsx").read_text()
    sync = Path("pengucoach/sparkyfitness/sync.py").read_text()
    assert "ge=0" in router
    assert '<option value={1826}>' in page
    assert '<option value={0}>' in page
    assert 'all_data = configured_days <= 0' in sync
    assert '"/sleep/details"' in sync
    assert 'activities_created' in sync
    assert 'activities_merged' in sync
