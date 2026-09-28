from pathlib import Path

from pengucoach.coach.readiness import compute_readiness

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_readiness_is_deterministic_and_explains_low_recovery():
    context = {
        "sleep_30d": [{"date": "2026-09-28", "duration_s": 5 * 3600, "source": "garmin"}],
        "hrv_30d": [
            {"date": "2026-09-27", "overnight_ms": 52, "source": "garmin"},
            {"date": "2026-09-28", "overnight_ms": 38, "baseline_low_ms": 45, "baseline_high_ms": 58, "source": "garmin"},
        ],
        "health_30d": [
            {"date": "2026-09-27", "resting_hr_bpm": 50, "stress_avg": 35, "body_battery_high": 72, "source": "garmin", "sources": {}},
            {"date": "2026-09-28", "resting_hr_bpm": 58, "stress_avg": 72, "body_battery_high": 30, "training_readiness": 28, "source": "garmin", "sources": {}},
        ],
    }
    result = compute_readiness(context, {"energy": 2, "soreness": 4}, [{"feeling": "hard", "exertion": 9}], consecutive_active_days=3)
    assert result["score"] is not None and result["score"] < 50
    assert result["status"] == "red"
    assert result["recommendation"] == "easy_or_rest"
    assert {x["key"] for x in result["components"]} >= {"sleep", "hrv", "resting_hr", "energy", "soreness", "hard_feedback"}
    assert result["method"] == "deterministic_v1"


def test_readiness_does_not_invent_precision_from_sparse_data():
    result = compute_readiness({"sleep_30d": [{"date": "2026-09-28", "duration_s": 8 * 3600, "source": "garmin"}]}, {}, [])
    assert result["score"] is None
    assert result["status"] == "insufficient"


def test_discomfort_caps_score_and_changes_recommendation():
    context = {
        "sleep_30d": [{"date": "2026-09-28", "duration_s": 8 * 3600, "source": "garmin"}],
        "health_30d": [{"date": "2026-09-28", "resting_hr_bpm": 48, "stress_avg": 20, "body_battery_high": 90, "source": "garmin", "sources": {}}],
    }
    result = compute_readiness(context, {"energy": 5, "soreness": 1, "discomfort": "Knie"}, [])
    assert result["score"] <= 39
    assert result["status"] == "red"
    assert result["recommendation"] == "check_discomfort"



def test_stale_recovery_data_is_not_used_as_today_readiness():
    from datetime import date
    context = {
        "sleep_30d": [{"date": "2026-09-20", "duration_s": 4 * 3600, "source": "garmin"}],
        "health_30d": [{"date": "2026-09-20", "resting_hr_bpm": 70, "stress_avg": 90, "source": "garmin", "sources": {}}],
    }
    result = compute_readiness(context, {}, [], today=date(2026, 9, 28))
    assert result["score"] is None
    assert result["available_factors"] == 0

def test_memory_feedback_and_adaptive_plan_contracts_are_exposed():
    backend = text("apps/api/routers/companion.py")
    personal = text("apps/web/components/CoachPersonal.tsx")
    feedback = text("apps/web/components/ActivityFeedback.tsx")
    plan = text("apps/web/components/PlanCompanion.tsx")
    assert 'preferences: str = Field(default="", max_length=1000)' in backend
    assert 'avoidances: str = Field(default="", max_length=1000)' in backend
    assert 'discomfort: str = Field(default="", max_length=500)' in backend
    assert 'Literal["postpone", "easy", "reduce"]' in backend
    assert '"adaptive_suggestions"' in backend
    assert "Trainingspräferenzen" in personal and "Was der Coach vermeiden soll" in personal
    assert "Beschwerden nach der Einheit" in feedback
    assert "readiness_yellow" in plan and "Reduzierte Einheit prüfen" in plan


def test_readiness_ui_and_transparent_method_are_visible():
    daily = text("apps/web/components/DailyCompanion.tsx")
    companion = text("pengucoach/coach/companion.py")
    css = text("apps/web/app/globals.css")
    assert "Pengu Readiness" in daily
    assert "compute_readiness" in companion
    assert "deterministic readiness v1" in companion
    assert ".readiness-card" in css
