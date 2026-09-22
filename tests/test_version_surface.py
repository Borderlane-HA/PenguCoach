from pathlib import Path
import tomllib


def test_dashboard_exposes_resolved_application_version():
    auth = Path("apps/api/routers/auth.py").read_text()
    shell = Path("apps/web/components/AppShell.tsx").read_text()
    assert '"app_version": settings.resolved_app_version' in auth
    assert 'className="side-version"' in shell
    assert 'v{me.app_version}' in shell


def test_release_versions_are_aligned():
    project_version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    package_text = Path("apps/web/package.json").read_text()
    config_text = Path("pengucoach/common/config.py").read_text()
    init_text = Path("pengucoach/__init__.py").read_text()
    assert project_version == "0.1.0-alpha.15"
    assert '"version": "0.1.0-alpha.15"' in package_text
    assert 'app_version: str = "0.1.0-alpha.15"' in config_text
    assert '__version__ = "0.1.0-alpha.15"' in init_text
