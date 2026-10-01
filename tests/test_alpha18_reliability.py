from pathlib import Path


def test_ai_studio_has_first_class_ionos_gemini_and_xai_presets():
    router = Path("apps/api/routers/admin_ai.py").read_text()
    llm = Path("pengucoach/llm/service.py").read_text()
    ui = Path("apps/web/app/admin/ai/page.tsx").read_text()
    assert "ionos|gemini|xai" in router
    assert '"ionos": "https://openai.inference.de-txl.ionos.com/v1"' in llm
    assert '"gemini": "https://generativelanguage.googleapis.com/v1beta/openai"' in llm
    assert '"xai": "https://api.x.ai/v1"' in llm
    assert 'option value="ionos"' in ui
    assert 'option value="gemini"' in ui
    assert 'option value="xai"' in ui


def test_history_cancel_can_hard_stop_stuck_task_and_clear_lock():
    router = Path("apps/api/routers/garmin.py").read_text()
    worker = Path("worker/tasks/garmin_sync.py").read_text()
    service = Path("pengucoach/garmin/sync/service.py").read_text()
    ui = Path("apps/web/app/settings/garmin/page.tsx").read_text()
    assert "task_id: str | None" in router
    assert 'terminate=True, signal="SIGTERM"' in router
    assert "force_clear_history_import_state" in router
    assert "current_history_import_task" in router
    assert "_discover_history_task_id" in router
    assert "inspector.active" in router
    assert "pengucoach:garmin-history-task:" in worker
    assert '"task_id": task_id' in worker
    assert "redis.delete(_history_control_key(user_id), _account_lock_key(user_id), _history_task_key(user_id))" in worker
    assert "asyncio.wait_for(asyncio.to_thread(func), timeout=timeout_seconds)" in service
    assert "GarminRequestTimeout" in service
    assert 'task_id:id' in ui
    assert "Sofort abbrechen" in ui


def test_training_plan_output_is_not_capped_by_task_default_and_large_plans_chunk():
    llm = Path("pengucoach/llm/service.py").read_text()
    worker = Path("worker/tasks/ai.py").read_text()
    ui = Path("apps/web/app/training/page.tsx").read_text()
    assert "Route budgets are task defaults, not a hidden ceiling" in llm
    assert "min(\n        configured_max" not in llm
    assert "chunked = expected_sessions > 12" in worker
    assert "merge_plan_segments" in worker
    assert "TRAINING_PLAN_SEGMENT_TRUNCATED" in worker
    assert "modelOutMax" in ui
    assert "Wochenblöcke" in ui
