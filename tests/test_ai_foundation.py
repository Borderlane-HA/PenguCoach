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
    assert TASK_DEFAULTS["activity_analysis"]["max_output_tokens"] == 3500
    assert TASK_DEFAULTS["training_plan"]["max_output_tokens"] == 4500
    assert TASK_DEFAULTS["activity_analysis"]["max_output_tokens"] <= 8192


def test_prompts_are_bilingual_and_deep_analysis_has_lookbacks():
    assert "3" in DEEP_ACTIVITY_PROMPT_DE and "7" in DEEP_ACTIVITY_PROMPT_DE
    assert "3" in DEEP_ACTIVITY_PROMPT_EN and "7" in DEEP_ACTIVITY_PROMPT_EN
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
