import json

from pengucoach.fit.activity_detail import selected_garmin_extras
from pengucoach.llm.service import DEEP_ACTIVITY_PROMPT, TASK_DEFAULTS, TRAINING_PLAN_PROMPT, _bounded_context


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


def test_ai_task_defaults_include_cost_limits_and_prompts():
    assert TASK_DEFAULTS["activity_analysis"]["max_output_tokens"] <= 8192
    assert TASK_DEFAULTS["training_plan"]["max_output_tokens"] <= 8192
    assert "previous 3" in DEEP_ACTIVITY_PROMPT
    assert "periodized" in TRAINING_PLAN_PROMPT


def test_context_budget_keeps_valid_json():
    context = {"source_notice": "x", "recent_activities": [{"n": i, "text": "x" * 500} for i in range(100)]}
    payload, meta = _bounded_context(context, 6000)
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    assert meta["context_chars"] <= 6000
    assert meta["context_truncated"] is True
