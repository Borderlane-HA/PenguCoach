from pathlib import Path


def test_garmin_strength_mapping_is_persistent_and_catalog_backed():
    models = Path("pengucoach/db/models.py").read_text()
    migration = Path("db/migrations/versions/0007_garmin_exercise_mappings.py").read_text()
    gateway = Path("pengucoach/garmin/gateway/workouts.py").read_text()
    router = Path("apps/api/routers/garmin_workouts.py").read_text()

    assert "class GarminExerciseMapping" in models
    assert 'UniqueConstraint("user_id", "source_name_normalized")' in models
    assert 'revision = "0007_garmin_exercise_mappings"' in migration
    assert 'down_revision = "0006_body_profile_metrics"' in migration
    assert "def search_exercise_catalog" in gateway
    assert "def strength_exercise_validation" in gateway
    assert 'catalog_exercise_by_name("Total Body")' in gateway
    assert '"resolution": "generic_fallback"' in gateway
    assert '@router.get("/exercise-catalog")' in router
    assert '@router.put("/exercise-mappings")' in router
    assert '@router.delete("/exercise-mappings")' in router


def test_strength_export_uses_saved_mappings_and_generic_fallback_without_failing_session():
    gateway = Path("pengucoach/garmin/gateway/workouts.py").read_text()
    worker = Path("worker/tasks/garmin_workouts.py").read_text()

    # Stored user choices are considered before built-in language aliases.
    assert gateway.index("# 2) Per-user persisted choice.") < gateway.index("# 3) Curated language aliases")
    assert "allow_generic_fallback=True" in gateway
    assert '"TOTAL_BODY"' in gateway
    assert "gateway.upload_session, session, exercise_mappings" in worker
    assert "GARMIN_EXERCISE_NOT_FOUND" in gateway  # defensive path remains explicit


def test_calendar_surfaces_mapping_before_export_and_can_search_catalog():
    ui = Path("apps/web/components/TrainingPlanCalendar.tsx").read_text()
    css = Path("apps/web/app/globals.css").read_text()

    assert "function GarminExerciseMapper" in ui
    assert "/garmin/workout-export/exercise-catalog" in ui
    assert '/garmin/workout-export/exercise-mappings' in ui
    assert "Garmin-Zuordnung fehlt" in ui
    assert "fallback: Total Body" in ui
    assert "generic_fallback_count" in ui
    assert ".garmin-exercise-mapper" in css


def test_future_strength_plan_uses_concrete_movements_not_block_titles():
    structured = Path("pengucoach/training_plan/structured.py").read_text()
    assert "Each strength_exercises" in structured
    assert "never a circuit/block title" in structured


def test_version_surfaces_advance_together():
    assert 'version = "0.1.0-alpha.29"' in Path("pyproject.toml").read_text()
    assert '"version": "0.1.0-alpha.29"' in Path("apps/web/package.json").read_text()
    assert '__version__ = "0.1.0-alpha.29"' in Path("pengucoach/__init__.py").read_text()
    assert 'app_version: str = "0.1.0-alpha.29"' in Path("pengucoach/common/config.py").read_text()
