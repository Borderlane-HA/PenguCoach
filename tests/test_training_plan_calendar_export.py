from datetime import date
from pathlib import Path

from pengucoach.training_plan.calendar import scheduled_date, selected_sessions
from pengucoach.training_plan.generation import normalize_training_plan_answer
from pengucoach.training_plan.structured import PLAN_CLOSE, PLAN_OPEN, extract_structured_plan


def _answer() -> dict:
    return {
        "content": f'''{PLAN_OPEN}
{{
  "format_version": 1,
  "title": "Base + intervals",
  "summary": "Two sessions",
  "weeks": 2,
  "sessions": [
    {{
      "id": "w1-d2-bike",
      "week": 1,
      "day": 2,
      "name": "Z2 ride",
      "sport": "cycling",
      "duration_min": 60,
      "optional": false,
      "notes": "Keep it easy",
      "steps": [
        {{"type": "warmup", "duration_seconds": 600}},
        {{"type": "work", "duration_seconds": 2400, "target": {{"type": "heart_rate_zone", "zone": 2}}}},
        {{"type": "cooldown", "duration_seconds": 600}}
      ],
      "strength_exercises": []
    }},
    {{
      "id": "w2-d6-run",
      "week": 2,
      "day": 6,
      "name": "Intervals",
      "sport": "running",
      "duration_min": 45,
      "optional": true,
      "notes": "Controlled",
      "steps": [
        {{"type": "warmup", "duration_seconds": 600}},
        {{"type": "repeat", "repeat": 4, "steps": [
          {{"type": "interval", "duration_seconds": 180, "target": {{"type": "heart_rate_zone", "zone": 4}}}},
          {{"type": "recovery", "duration_seconds": 120}}
        ]}},
        {{"type": "cooldown", "duration_seconds": 600}}
      ],
      "strength_exercises": []
    }}
  ]
}}
{PLAN_CLOSE}'''
    }


def test_structured_plan_is_extracted_rendered_and_scheduled():
    plan, error = extract_structured_plan(_answer()["content"])
    assert error is None
    assert plan is not None
    assert scheduled_date(date(2026, 9, 28), plan.sessions[0]) == date(2026, 9, 29)
    assert scheduled_date(date(2026, 9, 28), plan.sessions[1]) == date(2026, 10, 10)
    assert [x.id for x in selected_sessions(plan, ["w2-d6-run"])] == ["w2-d6-run"]

    content, metadata = normalize_training_plan_answer(_answer(), "de")
    assert metadata["structured_plan_valid"] is True
    assert metadata["structured_plan"]["sessions"][0]["id"] == "w1-d2-bike"
    assert "# Base + intervals" in content
    assert "HF Z2" in content
    assert "4×" in content


def test_invalid_structured_plan_keeps_original_ai_content():
    answer = {"content": "A readable plan without the machine block."}
    content, metadata = normalize_training_plan_answer(answer, "de")
    assert content == answer["content"]
    assert metadata["structured_plan_valid"] is False
    assert metadata["structured_plan"] is None
    assert metadata["structured_plan_error"] == "STRUCTURED_PLAN_MARKER_MISSING"


def test_garmin_write_surface_stays_narrow_and_opt_in_is_default_off():
    gateway = Path("pengucoach/garmin/gateway/workouts.py").read_text()
    settings = Path("pengucoach/db/models.py").read_text()
    migration = Path("db/migrations/versions/0004_garmin_workout_export.py").read_text()

    assert "class GarminWorkoutGateway" in gateway
    assert "def upload_session" in gateway
    assert "def schedule_workout" in gateway
    assert "def unschedule_workout" in gateway
    assert "def delete_workout" in gateway
    assert "__getattr__" not in gateway
    assert "workout_export_enabled: Mapped[bool] = mapped_column(Boolean, default=False)" in settings
    assert 'server_default=sa.false()' in migration
    assert 'sa.UniqueConstraint("user_id", "plan_run_id", "session_id", "scheduled_date")' in migration
