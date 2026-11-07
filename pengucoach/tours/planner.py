"""Tour planner logic (alpha.87). Pure functions – no network, fully testable.

Routing is done by BRouter (open source, no key). PenguCoach decides *where* a tour
should go: for a round trip it places waypoints on a circle that passes through the
start, asks BRouter for the route through them and rescales the circle until the
length fits. Each variant points in a different direction. The result is evaluated
here: length, climbing, surface and way types from the OSM tags BRouter returns,
how much of the loop is ridden twice, and an estimated duration.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable

EARTH_M = 6_371_000.0
DEFAULT_BROUTER_URL = "https://brouter.de/brouter"


@dataclass(frozen=True)
class Sport:
    key: str
    family: str  # matches activity sport families for personal speed
    profile: str
    params: dict[str, str] = field(default_factory=dict)
    speed_kmh: float = 20.0  # flat-ground default when there is no history
    climb_min_per_100m: float = 5.0
    gpx_type: str = "cycling"
    min_km: float = 2.0
    max_km: float = 250.0
    default_km: float = 40.0


# Profiles are the ones every BRouter installation ships (misc/profiles2), so a
# self-hosted server behaves like brouter.de. "profile:<name>" sets a profile
# variable; older servers simply ignore it. BRouter reads these values with
# Float.parseFloat, so booleans must be sent as 1 / 0, never as "true".
SPORTS: dict[str, Sport] = {
    "road_bike": Sport("road_bike", "cycling", "fastbike", {"profile:allow_steps": "0"}, 26.0, 5.0, "cycling", 10, 250, 60),
    "gravel": Sport("gravel", "cycling", "gravel", {"profile:prefer_unpaved_paths": "1"}, 21.0, 6.0, "cycling", 8, 200, 50),
    "mtb": Sport("mtb", "cycling", "mtb", {}, 15.0, 8.0, "cycling", 5, 120, 30),
    "trekking": Sport("trekking", "cycling", "trekking", {}, 18.0, 6.0, "cycling", 5, 200, 40),
    "running": Sport("running", "running", "hiking-mountain", {"profile:iswet": "1", "profile:SAC_scale_limit": "1", "profile:allow_steps": "0"}, 10.0, 6.0, "running", 2, 50, 10),
    "trail_running": Sport("trail_running", "running", "hiking-mountain", {"profile:SAC_scale_limit": "2", "profile:path_preference": "20.0", "profile:consider_forest": "1"}, 8.5, 9.0, "running", 2, 60, 12),
    "hiking": Sport("hiking", "hiking", "hiking-mountain", {"profile:SAC_scale_limit": "3", "profile:consider_noise": "1"}, 4.0, 10.0, "hiking", 2, 50, 12),
}

# Optional wishes, mapped onto the variables each standard profile understands.
PREFERENCES: dict[str, dict[str, dict[str, str] | str]] = {
    "low_traffic": {
        "road_bike": "fastbike-verylowtraffic",
        "gravel": {"profile:consider_traffic_estimate": "1", "profile:avoid_towns": "1"},
        "trekking": {"profile:avoid_unsafe": "1", "profile:consider_traffic": "1"},
        "running": {"profile:consider_noise": "1", "profile:consider_town": "1"},
        "trail_running": {"profile:consider_noise": "1", "profile:consider_town": "1"},
        "hiking": {"profile:consider_town": "1"},
    },
    "flat": {
        "road_bike": {"profile:uphillcost": "70", "profile:uphillcutoff": "1.0"},
        "gravel": {"profile:avoid_steep_inclines": "1", "profile:consider_elevation": "1"},
        "trekking": {"profile:consider_elevation": "1"},
        "running": {"profile:consider_elevation": "1"},
        "trail_running": {"profile:consider_elevation": "1"},
        "hiking": {"profile:consider_elevation": "1"},
    },
    "nature": {
        "road_bike": {"profile:consider_forest": "1", "profile:consider_river": "1"},
        "gravel": {"profile:prefer_forests": "1", "profile:prefer_rivers": "1"},
        "trekking": {"profile:consider_forest": "1", "profile:consider_river": "1"},
        "running": {"profile:consider_forest": "1", "profile:consider_river": "1"},
        "trail_running": {"profile:consider_river": "1"},
        "hiking": {"profile:consider_forest": "1", "profile:consider_river": "1"},
    },
}


def profile_for(sport: str, preferences: Iterable[str] = ()) -> tuple[str, dict[str, str]]:
    base = SPORTS[sport]
    profile, params = base.profile, dict(base.params)
    for wish in preferences:
        value = PREFERENCES.get(wish, {}).get(sport)
        if isinstance(value, str):
            profile = value
        elif isinstance(value, dict):
            params.update(value)
    return profile, params


# ---------------------------------------------------------------- geometry
def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    d, b = distance_m / EARTH_M, math.radians(bearing_deg)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


# Roads are not straight lines: a routed loop through points on a circle is longer
# than the circle itself. This is only the first guess; the loop is rescaled after
# each attempt.
DETOUR = {"road_bike": 1.22, "gravel": 1.3, "mtb": 1.4, "trekking": 1.28, "running": 1.3, "trail_running": 1.4, "hiking": 1.4}


def loop_waypoints(lat: float, lon: float, bearing: float, radius_m: float, points: int = 4) -> list[tuple[float, float]]:
    """Points on a circle through the start whose centre lies `radius_m` away in `bearing`.

    Returns start, the circle points clockwise and the start again.
    """
    centre = destination(lat, lon, bearing, radius_m)
    back = (bearing + 180) % 360
    ring = [destination(centre[0], centre[1], (back + step * 360 / (points + 1)) % 360, radius_m) for step in range(1, points + 1)]
    return [(lat, lon), *ring, (lat, lon)]


def first_radius(sport: str, target_m: float) -> float:
    return target_m / (2 * math.pi * DETOUR.get(sport, 1.3))


def next_radius(radius: float, target_m: float, routed_m: float) -> float:
    if routed_m <= 0:
        return radius * 0.7
    factor = max(0.5, min(1.8, target_m / routed_m))
    return radius * factor


def fits(target_m: float, routed_m: float, tolerance: float = 0.08) -> bool:
    return target_m > 0 and abs(routed_m - target_m) / target_m <= tolerance


def variant_bearings(count: int, direction: float | None, seed: int = 0) -> list[float]:
    """Directions for the variants: the wished direction ± 45°, otherwise spread around the start."""
    if direction is not None:
        return [((direction + offset) % 360) for offset in (0, -45, 45, -90, 90)[:count]]
    base = (seed * 47) % 360
    return [((base + i * 360 / count) % 360) for i in range(count)]


# ---------------------------------------------------------------- evaluation
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "sett", "chipseal", "metal", "wood", "unhewn_cobblestone", "cobblestone"}
UNPAVED = {"unpaved", "gravel", "fine_gravel", "compacted", "dirt", "earth", "ground", "grass", "mud", "sand", "pebblestone", "rock", "woodchips", "grass_paver", "gravel;grass", "clay"}
ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
SMALL_ROADS = {"residential", "unclassified", "service", "living_street", "road", "pedestrian"}
PATHS = {"path", "footway", "bridleway", "steps", "via_ferrata"}


def tags(value: str) -> dict[str, str]:
    out = {}
    for part in (value or "").split():
        if "=" in part:
            key, val = part.split("=", 1)
            out[key] = val
    return out


def surface_class(way: dict[str, str]) -> str:
    surface = way.get("surface", "")
    if surface in PAVED:
        return "paved"
    if surface in UNPAVED:
        return "unpaved"
    highway, tracktype = way.get("highway", ""), way.get("tracktype", "")
    # Without a surface tag the road class is a good hint, but it stays "probably".
    if highway in ROADS or highway in SMALL_ROADS or highway == "cycleway" or tracktype == "grade1":
        return "paved_probably"
    if highway in {"track", "path", "bridleway"} or tracktype in {"grade2", "grade3", "grade4", "grade5"}:
        return "unpaved_probably"
    return "unknown"


def way_class(way: dict[str, str]) -> str:
    highway = way.get("highway", "")
    if highway in ROADS:
        return "road"
    if highway in SMALL_ROADS:
        return "small_road"
    if highway == "cycleway" or way.get("bicycle") == "designated":
        return "cycleway"
    if highway == "track":
        return "track"
    if highway in PATHS:
        return "path"
    if way.get("route_ferry") or way.get("route") == "ferry":
        return "ferry"
    return "other"


def mix(messages: list[list[Any]] | None) -> tuple[dict[str, float], dict[str, float]]:
    """Distance-weighted surface and way shares (0..1) from BRouter's message table."""
    surface: dict[str, float] = {}
    ways: dict[str, float] = {}
    if not messages or len(messages) < 2:
        return surface, ways
    header = [str(h) for h in messages[0]]
    try:
        i_dist, i_tags = header.index("Distance"), header.index("WayTags")
    except ValueError:
        return surface, ways
    total = 0.0
    for row in messages[1:]:
        try:
            distance = float(row[i_dist])
        except (TypeError, ValueError, IndexError):
            continue
        if distance <= 0:
            continue
        way = tags(str(row[i_tags]) if len(row) > i_tags else "")
        total += distance
        s, w = surface_class(way), way_class(way)
        surface[s] = surface.get(s, 0.0) + distance
        ways[w] = ways.get(w, 0.0) + distance
    if total <= 0:
        return {}, {}
    return ({k: round(v / total, 3) for k, v in surface.items()}, {k: round(v / total, 3) for k, v in ways.items()})


def climb(elevations: list[float], threshold: float = 3.0) -> tuple[float, float]:
    """Ascent and descent with a small hysteresis so GPS-like noise does not add up."""
    values = [e for e in elevations if e is not None and math.isfinite(e)]
    if len(values) < 2:
        return 0.0, 0.0
    up = down = 0.0
    anchor = values[0]
    for value in values[1:]:
        delta = value - anchor
        if delta >= threshold:
            up += delta
            anchor = value
        elif delta <= -threshold:
            down -= delta
            anchor = value
    return round(up), round(down)


def doubled_share(coordinates: list[list[float]]) -> float:
    """Share of the length that runs over the same street segment twice (out and back)."""
    seen: dict[tuple, int] = {}
    pieces = []
    for a, b in zip(coordinates, coordinates[1:]):
        key = tuple(sorted(((round(a[0], 4), round(a[1], 4)), (round(b[0], 4), round(b[1], 4)))))
        length = metres((a[1], a[0]), (b[1], b[0]))
        if key[0] == key[1]:
            continue
        pieces.append((key, length))
        seen[key] = seen.get(key, 0) + 1
    total = sum(length for _, length in pieces)
    if total <= 0:
        return 0.0
    twice = sum(length for key, length in pieces if seen[key] > 1)
    return round(twice / total, 3)


def personal_speed(rows: Iterable[tuple[float | None, int | None]]) -> float | None:
    """Median speed (km/h) of recent activities as (distance_m, moving_seconds); None below three."""
    speeds = []
    for distance, seconds in rows:
        if distance and seconds and distance > 500 and seconds > 300:
            speed = distance / seconds * 3.6
            if 1.5 <= speed <= 70:
                speeds.append(speed)
    return round(statistics.median(speeds), 1) if len(speeds) >= 3 else None


def duration_s(sport: str, distance_m: float, ascent_m: float, descent_m: float = 0.0, speed_kmh: float | None = None) -> int:
    base = SPORTS[sport]
    if sport == "hiking" and speed_kmh is None:
        # DIN 33466: 4 km/h on the flat, 300 m/h up, 500 m/h down; the larger part counts fully.
        horizontal = distance_m / 1000 / 4.0
        vertical = ascent_m / 300 + descent_m / 500
        return int(round((max(horizontal, vertical) + min(horizontal, vertical) / 2) * 3600))
    speed = speed_kmh or base.speed_kmh
    flat = distance_m / 1000 / speed * 3600
    # Personal speeds already contain the user's usual hills, so they count half.
    climbing = ascent_m / 100 * base.climb_min_per_100m * 60 * (0.5 if speed_kmh else 1.0)
    return int(round(flat + climbing))


def parse_brouter(payload: dict) -> dict:
    """Turn a BRouter GeoJSON answer into a compact route dict."""
    features = payload.get("features") if isinstance(payload, dict) else None
    if not features:
        raise ValueError("ROUTE_EMPTY")
    feature = features[0]
    props = feature.get("properties") or {}
    coordinates = [[float(c[0]), float(c[1]), float(c[2]) if len(c) > 2 and c[2] is not None else None] for c in (feature.get("geometry") or {}).get("coordinates", [])]
    if len(coordinates) < 2:
        raise ValueError("ROUTE_EMPTY")

    def number(key: str) -> float | None:
        try:
            return float(props.get(key))
        except (TypeError, ValueError):
            return None

    length = number("track-length")
    if not length:
        length = sum(metres((a[1], a[0]), (b[1], b[0])) for a, b in zip(coordinates, coordinates[1:]))
    ascent, descent = climb([c[2] for c in coordinates if c[2] is not None])
    filtered = number("filtered ascend")
    surface, ways = mix(props.get("messages"))
    return {"coordinates": coordinates, "distance_m": round(length), "ascent_m": round(filtered) if filtered is not None else ascent,
            "descent_m": descent, "surface": surface, "ways": ways, "has_elevation": any(c[2] is not None for c in coordinates),
            "engine": str(props.get("creator") or "BRouter")}


def summarize(route: dict, sport: str, target_m: float | None, speed_kmh: float | None) -> dict:
    elevations = [c[2] for c in route["coordinates"] if c[2] is not None]
    out = {**route, "duration_s": duration_s(sport, route["distance_m"], route["ascent_m"], route["descent_m"], speed_kmh),
           "doubled": doubled_share(route["coordinates"]),
           "min_elevation_m": round(min(elevations)) if elevations else None, "max_elevation_m": round(max(elevations)) if elevations else None,
           "deviation": round((route["distance_m"] - target_m) / target_m, 3) if target_m else None}
    surface = route.get("surface") or {}
    out["paved_share"] = round(surface.get("paved", 0) + surface.get("paved_probably", 0), 3)
    out["unpaved_share"] = round(surface.get("unpaved", 0) + surface.get("unpaved_probably", 0), 3)
    out["warnings"] = warnings(out, sport)
    return out


def warnings(variant: dict, sport: str) -> list[str]:
    result = []
    ways = variant.get("ways") or {}
    if variant.get("deviation") is not None and abs(variant["deviation"]) > 0.15:
        result.append("LENGTH_OFF")
    if variant.get("doubled", 0) > 0.25:
        result.append("OUT_AND_BACK")
    if sport == "road_bike" and variant.get("unpaved_share", 0) > 0.1:
        result.append("UNPAVED_FOR_ROAD_BIKE")
    if sport in {"trail_running", "hiking", "mtb"} and ways.get("road", 0) > 0.25:
        result.append("MANY_ROADS")
    if ways.get("ferry"):
        result.append("FERRY")
    return result


def rank(variants: list[dict]) -> list[dict]:
    """Best first: close to the wished length, little riding twice."""
    def score(v: dict) -> float:
        return abs(v.get("deviation") or 0) * 2 + v.get("doubled", 0)
    return sorted(variants, key=score)


def distinct(variants: list[dict], limit: int) -> list[dict]:
    """Drop variants that are almost the same route (share most of their points)."""
    chosen: list[dict] = []
    for variant in variants:
        cells = {(round(c[0], 3), round(c[1], 3)) for c in variant["coordinates"]}
        if all(len(cells & other) / max(1, len(cells)) < 0.75 for other in (c["_cells"] for c in chosen)):
            chosen.append({**variant, "_cells": cells})
        if len(chosen) >= limit:
            break
    return [{k: v for k, v in c.items() if k != "_cells"} for c in chosen]
