"""alpha.84: SparkyFitness tracks without usable distance, sparse-route matching, body trends, Sparky scale values, floors."""
import asyncio
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from pengucoach.coach.session_features import route_briefing
from pengucoach.coach.workout_review import nearest_on_track, route_match, route_metrics
from pengucoach.fit.service import serialize_series
from pengucoach.fit.track import device_distance_mode
from pengucoach.garmin.sync.service import _floors
from pengucoach.sparkyfitness import sync as sparky
from pengucoach.sparkyfitness.telemetry import frame

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"


def hike(dist_mode="zero", sparse=True, shift=0.0):
    """A ~6 km loop with hills; straights keep only every 9th point (Douglas-Peucker style)."""
    corners = [(0, 0), (0.012, 0.004), (0.018, 0.028), (0.004, 0.036), (0, 0)]
    pts = []
    for (a, b), (c, d) in zip(corners, corners[1:]):
        for i in range(40):
            if sparse and 6 <= i <= 34 and i % 9:
                continue
            f = i / 40
            pts.append((47.85 + a + (c - a) * f + shift, 12.12 + b + (d - b) * f))
    start = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    t, total, gps = start, 0.0, []
    for i, (lat, lon) in enumerate(pts):
        if i:
            p = pts[i - 1]
            step = 2 * 6371000 * math.asin(math.sqrt(math.sin(math.radians(lat - p[0]) / 2) ** 2 + math.cos(math.radians(p[0])) * math.cos(math.radians(lat)) * math.sin(math.radians(lon - p[1]) / 2) ** 2))
            total += step
            t += timedelta(seconds=step / 1.4)
        dist = {"zero": 0, "cumulative": total, "steps": step if i else 0}[dist_mode]
        gps.append({"t": t.isoformat().replace("+00:00", "Z"), "lat": lat, "lon": lon, "alt": 600 + 120 * math.sin(total / 1300), "hr": 110, "dist": dist})
    return {"sparkyfitness": {"_workout_telemetry": {"version": 1, "status": {"gps": "available"}, "gps": gps}}}, total


def rows(raw):
    return serialize_series(frame(raw), limit=5000)


def test_device_distance_is_only_trusted_when_it_fits_the_route():
    gps = 5000.0
    assert device_distance_mode(pd.Series([0, 0, 0, 0]), gps) == "gps"
    assert device_distance_mode(pd.Series([0, 1200, 2500, 4900]), gps) == "device"
    assert device_distance_mode(pd.Series([0, 1200, 1300, 1250, 1300]), gps) == "steps"
    assert device_distance_mode(pd.Series([0, 300, 600, 900]), gps) == "gps"  # far too short
    assert device_distance_mode(pd.Series([0, 300, 600, 900]), 0) == "device"  # no positions: keep it


def test_sparky_hike_with_zero_distance_gets_a_real_distance_axis():
    for mode in ("zero", "cumulative", "steps"):
        raw, total = hike(mode)
        data = rows(raw)
        km = [r["distance_km"] for r in data]
        assert all(b >= a for a, b in zip(km, km[1:])), mode
        assert abs(km[-1] * 1000 - total) / total < 0.1, mode


def test_briefing_and_metrics_bridge_sparse_moving_fixes():
    raw, _ = hike("zero")
    data = rows(raw)
    brief = route_briefing(data)
    assert brief["hills"], "simplified tracks must still show climbs"
    assert brief["metrics"]["distance_km"] > 5
    assert route_metrics(data).get("avg_hr") == 110


def test_sparse_and_dense_recordings_of_the_same_route_match():
    sparse, _ = hike("zero", sparse=True)
    dense, _ = hike("cumulative", sparse=False, shift=0.0002)  # ~20 m offset
    assert route_match(rows(sparse), rows(dense))
    assert route_match(rows(dense), rows(sparse))
    other, _ = hike("zero", shift=0.01)  # 1 km away: a different route
    assert route_match(rows(sparse), rows(other)) is None


def test_nearest_on_track_uses_the_line_not_only_the_fixes():
    index, gap = nearest_on_track((47.8550, 12.1200), [(47.85, 12.12), (47.86, 12.12)])
    assert gap < 1 and index in (0, 1)


def test_route_comparison_also_considers_sparky_recordings():
    source = (ROOT / "apps/api/routers/insights.py").read_text()
    assert "outerjoin(FitFile" in source and 'telemetry(a.raw).get("gps")' in source


def test_garmin_floors_from_summary_or_timeline():
    assert _floors({"floorsAscended": 12.4, "floorsDescended": 9.0}, None) == (12.4, 9.0)
    timeline = {"floorsValueDescriptorDTOList": [{"key": "startTimeGMT"}, {"key": "endTimeGMT"}, {"key": "ascended"}, {"key": "descended"}],
                "floorValuesArray": [["a", "b", 2, 1], ["c", "d", 3, 0]]}
    assert _floors({}, timeline) == (5.0, 1.0)
    assert _floors({}, None) == (None, None)


def test_sparky_scale_values_and_floors_are_read():
    source = (ROOT / "pengucoach/sparkyfitness/sync.py").read_text()
    assert '"muscle_mass_kg", "muscle_mass"' in source and '"bone_mass_kg", "bone_mass"' in source
    assert '"/generic-health/metrics"' in source and '"floors_ascended"' in source
    assert 'else "muscle" if "muscle" in label' in source and 'else "floors" if "floor" in label' in source


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def request(self, path, params=None):
        assert path == "/generic-health/metrics"
        return self.payload


class FakeDb:
    def __init__(self):
        self.rows = {}

    async def scalar(self, statement):
        return None

    def add(self, row):
        self.rows[row.date] = row


def test_sparky_daily_metrics_fill_floors():
    db = FakeDb()
    payload = {"data": [{"id": "1", "entry_date": "2026-10-20", "floors_ascended": 14, "floors_descended": 11, "total_steps": 9000}]}
    result = asyncio.run(sparky._sync_daily_metrics(db, FakeClient(payload), "u", datetime(2026, 10, 20).date(), datetime(2026, 10, 20).date()))
    assert result["available"] and result["fields_filled"] >= 2
    row = next(iter(db.rows.values()))
    assert row.floors_ascended == 14 and row.floors_descended == 11 and row.steps == 9000


def test_floors_reach_api_layouts_and_coach():
    from pengucoach.coach.today import TODAY_METRICS
    from pengucoach.health.layout import HEALTH_METRICS
    assert "floors" in TODAY_METRICS and "floors" in HEALTH_METRICS
    assert '"floors_ascended": x.floors_ascended' in (ROOT / "apps/api/routers/health.py").read_text()
    assert '"floors_ascended": row.floors_ascended' in (ROOT / "pengucoach/coach/context.py").read_text()
    assert (ROOT / "db/migrations/versions/0018_daily_floors.py").is_file()


def test_body_trend_skips_days_without_a_reading():
    chart = (WEB / "components/ProfessionalLineChart.tsx").read_text()
    page = (WEB / "app/health/page.tsx").read_text()
    assert "p.value==null" in chart and "connect" in chart
    assert "BODY_TRENDS" in page and "connect:true" in page
    for key in ("weight_kg", "body_fat_percent", "muscle_mass_kg", "body_water_percent", "bone_mass_kg"):
        assert key in page


def test_explorer_shows_values_on_the_map_and_hovers_along_the_route():
    explorer = (WEB / "components/ActivityExplorer.tsx").read_text()
    route_map = (WEB / "components/ActivityRouteMap.tsx").read_text()
    assert "overlay={readoutCard}" in explorer and "onHover={setHover}" in explorer
    assert "function closestOnRoute" in route_map and 'view.on("click",nearest);view.on("mousemove",move)' in route_map
    assert "requestAnimationFrame" in route_map
    assert "range-details" in explorer and "Auswahl fixieren" not in explorer
