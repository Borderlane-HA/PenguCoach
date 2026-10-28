from pathlib import Path


def test_sparkyfitness_repository_surface_is_complete():
    required = [
        Path("pengucoach/sparkyfitness/__init__.py"),
        Path("pengucoach/sparkyfitness/client.py"),
        Path("pengucoach/sparkyfitness/sync.py"),
        Path("apps/api/routers/sparkyfitness.py"),
        Path("worker/tasks/sparkyfitness_sync.py"),
        Path("apps/web/app/settings/sparkyfitness/page.tsx"),
        Path("db/migrations/versions/0005_sparkyfitness_connection.py"),
    ]
    missing = [str(p) for p in required if not p.is_file()]
    assert not missing, f"Missing SparkyFitness files: {missing}"


def test_app_shell_contains_sparkyfitness_navigation():
    shell = Path("apps/web/components/AppShell.tsx").read_text()
    assert "/settings/sparkyfitness" in shell
