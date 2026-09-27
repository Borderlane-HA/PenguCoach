import json

from pengucoach.fit.activity_detail import selected_garmin_extras
from pengucoach.llm.service import (
    DEEP_ACTIVITY_PROMPT_DE,
    DEEP_ACTIVITY_PROMPT_EN,
    TASK_DEFAULTS,
    TRAINING_PLAN_PROMPT_DE,
    _bounded_context,
    _locale_key,
)


def test_garmin_elevation_totals_are_exposed():
    extra = selected_garmin_extras({
        "elevationGain": 431.0,
        "elevationLoss": 428.0,
        "minElevation": 379.0,
        "maxElevation": 530.0,
        "maxSpeed": 15.3,
    })
    assert extra["elevation_gain_m"] == 431.0
    assert extra["elevation_loss_m"] == 428.0
    assert extra["min_elevation_m"] == 379.0
    assert extra["max_elevation_m"] == 530.0


def test_ai_task_defaults_include_context_and_response_budgets():
    assert TASK_DEFAULTS["coach_chat"]["context_window_tokens"] == 8192
    assert TASK_DEFAULTS["activity_analysis"]["max_output_tokens"] == 8000
    assert TASK_DEFAULTS["training_plan"]["max_output_tokens"] == 8000
    assert TASK_DEFAULTS["activity_analysis"]["max_output_tokens"] <= 8192


def test_prompts_are_bilingual_and_deep_analysis_has_lookbacks():
    assert "activity_day" in DEEP_ACTIVITY_PROMPT_DE
    assert "three_days" in DEEP_ACTIVITY_PROMPT_DE and "seven_days" in DEEP_ACTIVITY_PROMPT_DE
    assert "activity_day" in DEEP_ACTIVITY_PROMPT_EN
    assert "three_days" in DEEP_ACTIVITY_PROMPT_EN and "seven_days" in DEEP_ACTIVITY_PROMPT_EN
    assert "periodisierten" in TRAINING_PLAN_PROMPT_DE
    assert _locale_key("de-DE") == "de"
    assert _locale_key("en-GB") == "en"


def test_context_budget_keeps_valid_json():
    context = {"source_notice": "x", "recent_activities": [{"n": i, "text": "x" * 500} for i in range(100)]}
    payload, meta = _bounded_context(context, 6000)
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    assert meta["context_chars"] <= 6000
    assert meta["context_truncated"] is True


def test_coach_context_compaction_keeps_real_training_and_latest_recovery_data():
    context = {
        "source_notice": "x",
        "period_days": 28,
        "data_inventory": {"activity_count": 12, "health_days": 28, "sleep_days": 20, "hrv_days": 20},
        "summary_7d": {"activity_count": 4, "duration_hours": 5.2},
        "summary_28d": {"activity_count": 12, "duration_hours": 18.4},
        "recent_activities": [
            {"garmin": {"name": f"Run {i}", "distance_m": 10000 + i, "started_at": f"2026-09-{26-i:02d}T10:00:00+00:00"}, "pengucoach": {"blob": "x" * 900}}
            for i in range(12)
        ],
        "health_30d": [{"date": f"2026-09-{i:02d}", "resting_hr_bpm": 50 + i, "blob": "h" * 500} for i in range(1, 29)],
        "sleep_30d": [{"date": f"2026-09-{i:02d}", "duration_s": 25000 + i, "blob": "s" * 500} for i in range(1, 21)],
        "hrv_30d": [{"date": f"2026-09-{i:02d}", "overnight_ms": 40 + i, "blob": "v" * 500} for i in range(1, 21)],
        "body_profile": {"weight_kg": 70.0},
        "training_zones": {"running": {"z2": [120, 140]}},
    }
    payload, meta = _bounded_context(context, 6000)
    parsed = json.loads(payload)
    assert meta["context_truncated"] is True
    assert parsed["data_inventory"]["activity_count"] == 12
    assert parsed["summary_28d"]["activity_count"] == 12
    assert parsed["recent_activities"]
    assert parsed["recent_activities"][0]["garmin"]["name"] == "Run 0"
    assert parsed["hrv_30d"][-1]["date"] == "2026-09-20"
    assert parsed["health_30d"][-1]["date"] == "2026-09-28"
