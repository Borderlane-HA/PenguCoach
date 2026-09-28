from datetime import date
from pathlib import Path
import tomllib

from pengucoach.coach.training_intelligence import plan_conflicts, weather_assessment


def test_alpha44_license_and_version_surface():
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["version"] == "0.1.0-alpha.44"
    assert project["license"] == "LicenseRef-PolyForm-Noncommercial-1.0.0"
    license_text = Path("LICENSE").read_text()
    assert "polyformproject.org/licenses/noncommercial/1.0.0" in license_text
    assert "Commercial use is not granted" in license_text
    assert "MIT License retain" in license_text


def test_weather_assessment_only_flags_outdoor_and_recommends_indoor_when_unfavorable():
    row = {
        "date": "2026-09-29",
        "temperature_2m_max": 13,
        "temperature_2m_min": 8,
        "precipitation_probability_max": 85,
        "precipitation_sum": 5,
        "wind_speed_10m_max": 40,
        "wind_gusts_10m_max": 58,
        "uv_index_max": 2,
        "weather_code": 61,
    }
    outdoor = weather_assessment(row, "running")
    assert outdoor["severity"] == "severe"
    assert outdoor["indoor_recommended"] is True
    assert "rain_probability" in outdoor["reasons"]
    assert weather_assessment(row, "strength") is None


def test_plan_conflicts_are_deterministic_and_advisory():
    sessions = [
        {"id": "a", "date": "2026-09-28", "name": "VO2 Intervals", "notes": "", "duration_min": 60, "sport": "running", "steps": []},
        {"id": "b", "date": "2026-09-29", "name": "Threshold Run", "notes": "", "duration_min": 100, "sport": "running", "steps": []},
    ]
    conflicts = plan_conflicts(sessions, {"training_days": [1, 3, 5], "session_minutes": 45}, [])
    types = {x["type"] for x in conflicts}
    assert "outside_training_days" in types
    assert "longer_than_typical" in types
    assert "hard_back_to_back" in types
    assert any(x.get("proposed_action") == "reduce" for x in conflicts)


def test_alpha44_ui_keeps_training_intelligence_progressively_disclosed():
    calendar = Path("apps/web/components/TrainingPlanCalendar.tsx").read_text()
    companion = Path("apps/web/components/PlanCompanion.tsx").read_text()
    personal = Path("apps/web/components/CoachPersonal.tsx").read_text()
    about = Path("apps/web/app/settings/about/page.tsx").read_text()
    assert "training-weather-badge" in calendar
    assert "Indoor-Alternative" in calendar
    assert "Plan-Konflikte" in companion
    assert "AI Decision Log" in companion
    assert "Mögliche Präferenz erkannt" in personal
    assert "PolyForm Noncommercial License 1.0.0" in about


def test_plan_conflicts_detect_other_saved_pengucoach_plan_without_garmin_export():
    sessions = [{"id": "current", "date": "2026-09-30", "name": "Easy Run", "notes": "", "duration_min": 45, "sport": "running", "steps": []}]
    other = [{"id": "other", "date": "2026-09-30", "name": "Strength", "plan_run_id": "other-run"}]
    conflicts = plan_conflicts(sessions, {}, [], other)
    row = next(x for x in conflicts if x["type"] == "other_pengucoach_plan_same_day")
    assert row["session_id"] == "current"
    assert row["proposed_action"] == "postpone"
    assert row["garmin_exported"] is False


def test_coach_evidence_surfaces_training_load_context():
    service = Path("pengucoach/llm/service.py").read_text()
    coach = Path("apps/web/app/coach/page.tsx").read_text()
    assert '"training_load"' in service
    assert "used.training_load" in coach
    assert 'bi(lang,"Belastung","Load")' in coach
