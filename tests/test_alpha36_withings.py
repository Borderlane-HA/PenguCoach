from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pengucoach.withings.client import authorization_url
from pengucoach.withings.sync import measurement_value


def test_withings_oauth_url_uses_read_scopes_and_state():
    url = authorization_url("client-1", "https://coach.example/api/v1/withings/oauth/callback", "csrf-state")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "account.withings.com"
    assert query["response_type"] == ["code"]
    assert query["state"] == ["csrf-state"]
    assert query["scope"] == ["user.info,user.metrics,user.activity"]


def test_withings_measurement_decimal_exponent_is_decoded():
    assert measurement_value({"value": 73125, "unit": -3}) == 73.125
    assert measurement_value({"value": 183, "unit": -1}) == 18.3


def test_withings_connection_surface_and_migration_exist():
    model = Path("pengucoach/db/models.py").read_text()
    migration = Path("db/migrations/versions/0009_withings_connection.py").read_text()
    api = Path("apps/api/routers/withings.py").read_text()
    main = Path("apps/api/main.py").read_text()
    assert "class WithingsConnection" in model
    assert 'down_revision = "0008_sparkyfitness_auto_sync"' in migration
    assert '@router.get("/oauth/callback")' in api
    assert 'SecretBox().encrypt(payload.client_secret)' in api
    assert '@router.delete("/local-data")' in api
    assert "withings.router" in main


def test_withings_autosync_is_registered():
    scheduler = Path("worker/tasks/scheduler.py").read_text()
    celery = Path("worker/celery_app.py").read_text()
    assert "schedule_due_withings_syncs" in scheduler
    assert "WithingsConnection.auto_sync_enabled" in scheduler
    assert "sync_withings_user.apply_async" in scheduler
    assert "schedule-due-withings-syncs" in celery
    assert '"worker.tasks.withings_sync"' in celery


def test_withings_frontend_is_in_connections_navigation():
    page = Path("apps/web/app/settings/withings/page.tsx").read_text()
    shell = Path("apps/web/components/AppShell.tsx").read_text()
    assert 'href:"/settings/withings"' in shell
    assert '"/withings/oauth/start"' in page
    assert '"/withings/sync/now"' in page
    assert "auto_sync_enabled" in page
    assert "Withings, Garmin, SparkyFitness" in page


def test_source_priority_is_visible_in_health_and_garmin_merge():
    health = Path("apps/api/routers/health.py").read_text()
    coach = Path("pengucoach/coach/context.py").read_text()
    garmin = Path("pengucoach/garmin/sync/service.py").read_text()
    assert 'source_priority = {"withings": 40, "garmin": 30, "sparkyfitness": 20, "manual": 10}' in health
    assert 'source_priority = {"withings": 40, "garmin": 30, "sparkyfitness": 20, "manual": 10}' in coach
    assert 'if sources.get(field) == "withings"' in garmin
