"""Alpha.87: tour planner – waypoints, BRouter parsing, scoring, client errors and wiring."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import httpx
import pytest

from pengucoach.tours import brouter, planner

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"
START = (50.1109, 8.6821)


def geojson(coords, messages=None, length=None, ascend=None):
    """A BRouter answer as FormatJson writes it (numbers as strings, messages with header row)."""
    props = {"creator": "BRouter-1.7.8", "name": "brouter_trekking_0", "track-length": str(length if length is not None else 0),
             "filtered ascend": str(ascend if ascend is not None else 0), "plain-ascend": "0", "total-time": "0", "total-energy": "0", "cost": "1"}
    props["messages"] = messages or [["Longitude", "Latitude", "Elevation", "Distance", "CostPerKm", "ElevCost", "TurnCost", "NodeCost",
                                      "InitialCost", "WayTags", "NodeTags", "Time", "Energy"]]
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": coords}}]}


def test_loop_waypoints_start_and_end_at_home_on_a_circle():
    points = planner.loop_waypoints(*START, bearing=90, radius_m=2000, points=4)
    assert points[0] == START and points[-1] == START and len(points) == 6
    centre = planner.destination(*START, 90, 2000)
    for p in points[1:-1]:
        assert abs(planner.metres(centre, p) - 2000) < 2
    # The loop lies east of the start when the bearing is 90°.
    assert all(p[1] > START[1] for p in points[1:-1])


def test_radius_guess_and_rescale():
    r = planner.first_radius("road_bike", 60000)
    assert 7000 < r < 8500
    assert planner.next_radius(1000, 30000, 60000) == 500
    assert planner.next_radius(1000, 30000, 10000) == 1800  # capped
    assert planner.fits(40000, 42000) and not planner.fits(40000, 46000)


def test_variant_directions():
    assert planner.variant_bearings(3, None, 0) == [0, 120, 240]
    assert planner.variant_bearings(3, 90, 0) == [90, 45, 135]
    assert planner.variant_bearings(3, None, 1) != planner.variant_bearings(3, None, 0)


def test_profiles_and_wishes():
    assert planner.profile_for("road_bike", [])[0] == "fastbike"
    assert planner.profile_for("road_bike", ["low_traffic"])[0] == "fastbike-verylowtraffic"
    profile, params = planner.profile_for("trail_running", ["nature"])
    assert profile == "hiking-mountain" and params["profile:path_preference"] == "20.0" and params["profile:consider_river"] == "1"
    profile, params = planner.profile_for("gravel", ["flat"])
    assert params["profile:avoid_steep_inclines"] == "1"
    # BRouter parses injected profile values with Float.parseFloat – "true" would break routing.
    for sport in planner.SPORTS:
        for wishes in ([], ["low_traffic"], ["flat"], ["nature"], ["low_traffic", "flat", "nature"]):
            for key, value in planner.profile_for(sport, wishes)[1].items():
                assert key.startswith("profile:") and math.isfinite(float(value)), (sport, key, value)
    # Every profile is one that a standard BRouter installation ships.
    shipped = {"fastbike", "fastbike-verylowtraffic", "gravel", "mtb", "trekking", "hiking-mountain"}
    for sport in planner.SPORTS:
        for wishes in ([], ["low_traffic"], ["flat"], ["nature"]):
            assert planner.profile_for(sport, wishes)[0] in shipped


def test_surface_and_way_mix_is_distance_weighted():
    header = ["Longitude", "Latitude", "Elevation", "Distance", "CostPerKm", "ElevCost", "TurnCost", "NodeCost", "InitialCost", "WayTags", "NodeTags", "Time", "Energy"]
    rows = [header,
            ["8682100", "50110900", "100", "600", "1000", "0", "0", "0", "0", "highway=residential surface=asphalt", "", "0", "0"],
            ["8690000", "50112000", "105", "300", "1300", "0", "0", "0", "0", "highway=track tracktype=grade2", "", "0", "0"],
            ["8695000", "50113000", "110", "100", "1300", "0", "0", "0", "0", "highway=path surface=gravel", "", "0", "0"]]
    surface, ways = planner.mix(rows)
    assert surface == {"paved": 0.6, "unpaved_probably": 0.3, "unpaved": 0.1}
    assert ways == {"small_road": 0.6, "track": 0.3, "path": 0.1}
    assert planner.mix(None) == ({}, {})
    assert planner.mix([header]) == ({}, {})


def test_climb_ignores_noise():
    assert planner.climb([100, 101, 100, 102, 101, 100]) == (0, 0)
    assert planner.climb([100, 110, 120, 115, 100]) == (20, 20)


def test_doubled_share_detects_out_and_back():
    there = [[8.68 + i * 0.001, 50.11, None] for i in range(11)]
    out_and_back = there + there[-2::-1]
    assert planner.doubled_share(out_and_back) == 1.0
    loop = [[8.68, 50.11], [8.69, 50.11], [8.69, 50.12], [8.68, 50.12], [8.68, 50.11]]
    assert planner.doubled_share(loop) == 0.0


def test_duration_uses_personal_speed_and_din_for_hiking():
    assert planner.duration_s("road_bike", 52000, 0) == 7200
    with_climb = planner.duration_s("road_bike", 52000, 1000)
    assert with_climb == 7200 + 3000
    assert planner.duration_s("road_bike", 30000, 0, speed_kmh=30) == 3600
    assert planner.duration_s("road_bike", 30000, 1000, speed_kmh=30) == 3600 + 1500
    # DIN 33466: 12 km and 600 m up / down -> 3 h horizontal, 3.2 h vertical -> 3.2 + 1.5 = 4.7 h
    assert planner.duration_s("hiking", 12000, 600, 600) == round(4.7 * 3600)
    assert planner.personal_speed([(10000, 3600), (20000, 3600), (30000, 3600)]) == 20.0
    assert planner.personal_speed([(10000, 3600), (20000, 3600)]) is None


def test_parse_brouter_answer():
    coords = [[8.6821, 50.1109, 100.0], [8.6900, 50.1150, 112.5], [8.6950, 50.1200, 108.0]]
    route = planner.parse_brouter(geojson(coords, length=1530, ascend=12))
    assert route["distance_m"] == 1530 and route["ascent_m"] == 12 and route["has_elevation"]
    assert route["coordinates"][1] == [8.69, 50.115, 112.5]
    without_ele = planner.parse_brouter(geojson([[8.68, 50.11], [8.69, 50.12]]))
    assert without_ele["distance_m"] > 1000 and not without_ele["has_elevation"]
    with pytest.raises(ValueError):
        planner.parse_brouter({"type": "FeatureCollection", "features": []})


def test_warnings_and_ranking():
    v = planner.summarize({"coordinates": [[8.68, 50.11, 1], [8.7, 50.11, 1]], "distance_m": 50000, "ascent_m": 300, "descent_m": 300,
                           "surface": {"unpaved": 0.3, "paved": 0.7}, "ways": {"road": 0.4, "ferry": 0.01}}, "road_bike", 40000, None)
    assert {"LENGTH_OFF", "UNPAVED_FOR_ROAD_BIKE", "FERRY"} <= set(v["warnings"])
    good, bad = {"deviation": 0.01, "doubled": 0.02}, {"deviation": 0.2, "doubled": 0.4}
    assert planner.rank([bad, good])[0] is good


def fake_router(detour=1.3, fail_first=None):
    calls = []

    async def route(points, profile, params, alternative=0):
        calls.append((points, profile, params, alternative))
        if fail_first and len(calls) == 1:
            raise brouter.RoutingError(fail_first)
        coords = [[lon, lat, 100.0 + i] for i, (lat, lon) in enumerate(points)]
        straight = sum(planner.metres(a, b) for a, b in zip(points, points[1:]))
        return {"coordinates": coords, "distance_m": round(straight * detour * (1 + 0.05 * alternative)), "ascent_m": 50, "descent_m": 50,
                "surface": {"paved": 1.0}, "ways": {"small_road": 1.0}, "has_elevation": True, "engine": "fake"}

    return route, calls


def test_round_trip_converges_to_the_wished_length():
    route, calls = fake_router(detour=1.6)
    variants = asyncio.run(brouter.round_trip(route, "road_bike", START, 60000, [], None, 3, 0, None))
    assert 1 <= len(variants) <= 3
    for v in variants:
        assert abs(v["deviation"]) <= 0.08, v["deviation"]
    assert len(calls) <= 12
    assert all(c[1] == "fastbike" for c in calls)


def test_round_trip_retries_smaller_when_a_point_is_off_the_network():
    route, calls = fake_router(fail_first="POINT_NOT_ON_NETWORK")
    variants = asyncio.run(brouter.round_trip(route, "hiking", START, 12000, ["nature"], 0, 1, 0, None))
    assert variants and len(calls) >= 2


def test_round_trip_stops_when_the_server_is_unreachable():
    async def route(points, profile, params, alternative=0):
        raise brouter.RoutingError("ROUTER_UNREACHABLE")
    with pytest.raises(brouter.RoutingError) as info:
        asyncio.run(brouter.round_trip(route, "running", START, 10000, [], None, 3, 0, None))
    assert info.value.code == "ROUTER_UNREACHABLE"


def test_a_to_b_uses_alternatives():
    route, calls = fake_router()
    end = planner.destination(*START, 45, 15000)
    variants = asyncio.run(brouter.a_to_b(route, "trekking", [START, end], [], 3, None))
    assert [c[3] for c in calls] == [0, 1, 2, 3]
    assert variants and variants[0]["deviation"] is None


def test_http_client_query_and_errors():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(dict(request.url.params))
        if "fail" in seen.get("profile", ""):
            return httpx.Response(400, text="from-position not mapped in existing datafile")
        return httpx.Response(200, json=geojson([[8.68, 50.11, 100], [8.69, 50.12, 120]], length=1400, ascend=20))

    async def run(profile):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await brouter.http_router("https://brouter.example/brouter", client)([START, (50.12, 8.69)], profile, {"profile:iswet": "1"}, 1)

    result = asyncio.run(run("hiking-mountain"))
    assert result["distance_m"] == 1400
    assert seen["lonlats"] == "8.682100,50.110900|8.690000,50.120000"
    assert seen["format"] == "geojson" and seen["alternativeidx"] == "1" and seen["profile:iswet"] == "1"
    with pytest.raises(brouter.RoutingError) as info:
        asyncio.run(run("fail"))
    assert info.value.code == "POINT_NOT_ON_NETWORK"


def test_error_codes_and_server_urls():
    assert brouter.error_code(400, "target island detected for section 0") == "POINT_ISOLATED"
    assert brouter.error_code(400, "datafile E5_N50.rd5 not found") == "AREA_NOT_COVERED"
    assert brouter.error_code(500, "operation killed by thread-priority-watchdog") == "ROUTING_TOO_LONG"
    assert brouter.error_code(503, "") == "SERVER_BUSY"
    assert brouter.clean_url("") == planner.DEFAULT_BROUTER_URL
    assert brouter.clean_url("http://192.168.1.20:17777") == "http://192.168.1.20:17777/brouter"
    assert brouter.clean_url("https://brouter.de/brouter-web") == "https://brouter.de/brouter"
    assert brouter.clean_url("http://lxc:17777/brouter/") == "http://lxc:17777/brouter"
    for bad in ("ftp://x", "brouter.de", "http://user:pw@host/brouter", "http://h/brouter?x=1"):
        with pytest.raises(ValueError):
            brouter.clean_url(bad)


def test_migration_models_and_wiring():
    migration = (ROOT / "db/migrations/versions/0020_tour_planner.py").read_text(encoding="utf-8")
    assert "down_revision = '0019_race_events'" in migration and "planned_tours" in migration and "app_settings" in migration
    main = (ROOT / "apps/api/main.py").read_text(encoding="utf-8")
    assert "tours.router" in main
    api = (ROOT / "apps/api/routers/tours.py").read_text(encoding="utf-8")
    assert "async def set_server(payload: ServerIn, user: User = Depends(admin_user)" in api
    assert "async def test_server(payload: ServerTestIn, user: User = Depends(admin_user)" in api
    assert 'proxyTimeout: 300_000' in (WEB / "next.config.ts").read_text(encoding="utf-8")


def test_sports_are_consistent():
    for key, sport in planner.SPORTS.items():
        assert sport.key == key and sport.min_km < sport.default_km < sport.max_km
        assert key in planner.DETOUR
    assert math.isclose(planner.metres(START, planner.destination(*START, 33, 5000)), 5000, rel_tol=1e-6)
    assert json.dumps(planner.PREFERENCES)


def test_page_nav_help_and_readme():
    page = (WEB / "app/tours/page.tsx").read_text(encoding="utf-8")
    assert '"/tours/plan"' in page and "gpx(" in page and "ActivityRouteMap3D" in page and "/tours/server/settings" in page
    shell = (WEB / "components/AppShell.tsx").read_text(encoding="utf-8")
    assert 'href:"/tours"' in shell and "dock:false" in shell and "x.dock!==false" in shell
    assert 'href="/tours"' in (WEB / "app/activities/page.tsx").read_text(encoding="utf-8")
    help_text = (WEB / "lib/help.ts").read_text(encoding="utf-8")
    assert 'id:"tours"' in help_text and "Touren planen" in help_text and "Plan tours" in help_text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) < 150, "the README stays short; release notes belong in the changelog"
    assert "docs/TOUR_PLANNER.md" in readme and "CHANGELOG.md" in readme and "**Alpha." not in readme
    assert (ROOT / "docs/images/pengucoach-readme-hero.png").stat().st_size > 200_000
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## 0.1.0-alpha.87") < changelog.index("## 0.1.0-alpha.86")


# ---------------------------------------------------------------- alpha.89
def _line(lat, lon0, lon1, n):
    return [[lon0 + (lon1 - lon0) * i / n, lat, 100.0] for i in range(n + 1)]


def test_dead_end_at_a_waypoint_is_found_and_moved_to_the_junction():
    # Along a road to the junction at lon 8.70, 400 m up a track to the waypoint and back, then on.
    road1 = _line(50.11, 8.68, 8.70, 20)
    spur = [[8.70, 50.11 + 0.0004 * i, 100.0] for i in range(1, 11)]
    back = spur[-2::-1] + [[8.70, 50.11, 100.0]]
    road2 = _line(50.11, 8.70, 8.72, 20)[1:]
    coords = road1 + spur + back + road2
    waypoints = [(50.11, 8.68), (50.114, 8.70), (50.11, 8.72)]
    found = planner.spurs(coords, waypoints)
    assert len(found) == 1 and found[0]["index"] == 1
    assert abs(found[0]["lat"] - 50.11) < 1e-6 and abs(found[0]["lon"] - 8.70) < 1e-6
    assert 400 < found[0]["length_m"] < 470
    fixed = planner.without_spurs(waypoints, found)
    assert fixed[1] == (50.11, 8.70)
    # A plain road through a waypoint is no dead end.
    assert planner.spurs(_line(50.11, 8.68, 8.72, 40), [(50.11, 8.68), (50.11, 8.70), (50.11, 8.72)]) == []


def test_round_trip_cuts_dead_ends_and_keeps_waypoints():
    junctions = set()

    async def route(points, profile, params, alternative=0):
        coords = []
        for n, (a, b) in enumerate(zip(points, points[1:])):
            start = a
            if 0 < n and (round(a[0], 6), round(a[1], 6)) not in junctions:
                # The via point lies 300 m up a track: road to the junction, up and back down.
                j = (a[0] - 0.0027, a[1])
                junctions.add((round(j[0], 6), round(j[1], 6)))
                up = [[a[1], j[0] + (a[0] - j[0]) * t / 9, 100.0] for t in range(10)]
                coords += up + up[-2::-1]
                start = j
            coords += [[start[1] + (b[1] - start[1]) * t / 10, start[0] + (b[0] - start[0]) * t / 10, 100.0] for t in range(1 if coords else 0, 10)]
        coords.append([points[-1][1], points[-1][0], 100.0])
        length = sum(planner.metres((x[1], x[0]), (y[1], y[0])) for x, y in zip(coords, coords[1:]))
        return {"coordinates": coords, "distance_m": round(length), "ascent_m": 0, "descent_m": 0, "surface": {}, "ways": {}, "has_elevation": True}

    variants = asyncio.run(brouter.round_trip(route, "road_bike", START, 30000, [], 0, 1, 0, None))
    v = variants[0]
    assert v["spurs_removed"] >= 1
    assert v["waypoints"][0] == [START[0], START[1]] and len(v["waypoints"]) >= 3
    assert all((round(w[0], 6), round(w[1], 6)) in junctions for w in v["waypoints"][1:-1]), "via points sit on the junctions"


def test_familiar_ways_steer_and_measure():
    track = [(50.11 + 0.0005 * i, 8.68) for i in range(200)]  # 11 km northwards
    cells = planner.known_cells([track])
    on = [[8.68, 50.11 + 0.0005 * i, None] for i in range(100)]
    off = [[8.75, 50.11 + 0.0005 * i, None] for i in range(100)]
    assert planner.known_share(on, cells) > 0.95
    assert planner.known_share(off, cells) == 0
    assert planner.known_share(on, set()) is None
    wps = [START, (50.15, 8.69), START]
    steered = planner.steer(wps, "known", track, cells, 3000)
    assert abs(steered[1][1] - 8.68) < 1e-9, "the via point moves onto the known track"
    away = planner.steer([START, (50.15, 8.68), START], "new", track, cells, 3000)
    assert planner.cell(*away[1]) not in cells
    assert planner.steer(wps, "any", track, cells, 3000) == wps
    ranked = planner.rank_by([{"deviation": 0, "doubled": 0, "known_share": .1}, {"deviation": 0, "doubled": 0, "known_share": .9}], "known")
    assert ranked[0]["known_share"] == .9
    assert planner.rank_by([{"deviation": 0, "doubled": 0, "known_share": .1}, {"deviation": 0, "doubled": 0, "known_share": .9}], "new")[0]["known_share"] == .1


def test_editor_routes_piece_by_piece_with_a_cache():
    calls = []

    async def route(points, profile, params, alternative=0):
        calls.append(tuple(points))
        a, b = points
        coords = [[a[1], a[0], 100.0], [(a[1] + b[1]) / 2, (a[0] + b[0]) / 2, 110.0], [b[1], b[0], 100.0]]
        return {"coordinates": coords, "distance_m": 1000, "ascent_m": 10, "descent_m": 10, "surface": {"paved": 1.0} if len(calls) % 2 else {"unpaved": 1.0},
                "ways": {"small_road": 1.0}, "has_elevation": True}

    brouter._PIECES.clear()
    pts = [START, (50.12, 8.69), (50.13, 8.70), START]
    merged = asyncio.run(brouter.through(route, pts, "trekking", {}, "test"))
    assert len(calls) == 3 and merged["distance_m"] == 3000 and merged["ascent_m"] == 30
    assert merged["segments"] == [0, 2, 4] and len(merged["coordinates"]) == 7
    assert abs(sum(merged["surface"].values()) - 1) < 1e-6
    moved = [START, (50.12, 8.69), (50.135, 8.705), START]
    asyncio.run(brouter.through(route, moved, "trekking", {}, "test"))
    assert len(calls) == 5, "only the two pieces next to the moved point are routed again"


def test_editor_endpoint_and_familiarity_are_wired():
    api = (ROOT / "apps/api/routers/tours.py").read_text(encoding="utf-8")
    assert '@router.post("/route")' in api and "clean_spurs" in api and "planner.spurs(" in api
    assert 'familiarity: Literal["any", "known", "new"] = "any"' in api and "_familiar(" in api


def test_alpha89_ui_help_and_changelog():
    page = (WEB / "app/tours/page.tsx").read_text(encoding="utf-8")
    assert '"/tours/route"' in page and "startEdit(" in page and "familiarity" in page and "!DEMO&&" in page
    tour_map = (WEB / "components/TourMap.tsx").read_text(encoding="utf-8")
    assert "h.onSelect(best)" in tour_map and "tour-variant-label" in tour_map and "onInsert" in tour_map and "pointerType" in tour_map
    help_text = (WEB / "lib/help.ts").read_text(encoding="utf-8")
    assert "Stichwege und Sackgassen" in help_text and "Dead ends" in help_text and "Bekannte Wege oder Neues entdecken" in help_text
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## 0.1.0-alpha.89") < changelog.index("## 0.1.0-alpha.88")
