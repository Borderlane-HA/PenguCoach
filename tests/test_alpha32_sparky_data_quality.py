from datetime import date
from pathlib import Path

import pytest

from pengucoach.sparkyfitness.sync import (
    _activity_candidate,
    _distance_m,
    _duration_seconds,
    _is_daily_metric_entry,
    _nested_first,
    _session_date,
    _session_started_at,
)


def test_healthkit_raw_workout_keeps_recorded_timestamp_not_import_timestamp():
    healthkit = {
        "uuid": "5AB11F30-5A8D-4091-B8AC-8E368C95612B",
        "endTime": "2026-09-21T09:48:29.805Z",
        "duration": {"unit": "s", "quantity": 1084.9930069446564},
        "startTime": "2026-09-21T09:27:34.129Z",
        "activityType": 52,
        "totalDistance": 1920.478991615586,
        "totalEnergyBurned": 99.74935933602772,
    }
    item = {
        "id": "hk-1",
        "exercise_name": "Walking",
        "source": "healthkit",
        # Reproduces the bad historical-import case: Sparky's relational row
        # may carry the sync day even though raw HealthKit has the real time.
        "entry_date": "2026-09-23",
        "created_at": "2026-09-23T05:00:00Z",
        "raw_data": healthkit,
    }
    assert _session_started_at(item).isoformat() == "2026-09-21T09:27:34.129000+00:00"
    assert _session_date(item) == date(2026, 9, 21)
    assert _duration_seconds(item) == 1085
    assert _distance_m(item) == pytest.approx(1920.478991615586)
    assert _nested_first(item, "totalEnergyBurned") == pytest.approx(99.74935933602772)


def test_detail_created_at_never_overrides_healthkit_raw_start_time():
    item = {
        "id": "hk-2",
        "entry_date": "2026-09-21",
        "raw_data": {"startTime": "2026-09-21T07:00:00Z"},
        "exercise_entry_details": {
            "created_at": "2026-09-23T06:00:00Z",
            "exercise_name": "Hiking",
        },
    }
    assert _session_started_at(item).date() == date(2026, 9, 21)
    assert _session_date(item) == date(2026, 9, 21)


def test_active_calories_are_daily_metric_not_activity():
    item = {
        "id": "move-ring-1",
        "exercise_name": "Active Calories",
        "entry_date": "2026-09-22",
        "calories_burned": 704,
        "exercise_entry_details": {"exercise_name": "Active Calories"},
    }
    assert _is_daily_metric_entry(item) is True
    assert _activity_candidate(item) is False


def test_alpha32_sparky_data_quality_surfaces_are_shipped():
    sync = Path("pengucoach/sparkyfitness/sync.py").read_text()
    api = Path("apps/api/routers/sparkyfitness.py").read_text()
    page = Path("apps/web/app/settings/sparkyfitness/page.tsx").read_text()
    assert 'domain="daily_metric_active_calories"' in sync
    assert '_merge_active_calories_metric' in sync
    assert 'observed_at=_session_started_at(item)' in sync
    assert 'delete_local_sparkyfitness_data' in sync
    assert '@router.delete("/local-data")' in api
    assert 'Alle SparkyFitness-Daten löschen' in page
    assert 'Auf dem SparkyFitness-Server wird nichts gelöscht' in page
