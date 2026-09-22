from pathlib import Path


def test_history_import_pages_activity_catalog_until_exhausted():
    worker = Path("worker/tasks/garmin_sync.py").read_text()
    assert "gateway.get_activities_page" in worker
    assert "offset += len(rows)" in worker
    assert "count_activities(" not in worker
    assert "include_activities=False" in worker


def test_history_import_is_resume_safe_and_reports_progress():
    worker = Path("worker/tasks/garmin_sync.py").read_text()
    assert 'SourceRecord.domain == "history_day_complete"' in worker
    assert '"history_day_complete"' in worker
    assert '"history_day_core_complete"' in worker
    assert 'HISTORY_FULL_DETAIL_DAYS = 90' in worker
    assert 'detail_level=detail_level' in worker
    assert 'set_history_import_control' in worker
    assert '_check_history_import_control' in worker
    assert 'bind=True, name="worker.tasks.garmin_sync.historical_import"' in worker
    assert "self.update_state(state=\"PROGRESS\"" in worker
    assert "_account_lock" in worker


def test_large_history_uses_batch_activity_upsert():
    service = Path("pengucoach/garmin/sync/service.py").read_text()
    assert "Activity.garmin_activity_id.in_(ids)" in service
    assert "Batch-loading" in service


def test_fit_backfill_has_duplicate_work_guard_and_large_queue_pacing():
    worker = Path("worker/tasks/fit.py").read_text()
    history = Path("worker/tasks/garmin_sync.py").read_text()
    assert 'f"pengucoach:fit:{activity_id}"' in worker
    assert 'f"pengucoach:garmin-account:{user_id}"' in worker
    assert 'activity.fit_status == "parsed"' in worker
    assert 'rate_limit="30/m"' in worker
    assert 'GarminConnectTooManyRequestsError' in worker
    assert 'countdown=index * 2' not in history


def test_activity_ai_context_is_not_dropped_when_budget_is_tight():
    service = Path("pengucoach/llm/service.py").read_text()
    assert 'compact["activity"] = None' not in service
    assert '"activity_analysis": 3072' in service
    assert '"output_budget_adjusted": output_budget_adjusted' in service


def test_bulk_activity_catalog_really_pages_past_200(monkeypatch):
    import asyncio
    import sys
    import types
    from types import SimpleNamespace

    try:
        import garminconnect  # noqa: F401
    except ImportError:
        stub = types.ModuleType("garminconnect")
        stub.Garmin = type("Garmin", (), {})
        stub.GarminConnectAuthenticationError = type("GarminConnectAuthenticationError", (Exception,), {})
        stub.GarminConnectTooManyRequestsError = type("GarminConnectTooManyRequestsError", (Exception,), {})
        sys.modules["garminconnect"] = stub
    try:
        import celery  # noqa: F401
    except ImportError:
        celery_stub = types.ModuleType("celery")
        def shared_task(*args, **kwargs):
            def decorate(fn):
                return fn
            return decorate
        celery_stub.shared_task = shared_task
        sys.modules["celery"] = celery_stub
    try:
        import redis  # noqa: F401
    except ImportError:
        redis_stub = types.ModuleType("redis")
        redis_stub.Redis = type("Redis", (), {"from_url": classmethod(lambda cls, *a, **k: cls())})
        sys.modules["redis"] = redis_stub
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        session_stub = types.ModuleType("pengucoach.db.session")
        session_stub.SessionLocal = None
        sys.modules["pengucoach.db.session"] = session_stub

    import worker.tasks.garmin_sync as sync

    activities = [
        {
            "activityId": 10_000 - i,
            "startTimeGMT": f"2026-{9 - (i // 90):02d}-{28 - (i % 20):02d}T10:00:00Z",
            "activityName": f"Activity {i}",
            "activityType": {"typeKey": "running"},
        }
        for i in range(350)
    ]

    class Gateway:
        def __init__(self):
            self.calls = []

        def get_activities_page(self, start=0, limit=100):
            self.calls.append((start, limit))
            return activities[start:start + limit]

    class DB:
        async def commit(self):
            return None

    imported_ids = []

    async def fake_upsert(db, user, rows):
        imported_ids.extend(int(row["activityId"]) for row in rows)
        return len(rows), []

    async def fake_store(*args, **kwargs):
        return None

    monkeypatch.setattr(sync, "_upsert_activities", fake_upsert)
    monkeypatch.setattr(sync, "_store_raw", fake_store)

    gateway = Gateway()
    run = SimpleNamespace(requests_made=0, records_read=0, records_inserted=0, domains={})
    result = asyncio.run(sync._import_activity_catalog(DB(), SimpleNamespace(id="user"), gateway, None, None, run))

    assert result["matched"] == 350
    assert result["pages"] == 4
    assert result["stop_reason"] == "empty_page"
    assert len(set(imported_ids)) == 350
    assert gateway.calls[:5] == [(0, 100), (100, 100), (200, 100), (300, 100), (350, 100)]
