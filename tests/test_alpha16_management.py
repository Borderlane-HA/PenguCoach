from pathlib import Path


def test_training_plan_and_ai_history_have_delete_surfaces():
    coach = Path("apps/api/routers/coach.py").read_text()
    training = Path("apps/web/app/training/page.tsx").read_text()
    activity = Path("apps/web/app/activities/[id]/page.tsx").read_text()
    assert '@router.delete("/ai-runs/{run_id}")' in coach
    assert '@router.delete("/training-plans/{run_id}")' in coach
    assert '@router.get("/training-plans/{run_id}/delete-info")' in coach
    assert "Auch aus Garmin löschen" in training
    assert "Nur in PenguCoach löschen" in training
    assert "/coach/ai-runs/" in activity


def test_garmin_plan_cleanup_unschedules_before_template_delete():
    gateway = Path("pengucoach/garmin/gateway/workouts.py").read_text()
    worker = Path("worker/tasks/garmin_workouts.py").read_text()
    router = Path("apps/api/routers/garmin_workouts.py").read_text()
    assert "def unschedule_workout" in gateway
    assert "gateway.unschedule_workout" in worker
    assert worker.index("gateway.unschedule_workout") < worker.index("gateway.delete_workout", worker.index("async def _delete_plan_from_garmin"))
    assert 'name="worker.tasks.garmin_workouts.delete_plan"' in worker
    assert 'delete-plan/{plan_run_id}/jobs' in router


def test_history_import_has_optimized_mode_and_pause_cancel():
    router = Path("apps/api/routers/garmin.py").read_text()
    worker = Path("worker/tasks/garmin_sync.py").read_text()
    service = Path("pengucoach/garmin/sync/service.py").read_text()
    ui = Path("apps/web/app/settings/garmin/page.tsx").read_text()
    assert 'mode: Literal["optimized", "full"] = "optimized"' in router
    assert '@router.post("/import/control")' in router
    assert 'HISTORY_FULL_DETAIL_DAYS = 90' in worker
    assert 'HistoryImportInterrupted' in worker
    assert 'history_day_core_complete' in worker
    assert 'detail_level: str = "full"' in service
    assert 'core_history = detail_level == "core"' in service
    assert 'Optimiert (empfohlen)' in ui
    assert 'controlImport("pause")' in ui
    assert 'controlImport("cancel")' in ui


def test_training_plan_model_receives_effective_hard_output_budget():
    llm = Path("pengucoach/llm/service.py").read_text()
    structured = Path("pengucoach/training_plan/structured.py").read_text()
    worker = Path("worker/tasks/ai.py").read_text()
    assert "HARD OUTPUT BUDGET" in llm
    assert "expected_sessions" in llm
    assert "NEVER omit requested weeks/sessions" in llm
    assert "Close the JSON object" in structured
    assert '"requested_max_output_tokens": answer.get("requested_max_output_tokens")' in worker
    assert "self.retry" in worker


def test_sidebar_version_is_left_aligned():
    css = Path("apps/web/app/globals.css").read_text()
    assert ".side-version{padding:0 9px 2px;text-align:left;" in css
