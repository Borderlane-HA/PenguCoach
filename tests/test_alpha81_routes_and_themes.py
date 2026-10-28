"""alpha.81: simplified SparkyFitness tracks keep their straight stretches."""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pengucoach.fit import track
from pengucoach.sparkyfitness import telemetry

ROOT = Path(__file__).resolve().parents[1]


def loop_points():
    """A 4 km square loop at 3 m/s, simplified like SparkyFitness: dense at corners, sparse on straights."""
    t0 = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    side = 1000.0
    corners = [(0, 0), (side, 0), (side, side), (0, side), (0, 0)]
    pts, elapsed = [], 0.0
    deg = 111_320.0
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        # Douglas-Peucker leaves a few points near the corners and none in between.
        for f in (0.0, 0.01, 0.02, 0.98, 0.99):
            x, y = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
            pts.append({"t": (t0 + timedelta(seconds=elapsed + side * f / 3.0)).isoformat().replace("+00:00", "Z"),
                        "lat": 48 + y / deg, "lon": 11 + x / (deg * math.cos(math.radians(48)))})
        elapsed += side / 3.0
    pts.append({"t": (t0 + timedelta(seconds=elapsed)).isoformat().replace("+00:00", "Z"), "lat": 48.0, "lon": 11.0})
    return pts


def raw(points):
    return {"sparkyfitness": {telemetry.KEY: {"version": 1, "gps": points}}}


def test_simplified_loop_is_one_line_with_full_distance():
    df = telemetry.frame(raw(loop_points()))
    assert df["track_segment"].nunique() == 1, "straight stretches minutes apart must not split the route"
    assert abs(df["distance"].max() - 4000) < 20
    assert abs(track.moving_seconds(df) - 4000 / 3.0) < 30
    speeds = df["speed"].dropna()
    assert len(speeds) >= len(df) - 1 and speeds.between(2.5, 3.5).all()


def test_pause_at_one_place_is_not_moving_time():
    t0 = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    pts = [{"t": (t0 + timedelta(seconds=i)).isoformat(), "lat": 48 + i * 3 / 111_320, "lon": 11.0} for i in range(60)]
    last = pts[-1]
    pts += [{"t": (t0 + timedelta(seconds=660 + i)).isoformat(), "lat": last["lat"] + i * 3 / 111_320, "lon": 11.0} for i in range(60)]
    df = telemetry.frame(raw(pts))
    assert df["track_segment"].nunique() == 1
    assert abs(track.moving_seconds(df) - 118) <= 3


def test_frontend_and_recap_wiring():
    js = (ROOT / "apps/web/lib/activityExplorer.ts").read_text()
    assert "metresBetween(previous.lat,previous.lon,lat,lon)/gap > 45" in js
    router = (ROOT / "apps/api/routers/activities.py").read_text()
    assert "_sparky_recap_routes(raws)" in router
    from apps.api.routers.activities import _sparky_recap_routes
    routes = _sparky_recap_routes([("a", raw(loop_points())), ("b", {"sparkyfitness": {}})])
    assert [r["id"] for r in routes] == ["a"] and len(routes[0]["points"]) > 10


def test_new_themes_are_registered_everywhere():
    css = (ROOT / "apps/web/app/globals.css").read_text()
    page = (ROOT / "apps/web/app/settings/appearance/page.tsx").read_text()
    api = (ROOT / "apps/api/routers/settings.py").read_text()
    theme = (ROOT / "apps/web/lib/theme.ts").read_text()
    for name in ("nightrun", "daylight", "carbon", "dusk"):
        assert f'html[data-theme="{name}"]{{color-scheme' in css
        assert f'id:"{name}"' in page and f'"{name}"' in api and f"|{name}" in api
    for name in ("nightrun", "carbon", "dusk"):
        assert f'"{name}"' in theme.split("DARK_THEMES=")[1].split("]")[0]
    layout = (ROOT / "apps/web/app/layout.tsx").read_text()
    assert '@fontsource-variable/inter' in layout and '@fontsource-variable/space-grotesk' in layout
    assert "--font-display" in css


def test_theme_contrast():
    import re

    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b):
        x, y = lum(a), lum(b)
        return (max(x, y) + .05) / (min(x, y) + .05)

    css = (ROOT / "apps/web/app/globals.css").read_text()
    for name in ("nightrun", "daylight", "carbon", "dusk"):
        block = re.search(r'html\[data-theme="%s"\]\{color-scheme[^}]*\}' % name, css).group(0)
        v = dict(re.findall(r"--([a-z0-9-]+):(#[0-9a-f]{6})", block))
        for surface in ("bg", "panel", "panel2", "panel3"):
            assert ratio(v["text"], v[surface]) >= 7, (name, surface)
            for fg in ("muted", "muted-2", "accent"):
                assert ratio(v[fg], v[surface]) >= 4.5, (name, fg, surface)


def test_theme_aware_chips_and_recap_button():
    css = (ROOT / "apps/web/app/globals.css").read_text()
    assert ".activity-summary-strip>div{background:var(--panel)}" in css
    assert '[data-theme="carbon"]' in css.split(".recap-trigger{background:color-mix")[0].rsplit("\n", 1)[-1]
