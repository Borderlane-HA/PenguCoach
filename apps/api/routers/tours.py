"""Tour planner (alpha.87): round trips and A→B tours per sport, routed by BRouter without a key."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import admin_user, safety_confirmed_user
from pengucoach.coach.training_intelligence import sport_family
from pengucoach.db.models import Activity, AppSetting, PlannedTour, User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.tours import brouter, planner
from pengucoach.weather.service import search_locations, weather_config

router = APIRouter(prefix="/tours", tags=["tours"])
log = logging.getLogger(__name__)
SportKey = Literal["road_bike", "gravel", "mtb", "trekking", "running", "trail_running", "hiking"]
Wish = Literal["low_traffic", "flat", "nature"]
SERVER_KEY = "tour_routing"
MAX_POINTS = 20000


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class PlanIn(BaseModel):
    sport: SportKey
    mode: Literal["round", "a_to_b"] = "round"
    start: Point
    end: Point | None = None
    via: list[Point] = Field(default_factory=list, max_length=8)
    distance_km: float | None = Field(default=None, gt=0, le=300, allow_inf_nan=False)
    direction: float | None = Field(default=None, ge=0, lt=360, allow_inf_nan=False)
    preferences: list[Wish] = Field(default_factory=list, max_length=3)
    variants: int = Field(default=3, ge=1, le=3)
    seed: int = Field(default=0, ge=0, le=1000)


class TourIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sport: SportKey
    mode: Literal["round", "a_to_b"] = "round"
    coordinates: list[list[float | None]] = Field(min_length=2, max_length=MAX_POINTS)
    summary: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("NAME_REQUIRED")
        return value

    @field_validator("coordinates")
    @classmethod
    def valid(cls, rows: list[list[float | None]]) -> list[list[float | None]]:
        out = []
        for row in rows:
            if len(row) < 2 or row[0] is None or row[1] is None or not (-180 <= row[0] <= 180 and -90 <= row[1] <= 90):
                raise ValueError("COORDINATES_INVALID")
            elevation = row[2] if len(row) > 2 and row[2] is not None and -500 < row[2] < 9000 else None
            out.append([round(float(row[0]), 6), round(float(row[1]), 6), None if elevation is None else round(float(elevation), 1)])
        return out


class ServerIn(BaseModel):
    url: str = Field(default="", max_length=300)


async def _server(db: AsyncSession) -> str:
    row = await db.get(AppSetting, SERVER_KEY)
    try:
        return brouter.clean_url((row.value or {}).get("url") if row else None)
    except ValueError:
        return planner.DEFAULT_BROUTER_URL


def _server_payload(url: str, user: User) -> dict:
    return {"url": url, "default_url": planner.DEFAULT_BROUTER_URL, "is_default": url == planner.DEFAULT_BROUTER_URL,
            "editable": user.role == "admin"}


async def _speeds(db: AsyncSession, user: User) -> dict[str, float]:
    """Median recent speed per sport family – the planner's duration uses it when there are three or more."""
    since = datetime.now(timezone.utc) - timedelta(days=180)
    rows = (await db.execute(select(Activity.sport_type, Activity.subsport_type, Activity.distance_m, Activity.moving_seconds, Activity.duration_seconds)
                             .where(Activity.user_id == user.id, Activity.started_at >= since, Activity.distance_m > 500))).all()
    groups: dict[str, list[tuple[float | None, int | None]]] = {}
    for sport, sub, distance, moving, duration in rows:
        text = f"{sport or ''} {sub or ''}".lower()
        family = sport_family(text)
        key = "mtb" if "mountain" in text or "mtb" in text else "gravel" if "gravel" in text else "road_bike" if "road" in text and family == "cycling" else \
            "trail_running" if "trail" in text else family
        groups.setdefault(key, []).append((distance, moving or duration))
        if key in {"mtb", "gravel", "road_bike"}:
            groups.setdefault("cycling", []).append((distance, moving or duration))
        if key == "trail_running":
            groups.setdefault("running", []).append((distance, moving or duration))
    return {key: speed for key, rows_ in groups.items() if (speed := planner.personal_speed(rows_)) is not None}


def _speed_for(sport: str, speeds: dict[str, float]) -> float | None:
    family = planner.SPORTS[sport].family
    if sport in speeds:
        return speeds[sport]
    # Without rides of the same kind the cycling median is scaled: gravel and touring
    # rides are usually slower than the road rides that dominate most histories.
    if sport in {"road_bike", "gravel", "trekking"} and family in speeds:
        return round(speeds[family] * {"road_bike": 1.0, "gravel": 0.85, "trekking": 0.75}[sport], 1)
    if sport == "running" and "running" in speeds:
        return speeds["running"]
    if sport == "hiking":
        return speeds.get("hiking")
    return None


@router.get("/options")
async def options(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    weather = weather_config(await db.get(UserPreference, user.id))
    home = None
    if weather.get("latitude") is not None and weather.get("longitude") is not None:
        home = {"lat": float(weather["latitude"]), "lon": float(weather["longitude"]), "name": weather.get("location_name") or ""}
    speeds = await _speeds(db, user)
    return {"sports": [{"key": s.key, "default_km": s.default_km, "min_km": s.min_km, "max_km": s.max_km, "speed_kmh": _speed_for(s.key, speeds) or s.speed_kmh,
                        "personal_speed": _speed_for(s.key, speeds) is not None, "gpx_type": s.gpx_type} for s in planner.SPORTS.values()],
            "home": home, "server": _server_payload(await _server(db), user)}


@router.get("/places")
async def places(q: str = Query(min_length=2, max_length=120), language: str = Query("de", max_length=8), _: User = Depends(safety_confirmed_user)):
    try:
        return {"results": await search_locations(q, language)}
    except Exception:
        raise HTTPException(502, "PLACE_SEARCH_UNAVAILABLE") from None


@router.post("/plan")
async def plan(payload: PlanIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    sport = planner.SPORTS[payload.sport]
    speed = _speed_for(payload.sport, await _speeds(db, user))
    route = brouter.http_router(await _server(db))
    start = (payload.start.lat, payload.start.lon)
    try:
        if payload.mode == "round":
            km = payload.distance_km or sport.default_km
            if not sport.min_km <= km <= sport.max_km:
                raise HTTPException(422, "DISTANCE_OUT_OF_RANGE")
            variants = await brouter.round_trip(route, payload.sport, start, km * 1000, list(payload.preferences), payload.direction,
                                                payload.variants, payload.seed, speed)
        else:
            if payload.end is None:
                raise HTTPException(422, "END_REQUIRED")
            points = [start, *[(p.lat, p.lon) for p in payload.via], (payload.end.lat, payload.end.lon)]
            if planner.metres(points[0], points[-1]) < 100 and not payload.via:
                raise HTTPException(422, "START_EQUALS_END")
            variants = await brouter.a_to_b(route, payload.sport, points, list(payload.preferences), payload.variants, speed)
    except brouter.RoutingError as exc:
        log.info("tour planning failed: %s %s", exc.code, exc.detail)
        raise HTTPException(502 if exc.code in {"ROUTER_UNREACHABLE", "ROUTING_TIMEOUT", "SERVER_BUSY"} else 422, exc.code) from None
    for i, variant in enumerate(variants):
        variant["id"] = f"v{i + 1}"
    return {"variants": variants, "speed_kmh": speed or sport.speed_kmh, "personal_speed": speed is not None, "seed": payload.seed}


def _tour(row: PlannedTour, with_geometry: bool) -> dict:
    out = {"id": str(row.id), "name": row.name, "sport": row.sport, "mode": row.mode, "distance_m": row.distance_m, "ascent_m": row.ascent_m,
           "duration_s": row.duration_s, "summary": row.summary or {}, "created_at": row.created_at.isoformat() if row.created_at else None}
    if with_geometry:
        out["coordinates"] = row.geometry or []
    else:
        coords = row.geometry or []
        step = max(1, len(coords) // 60)
        out["preview"] = [[c[0], c[1]] for c in coords[::step]]
    return out


@router.get("")
async def list_tours(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(PlannedTour).where(PlannedTour.user_id == user.id).order_by(PlannedTour.created_at.desc()).limit(200))).all()
    return {"items": [_tour(r, False) for r in rows]}


@router.post("")
async def save_tour(payload: TourIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    keep = {k: payload.summary.get(k) for k in ("descent_m", "surface", "ways", "paved_share", "unpaved_share", "doubled", "min_elevation_m",
                                                  "max_elevation_m", "profile", "warnings", "start_name", "end_name", "preferences") if k in payload.summary}
    distance = float(payload.summary.get("distance_m") or 0) or sum(planner.metres((a[1], a[0]), (b[1], b[0])) for a, b in zip(payload.coordinates, payload.coordinates[1:]))
    ascent = payload.summary.get("ascent_m")
    if not isinstance(ascent, (int, float)):
        ascent = planner.climb([c[2] for c in payload.coordinates if c[2] is not None])[0]
    duration = payload.summary.get("duration_s")
    if not isinstance(duration, (int, float)):
        duration = planner.duration_s(payload.sport, distance, float(ascent))
    row = PlannedTour(user_id=user.id, name=payload.name, sport=payload.sport, mode=payload.mode, distance_m=round(distance), ascent_m=round(float(ascent)),
                      duration_s=int(duration), geometry=payload.coordinates, summary=keep)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _tour(row, False)


async def _owned(db: AsyncSession, user: User, tour_id: uuid.UUID) -> PlannedTour:
    row = await db.get(PlannedTour, tour_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "TOUR_NOT_FOUND")
    return row


@router.get("/{tour_id}")
async def get_tour(tour_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return _tour(await _owned(db, user, tour_id), True)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/{tour_id}")
async def rename_tour(tour_id: uuid.UUID, payload: RenameIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await _owned(db, user, tour_id)
    row.name = payload.name.strip() or row.name
    await db.commit()
    return _tour(row, False)


@router.delete("/{tour_id}")
async def delete_tour(tour_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, user, tour_id))
    await db.commit()
    return {"deleted": True}


@router.put("/server/settings")
async def set_server(payload: ServerIn, user: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    """Only administrators choose the routing server: the API calls this address itself."""
    try:
        url = brouter.clean_url(payload.url)
    except ValueError:
        raise HTTPException(422, "BROUTER_URL_INVALID") from None
    row = await db.get(AppSetting, SERVER_KEY)
    value = {"url": "" if url == planner.DEFAULT_BROUTER_URL else url}
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SERVER_KEY, value=value))
    await db.commit()
    return _server_payload(url, user)


class ServerTestIn(BaseModel):
    url: str = Field(default="", max_length=300)
    near: Point | None = None


@router.post("/server/test")
async def test_server(payload: ServerTestIn, user: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    """Route a 1 km piece near the training location (or Frankfurt) to check the server answers."""
    try:
        url = brouter.clean_url(payload.url) if payload.url.strip() else await _server(db)
    except ValueError:
        raise HTTPException(422, "BROUTER_URL_INVALID") from None
    weather = weather_config(await db.get(UserPreference, user.id))
    if payload.near:
        lat, lon = payload.near.lat, payload.near.lon
    elif weather.get("latitude") is not None:
        lat, lon = float(weather["latitude"]), float(weather["longitude"])
    else:
        lat, lon = 50.1109, 8.6821
    end = planner.destination(lat, lon, 90, 1000)
    try:
        result = await brouter.http_router(url)([(lat, lon), end], "trekking", {}, 0)
    except brouter.RoutingError as exc:
        return {"ok": False, "url": url, "code": exc.code, "detail": exc.detail}
    return {"ok": True, "url": url, "engine": result.get("engine"), "distance_m": result["distance_m"], "has_elevation": result["has_elevation"]}
