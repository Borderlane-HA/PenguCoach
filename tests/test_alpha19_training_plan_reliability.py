from pathlib import Path


def test_training_token_input_accepts_8000_exactly():
    ui = Path("apps/web/app/training/page.tsx").read_text()
    assert 'step={1} value={tokens}' in ui
    assert 'step={128} value={tokens}' not in ui
    assert "pro KI-Aufruf/Planabschnitt" in ui


def test_ollama_structured_training_plan_uses_schema_and_disables_thinking():
    llm = Path("pengucoach/llm/service.py").read_text()
    worker = Path("worker/tasks/ai.py").read_text()
    structured = Path("pengucoach/training_plan/structured.py").read_text()
    assert 'response_format_schema: dict[str, Any] | None = None' in llm
    assert 'ollama_payload["think"] = False' in llm
    assert 'ollama_payload["format"] = response_format_schema' in llm
    assert "TrainingPlanDocument.model_json_schema()" in worker
    assert "wrapper is optional" in structured


def test_training_segments_get_generous_budget_and_full_budget_retry():
    worker = Path("worker/tasks/ai.py").read_text()
    assert "max(3500, segment_sessions * 420 + 800)" in worker
    assert "retry_budget = requested_max" in worker
    assert "def parse_segment" in worker
    assert "SEGMENT_SESSION_COUNT" in worker
    # A raw truncation flag alone must no longer fail before parsing the JSON.
    parse_pos = worker.index("segment, segment_error = parse_segment(answer_part)")
    fail_pos = worker.index('raise RuntimeError(f"TRAINING_PLAN_SEGMENT_TRUNCATED:{start_week}-{end_week}")')
    assert parse_pos < fail_pos


def test_training_segment_failures_are_human_readable_in_ui():
    ui = Path("apps/web/app/training/page.tsx").read_text()
    assert "friendlyPlanError" in ui
    assert "TRAINING_PLAN_SEGMENT_TRUNCATED" in ui
    assert "TRAINING_PLAN_SEGMENT_INVALID" in ui
