from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_training_jobs_are_tracked_and_duplicate_guarded_server_side():
    coach = text("apps/api/routers/coach.py")
    assert 'job_type="training_plan"' in coach
    assert 'status": "already_running"' in coach
    assert 'BackgroundJob.created_at >= cutoff' in coach
    assert 'AsyncResult(str(row.id), app=celery_app)' in coach


def test_active_job_lookup_is_user_scoped_and_recent():
    jobs = text("apps/api/routers/jobs.py")
    assert '@router.get("/active")' in jobs
    assert 'BackgroundJob.user_id == user.id' in jobs
    assert 'BackgroundJob.job_type == job_type' in jobs
    assert 'timedelta(hours=12)' in jobs
    assert '"summary": {' in jobs


def test_training_page_restores_server_job_and_keeps_it_visible():
    page = text("apps/web/app/training/page.tsx")
    assert '/jobs/active?job_type=training_plan' in page
    assert 'training-running-job' in page
    assert 'PLANERSTELLUNG LÄUFT' in page
    assert 'Plan wird bereits erstellt' in page
    assert 'showRunningJob' in page
    assert 'disabled={busy||jobLookup||!model||!isMonday(planStart)}' in page


def test_running_job_has_mobile_layout():
    css = text("apps/web/app/globals.css")
    assert '.training-running-job' in css
    assert '.training-running-job-actions' in css
    assert '@media(max-width:760px){.training-running-job' in css
    assert '@media(max-width:480px){.training-running-job' in css
