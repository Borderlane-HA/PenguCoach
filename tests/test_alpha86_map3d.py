"""Alpha.86: 3D route map – wiring, key-less tiles, worker copy, fallbacks and help."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_maplibre_is_pinned_and_the_worker_is_copied_at_build_time():
    package = json.loads(read("package.json"))
    assert package["dependencies"]["maplibre-gl"] == "6.15.0"
    assert package["scripts"]["build"].startswith("node scripts/copy-maplibre-worker.mjs && next build")
    script = read("scripts/copy-maplibre-worker.mjs")
    assert "maplibre-gl-worker.mjs" in script and "public" in script and "process.exit(0)" in script
    assert "apps/web/public/vendor/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    # Docker and native installs both run `npm run build`, so the copy happens everywhere.
    assert "npm run build" in read("Dockerfile")
    assert "npm run build" in (ROOT / "install/proxmox/pengucoach-update.sh").read_text(encoding="utf-8")


def test_3d_map_is_loaded_on_demand_and_uses_the_copied_worker():
    explorer = read("components/ActivityExplorer.tsx")
    assert 'dynamic(()=>import("./ActivityRouteMap3D"),{ssr:false' in explorer
    assert "pengucoach_route_view" in explorer and "map-view-switch" in explorer
    assert 'view3dError==="NO_WEBGL"' in explorer
    component = read("components/ActivityRouteMap3D.tsx")
    assert 'await import("maplibre-gl")' in component
    assert "setWorkerUrl(WORKER)" in component and "/vendor/maplibre-gl-worker.mjs" in component
    assert '"raster-dem"' in component and 'encoding:"terrarium"' in component and "hillshade" in component
    assert "NO_WEBGL" in component and "onUnavailable" in component


def test_tiles_need_no_key():
    tiles = read("lib/map3d.ts")
    urls = re.findall(r'https://[^"\']+\{z\}/\{x\}/\{y\}\.png', tiles)
    assert len(urls) >= 5
    assert not re.search(r"key=|token=|access_token", tiles, re.I)
    assert "elevation-tiles-prod/terrarium" in tiles and "opentopomap" in tiles and "openstreetmap" in tiles


def test_flyover_and_controls_stop_cleanly():
    component = read("components/ActivityRouteMap3D.tsx")
    assert "lookAhead(" in component and "turnTowards(" in component and "positionAt(" in component
    assert "cancelAnimationFrame" in component and 'view.on("wheel",stop)' in component
    assert "now-lastEmit>120" in component, "the chart must not re-render every frame during a flyover"
    assert "map.current?.remove()" in component


def test_global_button_and_summary_styles_do_not_leak_into_map_controls():
    css = read("app/globals.css")
    assert ".map3d .maplibregl-ctrl button[aria-expanded]::before" in css
    assert ".map3d details.maplibregl-ctrl-attrib>summary.maplibregl-ctrl-attrib-button" in css
    assert ".map3d-tools button{background:var(--panel2)!important;color:var(--text)!important" in css


def test_help_and_changelog():
    help_text = read("lib/help.ts")
    assert "3D-Karte und Flyover" in help_text and "3D map and flyover" in help_text
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## 0.1.0-alpha.86") < changelog.index("## 0.1.0-alpha.85")
