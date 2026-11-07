"""BRouter client and tour search (alpha.87).

BRouter is called with plain HTTP GET (`/brouter?lonlats=…&profile=…&format=geojson`).
The public server brouter.de needs no key; a self-hosted BRouter works the same.
Requests run one after another per installation, so a public server is never
flooded – a tour search makes at most a handful of calls.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from pengucoach.tours import planner

log = logging.getLogger(__name__)
Router = Callable[[list[tuple[float, float]], str, dict[str, str], int], Awaitable[dict]]

_LOCK = asyncio.Semaphore(2)
FATAL = {"ROUTER_UNREACHABLE", "PROFILE_UNKNOWN", "AREA_NOT_COVERED", "SERVER_BUSY"}
TIMEOUT = httpx.Timeout(45.0, connect=8.0)


class RoutingError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail[:300]


def clean_url(value: str | None) -> str:
    text = (value or "").strip().rstrip("/")
    if not text:
        return planner.DEFAULT_BROUTER_URL
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.query or parts.fragment or "@" in parts.netloc:
        raise ValueError("BROUTER_URL_INVALID")
    # People paste the web UI address; the routing endpoint is /brouter.
    if parts.path in {"", "/"} or parts.path.rstrip("/").endswith("/brouter-web"):
        base = text[: -len("/brouter-web")] if text.endswith("/brouter-web") else text
        return base.rstrip("/") + "/brouter"
    return text


def error_code(status: int, text: str) -> str:
    message = (text or "").lower()
    if "not mapped" in message or ("no track found" in message and "position" in message):
        return "POINT_NOT_ON_NETWORK"
    if "island" in message:
        return "POINT_ISOLATED"
    if ("datafile" in message or "segment" in message) and "not found" in message:
        return "AREA_NOT_COVERED"
    if "profile" in message and ("not found" in message or "unknown" in message or "parse" in message):
        return "PROFILE_UNKNOWN"
    if "timeout" in message or "watchdog" in message or "killed" in message:
        return "ROUTING_TOO_LONG"
    if status in {429, 503}:
        return "SERVER_BUSY"
    return "ROUTING_FAILED"


def http_router(base_url: str, client: httpx.AsyncClient | None = None) -> Router:
    url = clean_url(base_url)

    async def route(points: list[tuple[float, float]], profile: str, params: dict[str, str], alternative: int = 0) -> dict:
        query = {"lonlats": "|".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points), "profile": profile,
                 "alternativeidx": str(alternative), "format": "geojson", **params}
        async with _LOCK:
            try:
                if client is not None:
                    response = await client.get(url, params=query)
                else:
                    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "PenguCoach tour planner"}) as own:
                        response = await own.get(url, params=query)
            except httpx.TimeoutException as exc:
                raise RoutingError("ROUTING_TIMEOUT", str(exc)) from None
            except httpx.HTTPError as exc:
                raise RoutingError("ROUTER_UNREACHABLE", str(exc)) from None
        if response.status_code != 200:
            raise RoutingError(error_code(response.status_code, response.text), response.text)
        try:
            return planner.parse_brouter(response.json())
        except ValueError:
            raise RoutingError(error_code(200, response.text), response.text) from None

    return route


@dataclass
class Familiar:
    """The user's own recorded tracks of this sport (alpha.89)."""
    mode: str = "any"  # any | known | new
    points: list[tuple[float, float]] = field(default_factory=list)
    cells: set = field(default_factory=set)


async def _clean(route: Router, waypoints: list[tuple[float, float]], result: dict, profile: str, params: dict[str, str]) -> tuple[dict, list[tuple[float, float]], int]:
    """Cut dead ends: move every waypoint that sits at the end of a there-and-back spur to its junction and route again."""
    found = planner.spurs(result["coordinates"], waypoints)
    if not found:
        return result, waypoints, 0
    better = planner.without_spurs(waypoints, found)
    try:
        again = await route(better, profile, params, 0)
    except RoutingError:
        return result, waypoints, 0
    return again, better, len(found)


async def round_trip(route: Router, sport: str, start: tuple[float, float], target_m: float, preferences: list[str],
                     direction: float | None, count: int, seed: int, speed_kmh: float | None, familiar: Familiar | None = None) -> list[dict]:
    profile, params = planner.profile_for(sport, preferences)
    familiar = familiar or Familiar()
    errors: list[RoutingError] = []

    async def search(bearing: float) -> dict | None:
        radius, best = planner.first_radius(sport, target_m), None
        for _ in range(4):
            waypoints = planner.steer(planner.loop_waypoints(start[0], start[1], bearing, radius), familiar.mode, familiar.points, familiar.cells, radius)
            try:
                result = await route(waypoints, profile, params, 0)
            except RoutingError as exc:
                errors.append(exc)
                # A waypoint in a lake or on a motorway: try a slightly smaller loop.
                if exc.code in {"POINT_NOT_ON_NETWORK", "POINT_ISOLATED"}:
                    radius *= 0.8
                    continue
                if exc.code in FATAL:
                    raise
                break
            result, waypoints, cut = await _clean(route, waypoints, result, profile, params)
            candidate = planner.summarize(result, sport, target_m, speed_kmh)
            candidate.update(bearing=round(bearing), profile=profile, waypoints=[[round(a, 6), round(b, 6)] for a, b in waypoints], spurs_removed=cut,
                             known_share=planner.known_share(result["coordinates"], familiar.cells))
            if best is None or abs(candidate["deviation"]) < abs(best["deviation"]):
                best = candidate
            if planner.fits(target_m, result["distance_m"]):
                break
            radius = planner.next_radius(radius, target_m, result["distance_m"])
        return best

    # The directions are searched side by side (the semaphore keeps it to two calls at once).
    results = await asyncio.gather(*(search(b) for b in planner.variant_bearings(count, direction, seed)), return_exceptions=True)
    fatal = [r for r in results if isinstance(r, RoutingError)]
    found = [r for r in results if isinstance(r, dict)]
    if not found:
        if fatal:
            raise fatal[0]
        raise errors[-1] if errors else RoutingError("ROUTING_FAILED")
    return planner.distinct(planner.rank_by(found, familiar.mode), count)


async def a_to_b(route: Router, sport: str, points: list[tuple[float, float]], preferences: list[str], count: int,
                 speed_kmh: float | None, familiar: Familiar | None = None) -> list[dict]:
    profile, params = planner.profile_for(sport, preferences)
    familiar = familiar or Familiar()
    found: list[dict] = []
    last: RoutingError | None = None
    # BRouter offers up to four alternatives for the same points.
    for alternative in range(min(4, count + 1)):
        try:
            result = await route(points, profile, params, alternative)
        except RoutingError as exc:
            if alternative == 0:
                raise
            last = exc
            break
        candidate = planner.summarize(result, sport, None, speed_kmh)
        candidate.update(alternative=alternative, profile=profile, waypoints=[[round(a, 6), round(b, 6)] for a, b in points], spurs_removed=0,
                         known_share=planner.known_share(result["coordinates"], familiar.cells))
        found.append(candidate)
    if not found:
        raise last or RoutingError("ROUTING_FAILED")
    return planner.distinct(planner.rank_by(found, familiar.mode) if familiar.mode != "any" else found, count)


# ---------------------------------------------------------------- alpha.89: editor
_PIECES: OrderedDict[tuple, dict] = OrderedDict()
PIECE_CACHE = 600


async def through(route: Router, points: list[tuple[float, float]], profile: str, params: dict[str, str], cache_key: str = "") -> dict:
    """Route through all points piece by piece. Unchanged pieces come from a cache, so dragging one
    point in the editor only asks BRouter for the two pieces next to it."""
    frozen = tuple(sorted(params.items()))

    async def piece(a: tuple[float, float], b: tuple[float, float]) -> dict:
        key = (cache_key, profile, frozen, round(a[0], 6), round(a[1], 6), round(b[0], 6), round(b[1], 6))
        if key in _PIECES:
            _PIECES.move_to_end(key)
            return _PIECES[key]
        result = await route([a, b], profile, params, 0)
        _PIECES[key] = result
        while len(_PIECES) > PIECE_CACHE:
            _PIECES.popitem(last=False)
        return result

    pairs = list(zip(points, points[1:]))
    parts = await asyncio.gather(*(piece(a, b) for a, b in pairs))
    return planner.merge(list(parts))
