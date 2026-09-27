"""Regression coverage for retiring the connector introduced in alpha.36."""
from pathlib import Path
from pengucoach.db.models import Base
from apps.api.main import app
from worker.celery_app import app as celery

def test_retired_connector_has_no_routes_schedules_or_credentials_model():
    assert not any("/withings" in getattr(route, "path", "") for route in app.routes)
    assert "withings_connections" not in Base.metadata.tables
    assert not any("withings" in key for key in celery.conf.beat_schedule)
    assert "withings.router" not in Path("apps/api/main.py").read_text()
    assert 'href:"/settings/withings"' not in Path("apps/web/components/AppShell.tsx").read_text()

def test_upgrade_retains_historical_chain_and_retires_credentials():
    migration = Path("db/migrations/versions/0010_retire_withings.py").read_text()
    assert 'down_revision = "0009_withings_connection"' in migration
    assert 'op.drop_table("withings_connections")' in migration
    for path in ("pengucoach/withings/client.py", "pengucoach/withings/sync.py", "worker/tasks/withings_sync.py"):
        assert "import" not in Path(path).read_text()
