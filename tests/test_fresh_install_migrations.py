from pathlib import Path


def test_fresh_installer_bootstraps_current_schema_before_stamping():
    script = Path("install/proxmox/install-app.sh").read_text()
    assert "Fresh database detected; creating current schema" in script
    assert ".venv/bin/python install/proxmox/bootstrap-db.py" in script
    assert ".venv/bin/alembic -c alembic.ini stamp head" in script
    assert "Existing database detected; applying Alembic migrations" in script


def test_ai_runs_historical_migration_is_idempotent():
    migration = Path("db/migrations/versions/0002_ai_runs.py").read_text()
    assert 'if "ai_runs" in inspector.get_table_names()' in migration


def test_vo2_migration_reports_missing_baseline_cleanly():
    migration = Path("db/migrations/versions/0003_activity_vo2max.py").read_text()
    assert 'if "activities" not in inspector.get_table_names()' in migration
    assert "baseline schema is missing table 'activities'" in migration
