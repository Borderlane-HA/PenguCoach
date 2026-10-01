from pathlib import Path

import pytest

from pengucoach.fit.activity_detail import selected_activity_extras
from pengucoach.sparkyfitness.sync import _avg_speed_mps, _nested_first, _session_started_at


def test_sparky_provider_telemetry_surfaces_full_elevation_and_speed():
    raw = {
        "source": "sparkyfitness",
        "sparkyfitness": {
            "exercise_entry_details": {
                "distance": 2.46,
                "duration_minutes": 31.1,
                "avg_speed_mps": 1.36,
            },
            "provider_activity_details": {
                "telemetry": {
                    "avg_heart_rate": 100,
                    "max_heart_rate": 107,
                    "avg_speed_mps": 1.36,
                    "max_speed_mps": 1.97,
                    "elevation_gain_meters": 9.09,
                    "elevation_loss_meters": 11.27,
                    "min_elevation_meters": 383.62,
                    "max_elevation_meters": 391.9,
                }
            },
        },
    }
    extras = selected_activity_extras(raw)
    assert extras["max_speed_mps"] == pytest.approx(1.97)
    assert extras["elevation_gain_m"] == pytest.approx(9.09)
    assert extras["elevation_loss_m"] == pytest.approx(11.27)
    assert extras["min_elevation_m"] == pytest.approx(383.62)
    assert extras["max_elevation_m"] == pytest.approx(391.9)
    assert _avg_speed_mps(raw["sparkyfitness"]) == pytest.approx(1.36)


def test_nested_sparky_telemetry_names_match_current_v3_contract():
    item = {
        "provider_activity_details": {
            "telemetry": {
                "max_speed_mps": 8.75,
                "elevation_loss_meters": 123.4,
                "min_elevation_meters": 401.2,
                "max_elevation_meters": 612.8,
            }
        }
    }
    assert _nested_first(item, "max_speed_mps") == pytest.approx(8.75)
    assert _nested_first(item, "elevation_loss_meters") == pytest.approx(123.4)
    assert _nested_first(item, "min_elevation_meters") == pytest.approx(401.2)
    assert _nested_first(item, "max_elevation_meters") == pytest.approx(612.8)



def test_healthkit_raw_start_time_beats_relational_midnight_placeholder():
    item = {
        "start_time": "2026-09-22T00:00:00Z",
        "entry_date": "2026-09-22",
        "exercise_entry_details": {
            "raw_data": {
                "startTime": "2026-09-22T15:12:09.114Z",
                "endTime": "2026-09-22T15:43:15.242Z",
            }
        },
    }
    assert _session_started_at(item).isoformat() == "2026-09-22T15:12:09.114000+00:00"

def test_alpha33_auto_sync_and_detail_surfaces_are_shipped():
    model = Path("pengucoach/db/models.py").read_text()
    migration = Path("db/migrations/versions/0008_sparkyfitness_auto_sync.py").read_text()
    scheduler = Path("worker/tasks/scheduler.py").read_text()
    celery = Path("worker/celery_app.py").read_text()
    sync = Path("pengucoach/sparkyfitness/sync.py").read_text()
    api = Path("apps/api/routers/activities.py").read_text()
    page = Path("apps/web/app/settings/sparkyfitness/page.tsx").read_text()
    detail = Path("apps/web/app/activities/[id]/page.tsx").read_text()

    assert "auto_sync_enabled" in model
    assert "sync_interval_minutes" in model
    assert "next_sync_at" in model
    assert 'revision = "0008_sparkyfitness_auto_sync"' in migration
    assert "schedule_due_sparkyfitness_syncs" in scheduler
    assert "schedule-due-sparkyfitness-syncs" in celery
    assert "effective_days = 2 if incremental else configured_days" in sync
    assert '"activity_extra": selected_activity_extras(row.raw)' in api
    assert "Auto-Sync Intervall" in page
    assert "heute + gestern" in page
    assert "const gx=d.activity_extra??d.garmin_extra??{}" in detail
    assert "3600/avgSpeed" in detail
