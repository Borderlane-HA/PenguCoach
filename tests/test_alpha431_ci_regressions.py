from pathlib import Path
import json
import re
import tomllib



def test_alpha431_python_package_version_is_pep440_and_cross_surface_aligned():
    project_version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    web_version = json.loads(Path("apps/web/package.json").read_text())["version"]
    config = Path("pengucoach/common/config.py").read_text()
    init = Path("pengucoach/__init__.py").read_text()

    assert project_version == "0.1.0-alpha.43.post1"
    assert web_version == project_version
    assert f'app_version: str = "{project_version}"' in config
    assert f'__version__ = "{project_version}"' in init
    assert 'return f"{match.group(1)}-alpha.{match.group(2)}.{match.group(3)}"' in config


def test_alpha431_training_active_job_fallback_keeps_anyobj_type():
    training = Path("apps/web/app/training/page.tsx").read_text()
    assert 'catch(():AnyObj=>({active:false}))' in training
    assert 'a?.task_id' in training
