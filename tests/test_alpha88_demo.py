"""Alpha.88: public demo on GitHub Pages – static export, fake data, base path, workflow."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_workflow_builds_and_deploys_pages():
    flow = (ROOT / ".github/workflows/demo-pages.yml").read_text(encoding="utf-8")
    for needed in ("pages: write", "id-token: write", "actions/upload-pages-artifact", "actions/deploy-pages", "npm run build:demo",
                   "path: apps/web/out", "DEMO_BASE_PATH: /${{ github.event.repository.name }}", "workflow_dispatch", "tests/demo.test.cjs"):
        assert needed in flow, needed


def test_demo_build_is_separate_from_normal_installs():
    config = read("next.config.ts")
    assert 'output: "export"' in config and "trailingSlash: true" in config and 'output: "standalone"' in config
    assert 'process.env.NEXT_PUBLIC_DEMO === "1"' in config
    package = json.loads(read("package.json"))
    assert package["scripts"]["build"] == "node scripts/copy-maplibre-worker.mjs && next build"
    assert package["scripts"]["build:demo"] == "node scripts/build-demo.mjs"
    script = read("scripts/build-demo.mjs")
    assert "NEXT_PUBLIC_DEMO" in script and ".nojekyll" in script and "rmSync(target" in script
    api = read("lib/api.ts")
    assert "if(DEMO&&typeof window!==\"undefined\")installDemo();" in api
    layout = read("app/activities/[id]/layout.tsx")
    assert 'if(process.env.NEXT_PUBLIC_DEMO!=="1")return [];' in layout
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "apps/web/public/demo-data/" in gitignore and "apps/web/out/" in gitignore


def test_navigation_respects_the_base_path():
    offenders = []
    for path in list((WEB / "app").rglob("*.tsx")) + list((WEB / "components").rglob("*.tsx")) + list((WEB / "lib").rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"location\.(replace|assign)\(([^;]*?)\)|location\.href=([^;}]+)", text):
            if "withBase(" not in match.group(0):
                offenders.append(f"{path.relative_to(WEB)}: {match.group(0)[:60]}")
        if re.search(r'src="/(?!/)', text):
            offenders.append(f"{path.relative_to(WEB)}: absolute src")
    assert not offenders, offenders
    assert 'withBase("/vendor/maplibre-gl-worker.mjs")' in read("components/ActivityRouteMap3D.tsx")


def test_demo_is_read_only_and_labelled():
    demo = read("lib/demo.ts")
    assert "DEMO_READ_ONLY" in demo and "403" in demo and "shiftDays" in demo
    shell = read("components/AppShell.tsx")
    assert "demo-banner" in shell and "Erfundene Daten" in shell
    data = WEB / "demo/data"
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    assert index["recorded"] and len(index["entries"]) > 100
    me = json.loads((data / index["entries"]["/auth/me"]).read_text(encoding="utf-8"))["/auth/me"]
    user = me.get("user", me)
    assert len(list(data.iterdir())) < 20
    assert user["username"] == "Pia" and user["role"] != "admin"


def test_docs_help_readme_and_changelog():
    assert "borderlane-ha.github.io/PenguCoach" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Settings → Pages → Source: GitHub Actions" in (ROOT / "docs/DEMO.md").read_text(encoding="utf-8")
    help_text = read("lib/help.ts")
    assert "Live-Demo auf GitHub" in help_text and "Live demo on GitHub" in help_text
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## 0.1.0-alpha.88") < changelog.index("## 0.1.0-alpha.87")
