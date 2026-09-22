from pathlib import Path

import pytest

from pengucoach.training_plan.calendar import apply_session_overrides
from pengucoach.training_plan.structured import TrainingSession


def _session() -> TrainingSession:
    return TrainingSession.model_validate({
        "id": "w1-d1-run",
        "week": 1,
        "day": 1,
        "name": "Base run",
        "sport": "running",
        "duration_min": 50,
        "steps": [
            {"type": "warmup", "duration_seconds": 600},
            {"type": "work", "duration_seconds": 1800, "target": {"type": "heart_rate_zone", "zone": 2}},
            {"type": "cooldown", "duration_seconds": 600},
        ],
    })


def test_activity_journal_uses_real_server_side_pagination_and_search():
    api = Path("apps/api/routers/activities.py").read_text()
    ui = Path("apps/web/app/activities/page.tsx").read_text()
    assert "per_page: int | None" in api
    assert ".offset(offset).limit(page_size)" in api
    assert "filtered_total" in api
    assert "cast(Activity.raw, String).ilike(pattern)" in api
    assert 'per_page:String(perPage)' in ui
    assert 'value={25}' in ui and 'value={50}' in ui and 'value={100}' in ui
    assert "activity-pager" in ui
    assert "filtered_total" in ui
    assert "/activities?limit=200" not in ui


def test_session_override_can_change_duration_and_remove_warmup_without_mutating_identity():
    original = _session()
    edited = original.model_copy(deep=True)
    edited.duration_min = 20
    edited.steps = edited.steps[1:2]
    edited.steps[0].duration_seconds = 1200
    result = apply_session_overrides([original], {original.id: edited})
    assert result[0].duration_min == 20
    assert len(result[0].steps) == 1
    assert result[0].steps[0].type == "work"
    assert original.duration_min == 50
    assert len(original.steps) == 3


def test_session_override_cannot_move_or_change_sport():
    original = _session()
    edited = original.model_copy(deep=True)
    edited.day = 2
    with pytest.raises(ValueError, match="TRAINING_SESSION_OVERRIDE_IDENTITY_MISMATCH"):
        apply_session_overrides([original], {original.id: edited})


def test_garmin_preview_and_worker_apply_user_calendar_edits():
    router = Path("apps/api/routers/garmin_workouts.py").read_text()
    worker = Path("worker/tasks/garmin_workouts.py").read_text()
    ui = Path("apps/web/components/TrainingPlanCalendar.tsx").read_text()
    assert "session_overrides" in router
    assert "apply_session_overrides" in router
    assert 'payload.get("session_overrides")' in worker
    assert "Vor Garmin bearbeiten" in ui
    assert "Gesamtdauer aus Schritten übernehmen" in ui
    assert "session_overrides:overrides" in ui
    assert "localStorage.setItem(editKey" in ui
