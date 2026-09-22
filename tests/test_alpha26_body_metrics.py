from pathlib import Path

from pengucoach.sparkyfitness.sync import _height_cm, _kg


def test_scale_unit_helpers_accept_common_shapes():
    assert _height_cm(1.82) == 182.0
    assert _height_cm(182) == 182
    assert _kg(72000) == 72.0
    assert _kg(72) == 72


def test_body_measurement_model_tracks_smart_scale_metrics():
    model = Path("pengucoach/db/models.py").read_text()
    for field in (
        "weight_kg", "height_cm", "bmi", "body_fat_percent",
        "body_water_percent", "muscle_mass_kg", "bone_mass_kg",
    ):
        assert field in model
    migration = Path("db/migrations/versions/0006_body_profile_metrics.py").read_text()
    assert 'revision = "0006_body_profile_metrics"' in migration
    assert 'down_revision = "0005_sparkyfitness_connection"' in migration


def test_health_api_and_ui_expose_body_metrics_and_per_metric_sources():
    api = Path("apps/api/routers/health.py").read_text()
    health = Path("apps/web/app/health/page.tsx").read_text()
    today = Path("apps/web/app/today/page.tsx").read_text()
    assert '"body_latest"' in api
    assert '"sources": sources' in api
    assert 'body_fat_percent' in health
    assert 'bone_mass_kg' in health
    assert 'Muskelmasse' in health
    assert 'Schritte' in health
    assert 'body_fat_percent' in today
    assert 'Schritte' in today


def test_ai_context_contains_body_profile_and_daily_steps_provenance():
    context = Path("pengucoach/coach/context.py").read_text()
    assert '"body_profile": body' in context
    assert 'BODY_CONTEXT_FIELDS' in context
    assert '"steps": row.steps' in context
    assert 'item["sources"][field]' in context


def test_garmin_and_sparky_sync_capture_height_and_scale_metrics():
    garmin = Path("pengucoach/garmin/sync/service.py").read_text()
    sparky = Path("pengucoach/sparkyfitness/sync.py").read_text()
    worker = Path("worker/tasks/garmin_sync.py").read_text()
    assert '"bone_mass_kg"' in garmin
    assert 'upsert_garmin_profile' in garmin
    assert 'get_user_profile' in worker
    assert '"height_cm"' in sparky
    assert '"body_water_percent"' in sparky
    assert '"muscle_mass_kg"' in sparky
    assert '"bone_mass_kg"' in sparky
