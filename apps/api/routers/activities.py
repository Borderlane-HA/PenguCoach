import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import Activity, ActivityMetric, FitFile, GarminConnection, User
from pengucoach.db.session import get_db
from pengucoach.fit.activity_detail import selected_activity_extras, selected_garmin_extras
from pengucoach.sparkyfitness.activity_time import stored_time_info
from pengucoach.fit.service import load_recording_detail, load_recording_series
from pengucoach.imports.manual_activity import MAX_UPLOAD_BYTES, import_manual_activity
from worker.tasks.fit import analyze_fit

router = APIRouter(prefix="/activities", tags=["activities"])

_STATS_TTL_SECONDS = 30.0
_stats_cache: dict[uuid.UUID, tuple[float, dict]] = {}


def _manual_source_expr():
    return Activity.raw["source"].astext == "manual_upload"


def _sparky_source_expr():
    # Sparky-only activities and Garmin activities enriched from SparkyFitness
    # both carry the dedicated top-level JSONB key. This can use the partial
    # PostgreSQL index created in migration 0013 instead of casting the full
    # JSON payload to text.
    return Activity.raw.has_key("sparkyfitness")  # noqa: W601 - SQLAlchemy JSONB operator


async def _activity_stats(user_id: uuid.UUID, db: AsyncSession, *, use_cache: bool = True) -> dict:
    now = time.monotonic()
    cached = _stats_cache.get(user_id)
    if use_cache and cached and now - cached[0] < _STATS_TTL_SECONDS:
        return {**cached[1], "cached": True}

    manual = _manual_source_expr()
    sparky = _sparky_source_expr()
    row = (await db.execute(
        select(
            func.count(Activity.id).label("total"),
            func.count(Activity.id).filter(Activity.fit_status == "parsed").label("analyzed_total"),
            func.count(Activity.id).filter(manual).label("manual_total"),
            func.count(Activity.id).filter(Activity.garmin_activity_id > 0).label("garmin_total"),
            func.count(Activity.id).filter(sparky).label("sparky_total"),
            func.count(Activity.id).filter(and_(Activity.garmin_activity_id > 0, sparky)).label("merged_total"),
        ).where(Activity.user_id == user_id)
    )).one()
    result = {
        "total": int(row.total or 0),
        "analyzed_total": int(row.analyzed_total or 0),
        "manual_total": int(row.manual_total or 0),
        "garmin_total": int(row.garmin_total or 0),
        "sparky_total": int(row.sparky_total or 0),
        "merged_total": int(row.merged_total or 0),
        "cached": False,
        "cache_ttl_seconds": int(_STATS_TTL_SECONDS),
    }
    _stats_cache[user_id] = (now, result)
    return result



def _activity_sources(x: Activity) -> list[str]:
    raw = x.raw or {}
    primary = str(raw.get("source") or "garmin")
    sources: list[str] = [primary]
    if "sparkyfitness" in raw and "sparkyfitness" not in sources:
        sources.append("sparkyfitness")
    return sources


def _summary(x: Activity) -> dict:
    raw = x.raw or {}
    sources = _activity_sources(x)
    activity_time = stored_time_info(x)
    return {
        "id": str(x.id),
        "garmin_activity_id": x.garmin_activity_id,
        "name": x.name,
        "sport_type": x.sport_type,
        "subsport_type": x.subsport_type,
        "started_at": x.started_at,
        "time_precision": activity_time.get("precision", "second"),
        "activity_date": activity_time.get("local_date"),
        "record_timezone": activity_time.get("timezone"),
        "duration_seconds": x.duration_seconds,
        "moving_seconds": x.moving_seconds,
        "distance_m": x.distance_m,
        "calories": x.calories,
        "avg_hr": x.avg_hr,
        "max_hr": x.max_hr,
        "avg_speed": x.avg_speed,
        "avg_power": x.avg_power,
        "avg_cadence": x.avg_cadence,
        "vo2max": x.vo2max,
        "elevation_gain": x.elevation_gain,
        "training_load": x.training_load,
        "aerobic_training_effect": x.aerobic_training_effect,
        "anaerobic_training_effect": x.anaerobic_training_effect,
        "fit_status": x.fit_status,
        "source": sources[0],
        "sources": sources,
        "metric_sources": raw.get("_metric_sources", {}),
        "source_detail": raw.get("sparkyfitness_provider"),
        "original_filename": raw.get("filename"),
    }


async def _owned_activity(activity_id: uuid.UUID, user: User, db: AsyncSession) -> Activity:
    row = await db.get(Activity, activity_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="ACTIVITY_NOT_FOUND")
    return row


def _journal_filters(user: User, sport: str | None, source: str | None, q: str | None):
    """Filters shared by the activity journal and its recap."""
    filtered = [Activity.user_id == user.id]
    if sport:
        filtered.append(Activity.sport_type == sport)
    if source == "garmin":
        # Native Garmin IDs are positive. Activities enriched from SparkyFitness
        # remain part of the Garmin view as well.
        filtered.append(Activity.garmin_activity_id > 0)
    elif source == "sparkyfitness":
        filtered.append(_sparky_source_expr())
    elif source == "manual":
        filtered.append(_manual_source_expr())
    term = (q or "").strip()
    if term:
        pattern = f"%{term}%"
        # Search intentionally stays on concise indexed/structured fields. The
        # previous full-JSON text conversion forced PostgreSQL to scan every payload
        # payload on each keystroke, which became visible with large histories.
        filtered.append(or_(
            Activity.name.ilike(pattern),
            Activity.sport_type.ilike(pattern),
            Activity.subsport_type.ilike(pattern),
            Activity.raw["filename"].astext.ilike(pattern),
        ))
    return filtered, term


@router.get("")
async def list_activities(
    limit: int = Query(default=50, ge=1, le=500),
    page: int | None = Query(default=None, ge=1),
    per_page: int | None = Query(default=None, ge=10, le=100),
    q: str | None = Query(default=None, max_length=120),
    sport: str | None = None,
    source: str | None = Query(default=None, pattern="^(garmin|sparkyfitness|manual)$"),
    include_stats: bool = Query(default=True),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """List activities.

    The legacy ``limit`` response remains a plain array for dashboard callers.
    Supplying ``page`` or ``per_page`` enables the paginated response used by
    the activity journal. Alpha.45.1 lets the journal opt out of expensive
    summary statistics via ``include_stats=false`` and loads them independently
    from ``/activities/stats``.
    """
    filtered, term = _journal_filters(user, sport, source, q)

    paginated = page is not None or per_page is not None
    if not paginated:
        rows = (await db.scalars(
            select(Activity).where(*filtered).order_by(Activity.started_at.desc()).limit(limit)
        )).all()
        return [_summary(x) for x in rows]

    current_page = page or 1
    page_size = per_page or 50
    filtered_total = int((await db.scalar(select(func.count(Activity.id)).where(*filtered))) or 0)
    pages = max(1, (filtered_total + page_size - 1) // page_size)
    current_page = min(current_page, pages)
    offset = (current_page - 1) * page_size
    rows = (await db.scalars(
        select(Activity).where(*filtered).order_by(Activity.started_at.desc()).offset(offset).limit(page_size)
    )).all()
    response = {
        "items": [_summary(x) for x in rows],
        "page": current_page,
        "per_page": page_size,
        "pages": pages,
        "filtered_total": filtered_total,
        "query": term,
        "source_filter": source,
    }
    if include_stats:
        response.update(await _activity_stats(user.id, db))
    return response


@router.get("/stats")
async def activity_stats(
    refresh: bool = Query(default=False),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """Return activity source/status counters independently from the first page.

    The counters use one aggregate SQL statement and a short process-local TTL
    cache so revisiting the journal does not repeatedly scan the history.
    """
    return await _activity_stats(user.id, db, use_cache=not refresh)


RECAP_ROUTE_LIMIT = 300


def _recap_routes(paths: list[tuple[str, str]]) -> list[dict]:
    import pandas as pd
    from pengucoach.coach.recap import downsample
    routes = []
    for activity_id, path in paths:
        try:
            frame = pd.read_parquet(path, columns=["position_lat", "position_long"])
        except (OSError, ValueError, KeyError, ImportError):
            continue
        frame = frame.dropna()
        points = downsample(list(zip(frame["position_lat"].astype(float), frame["position_long"].astype(float))))
        if points:
            routes.append({"id": activity_id, "points": points})
    return routes


def _sparky_recap_routes(rows) -> list[dict]:
    from pengucoach.coach.recap import downsample
    from pengucoach.sparkyfitness.telemetry import telemetry
    routes = []
    for activity_id, raw in rows:
        points = [(p.get("lat"), p.get("lon")) for p in telemetry(raw).get("gps", []) if isinstance(p, dict)]
        points = [(float(a), float(b)) for a, b in points if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool)]
        thinned = downsample(points)
        if thinned:
            routes.append({"id": str(activity_id), "points": thinned})
    return routes


@router.get("/recap")
async def activity_recap(
    period: Literal["today", "week", "month", "year", "all"] = "month",
    q: str | None = Query(default=None, max_length=120),
    sport: str | None = None,
    source: str | None = Query(default=None, pattern="^(garmin|sparkyfitness|manual)$"),
    routes: bool = True,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """Animated recap of the filtered journal for a calendar period in the user's time zone."""
    from pengucoach.coach.recap import period_bounds, summarize
    from pengucoach.common.dates import day_start, user_zone
    zone = user_zone(user)
    today = datetime.now(zone).date()
    bounds = period_bounds(period, today)
    filtered, term = _journal_filters(user, sport, source, q)
    columns = (Activity.id, Activity.name, Activity.sport_type, Activity.started_at, Activity.duration_seconds,
               Activity.moving_seconds, Activity.distance_m, Activity.elevation_gain, Activity.calories,
               Activity.avg_power)

    async def load(start, end):
        conditions = [*filtered, Activity.started_at.is_not(None), Activity.started_at < day_start(end + timedelta(days=1), user)]
        if start is not None:
            conditions.append(Activity.started_at >= day_start(start, user))
        result = await db.execute(select(*columns).where(*conditions).order_by(Activity.started_at.desc()))
        rows = []
        for item in result.all():
            started = item.started_at if item.started_at.tzinfo else item.started_at.replace(tzinfo=timezone.utc)
            rows.append({"id": item.id, "name": item.name, "sport_type": item.sport_type,
                         "day": started.astimezone(zone).date(), "distance_m": item.distance_m,
                         "duration_s": item.moving_seconds or item.duration_seconds, "elevation_m": item.elevation_gain,
                         "calories": item.calories, "avg_power": item.avg_power})
        return rows

    current = await load(bounds["start"], bounds["end"])
    previous = await load(bounds["previous_start"], bounds["previous_end"]) if bounds["previous_start"] else None
    result = summarize(current, period=period, today=today, previous=previous)
    result.update(query=term, source_filter=source, timezone=str(zone), route_limit=RECAP_ROUTE_LIMIT, routes=[])
    if routes and current:
        ids = [row["id"] for row in current]
        fits = (await db.execute(select(FitFile.activity_id, FitFile.parquet_path).where(
            FitFile.user_id == user.id, FitFile.activity_id.in_(ids), FitFile.parquet_path.is_not(None)))).all()
        order = {activity_id: index for index, activity_id in enumerate(ids)}
        paths = sorted(((str(a), p) for a, p in fits), key=lambda item: order.get(uuid.UUID(item[0]), 0))[:RECAP_ROUTE_LIMIT]
        routes_found = await asyncio.to_thread(_recap_routes, paths)
        # SparkyFitness activities have no FIT file; their track lives in the activity row.
        with_fit = {a for a, _ in fits}
        sparky_ids = [i for i in ids if i not in with_fit][: max(0, RECAP_ROUTE_LIMIT - len(routes_found))]
        if sparky_ids:
            raws = (await db.execute(select(Activity.id, Activity.raw).where(
                Activity.user_id == user.id, Activity.id.in_(sparky_ids), Activity.raw.has_key("sparkyfitness")))).all()  # noqa: W601
            routes_found += _sparky_recap_routes(raws)
        routes_found.sort(key=lambda r: order.get(uuid.UUID(r["id"]), 0))
        result["routes"] = routes_found[:RECAP_ROUTE_LIMIT]
        result["routes_limited"] = len(fits) + len(sparky_ids) > RECAP_ROUTE_LIMIT
    return result


@router.post("/import")
async def import_activity(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    sport_type: str | None = Form(default=None),
    allow_overlap: bool = Form(default=False),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or "activity"
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="ACTIVITY_UPLOAD_TOO_LARGE")
    try:
        activity = await import_manual_activity(
            db, user, filename, raw,
            name_override=(name or "").strip() or None,
            sport_override=None if not sport_type or sport_type == "auto" else sport_type,
            allow_overlap=allow_overlap,
        )
    except ValueError as exc:
        code = str(exc)
        if code.startswith("DUPLICATE_UPLOAD:"):
            existing = code.split(":", 1)[1]
            raise HTTPException(status_code=409, detail={"code": "ACTIVITY_ALREADY_IMPORTED", "activity_id": existing}) from exc
        if code.startswith("ACTIVITY_OVERLAP:"):
            existing_id = uuid.UUID(code.split(":", 1)[1])
            other = await db.get(Activity, existing_id)
            raise HTTPException(status_code=409, detail={
                "code": "ACTIVITY_OVERLAP", "activity_id": str(existing_id),
                "activity": _summary(other) if other else None,
            }) from exc
        status = 413 if code == "UPLOAD_TOO_LARGE" else 400
        raise HTTPException(status_code=status, detail=code) from exc
    _stats_cache.pop(user.id, None)
    return {"activity_id": str(activity.id), "activity": _summary(activity)}


@router.get("/{activity_id}")
async def detail(
    activity_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_activity(activity_id, user, db)
    metric = await db.scalar(select(ActivityMetric).where(ActivityMetric.activity_id == row.id))
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == row.id))
    return {
        **_summary(row),
        "metrics": {
            "hr_drift": metric.hr_drift,
            "pace_drift": metric.pace_drift,
            "power_drift": metric.power_drift,
            "aerobic_decoupling": metric.aerobic_decoupling,
            "pace_consistency": metric.pace_consistency,
            "cadence_drift": metric.cadence_drift,
            "data_quality_score": metric.data_quality_score,
            "details": metric.details,
        } if metric else None,
        "fit": {
            "status": fit.status,
            "downloaded_at": fit.downloaded_at,
            "parsed_at": fit.parsed_at,
            "quality": fit.data_quality,
        } if fit else None,
        # Only expose a curated numeric subset instead of passing Garmin's entire raw payload to the UI.
        "garmin_extra": selected_garmin_extras(row.raw),
        "activity_extra": selected_activity_extras(row.raw),
    }


@router.get("/{activity_id}/series")
async def series(
    activity_id: uuid.UUID,
    limit: int = Query(default=3500, ge=100, le=10000),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_activity(activity_id, user, db)
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == row.id))
    data = await asyncio.to_thread(load_recording_series, row, fit, limit)
    return {"data": data}


@router.get("/{activity_id}/analysis")
async def activity_analysis(
    activity_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_activity(activity_id, user, db)
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == row.id))
    result = await asyncio.to_thread(load_recording_detail, row, fit)
    result["fit_status"] = row.fit_status
    return result


@router.post("/{activity_id}/fit/analyze")
async def enqueue_fit(
    activity_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_activity(activity_id, user, db)
    if "garmin" not in _activity_sources(row):
        raise HTTPException(status_code=409, detail="FIT_NOT_AVAILABLE_FOR_ACTIVITY_SOURCE")
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not conn or conn.status != "connected":
        raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    task = analyze_fit.apply_async(args=[str(user.id), str(row.id)], queue="fit")
    return {"queued": True, "task_id": task.id}
