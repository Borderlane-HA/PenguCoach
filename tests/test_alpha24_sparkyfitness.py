from pathlib import Path

from pengucoach.sparkyfitness.client import normalize_base_url


def test_sparkyfitness_url_normalization_accepts_frontend_and_swagger_urls():
    assert normalize_base_url("https://fitness.example.com") == "https://fitness.example.com/api"
    assert normalize_base_url("https://fitness.example.com/api") == "https://fitness.example.com/api"
    assert normalize_base_url("https://fitness.example.com/api/api-docs/swagger/") == "https://fitness.example.com/api"


def test_sparkyfitness_url_rejects_credentials_and_non_http_schemes():
    for value in ("file:///tmp/x", "ftp://fitness.example.com", "https://user:pass@fitness.example.com"):
        try:
            normalize_base_url(value)
        except ValueError as exc:
            assert str(exc) == "SPARKYFITNESS_URL_INVALID"
        else:
            raise AssertionError(value)


def test_sparkyfitness_integration_is_explicitly_read_only():
    client = Path("pengucoach/sparkyfitness/client.py").read_text()
    router = Path("apps/api/routers/sparkyfitness.py").read_text()
    page = Path("apps/web/app/settings/sparkyfitness/page.tsx").read_text()
    assert "async def request" in client
    assert "client.get(" in client
    assert "client.post(" not in client
    assert '"read_only": True' in router
    assert "read-only" in page.lower()


def test_sparkyfitness_api_key_is_encrypted_and_never_returned():
    router = Path("apps/api/routers/sparkyfitness.py").read_text()
    model = Path("pengucoach/db/models.py").read_text()
    assert "api_key_ciphertext" in model
    assert "SecretBox().encrypt(payload.api_key)" in router
    assert '"api_key"' not in router.split('@router.get("/status")', 1)[1].split('@router.post("/connect")', 1)[0]


def test_sparkyfitness_migration_and_worker_are_wired():
    migration = Path("db/migrations/versions/0005_sparkyfitness_connection.py").read_text()
    celery = Path("worker/celery_app.py").read_text()
    main = Path("apps/api/main.py").read_text()
    assert 'down_revision = "0004_garmin_workout_export"' in migration
    assert '"worker.tasks.sparkyfitness_sync"' in celery
    assert "sparkyfitness.router" in main


def test_sparkyfitness_is_visible_next_to_garmin_in_navigation():
    shell = Path("apps/web/components/AppShell.tsx").read_text()
    assert '/settings/garmin' in shell
    assert '/settings/sparkyfitness' in shell
    assert 'label:"SparkyFitness"' in shell
