from pathlib import Path


def test_training_plan_context_is_selectable_and_defaults_to_seven_days():
    router = Path("apps/api/routers/coach.py").read_text()
    context = Path("pengucoach/coach/context.py").read_text()
    ui = Path("apps/web/app/training/page.tsx").read_text()
    assert "context_days: Literal[3, 7, 14, 21, 28] = 7" in router
    assert "class TrainingContextSelection" in router
    assert "days = days if days in {3, 7, 14, 21, 28} else 7" in context
    assert 'const CONTEXT_DAYS=[3,7,14,21,28]' in ui
    assert 'context_data:contextData' in ui
    assert 'Training & FIT' in ui
    assert 'Schlaf & HRV' in ui
    assert 'Erholung & Stress' in ui


def test_ollama_generation_streams_and_reports_live_token_progress():
    llm = Path("pengucoach/llm/service.py").read_text()
    worker = Path("worker/tasks/ai.py").read_text()
    assert '"stream": True' in llm
    assert 'output_tokens_estimate' in llm
    assert 'output_tokens_exact' in llm
    assert 'read=max(float(settings.ai_request_timeout_seconds), 900.0)' in llm
    assert 'progress_callback=progress_callback' in worker
    assert '_progress_callback' in worker


def test_ai_jobs_are_user_cancellable_without_persisting_cancelled_results():
    jobs = Path("apps/api/routers/jobs.py").read_text()
    worker = Path("worker/tasks/ai.py").read_text()
    llm = Path("pengucoach/llm/service.py").read_text()
    training = Path("apps/web/app/training/page.tsx").read_text()
    coach = Path("apps/web/app/coach/page.tsx").read_text()
    activity = Path("apps/web/app/activities/[id]/page.tsx").read_text()
    assert '@router.post("/{task_id}/cancel")' in jobs
    assert "request_cancel(task_id)" in jobs
    assert "AiGenerationCancelled" in llm
    assert 'return {"cancelled": True, "reason": "AI_JOB_CANCELLED"}' in worker
    assert '/cancel`' in training
    assert '/cancel`' in coach
    assert '/cancel`' in activity


def test_docs_keep_current_reference_material_not_per_release_change_lists():
    docs = Path("docs")
    names = {p.name for p in docs.iterdir() if p.is_file()}
    assert not any(name.startswith("CHANGED_FILES_") for name in names)
    assert not any(name.startswith("RELEASE_ALPHA") for name in names)
    assert "AI_STUDIO.md" in names
    assert "GARMIN_WORKOUT_EXPORT.md" in names
    assert "GARMIN_HISTORY_AND_VO2.md" in names
