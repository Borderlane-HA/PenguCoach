from pathlib import Path
import json
import re
import tomllib


def test_dashboard_exposes_resolved_application_version():
    auth = Path("apps/api/routers/auth.py").read_text()
    shell = Path("apps/web/components/AppShell.tsx").read_text()
    assert '"app_version": settings.resolved_app_version' in auth
    assert 'className="side-version"' in shell
    assert 'v{me.app_version}' in shell


def test_release_versions_are_aligned():
    project_version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    package_version = json.loads(Path("apps/web/package.json").read_text())["version"]
    config_text = Path("pengucoach/common/config.py").read_text()
    init_text = Path("pengucoach/__init__.py").read_text()
    config_match = re.search(r'app_version:\s*str\s*=\s*"([^"]+)"', config_text)
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    assert config_match is not None
    assert init_match is not None
    assert package_version == project_version
    assert config_match.group(1) == project_version
    assert init_match.group(1) == project_version
