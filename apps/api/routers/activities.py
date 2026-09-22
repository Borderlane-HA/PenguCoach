import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import Activity, ActivityMetric, FitFile, GarminConnection, User
from pengucoach.db.session import get_db
from pengucoach.fit.activity_detail import selected_garmin_extras
from pengucoach.fit.service import load_activity_detail, load_activity_series
from pengucoach.imports.manual_activity import MAX_UPLOAD_BYTES, import_manual_activity
from worker.tasks.fit import analyze_fit

router = APIRouter(prefix="/activities", tags=["activities"])


def _summary(x: Activity) -> dict:
    return {
        "id": str(x.id),
        "garmin_activity_id": x.garmin_activity_id,
        "name": x.name,
        "sport_type": x.sport_type,
        "subsport_type": x.subsport_type,
        "started_at": x.started_at,
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
        "source": (x.raw or {}).get("source", "garmin"),
        "original_filename": (x.raw or {}).get("filename"),
    }


async def _owned_activity(activity_id: uuid.UUID, user: User, db: AsyncSession) -> Activity:
    row = await db.get(Activity, activity_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="ACTIVITY_NOT_FOUND")
    return row


@router.get("")
async def list_activities(
    limit: int = Query(default=50, ge=1, le=500),
    page: int | None = Query(default=None, ge=1),
    per_page: int | None = Query(default=None, ge=10, le=100),
    q: str | None = Query(default=None, max_length=120),
    sport: str | None = None,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """List activities.

    The legacy ``limit`` response remains a plain array for dashboard callers.
    Supplying ``page`` or ``per_page`` enables the paginated response used by
    the activity journal. Search is performed server-side over the complete
    activity history, not just the currently visible page.
    """
    base_filters = [Activity.user_id == user.id]
    if sport:
        base_filters.append(Activity.sport_type == sport)

    filtered = list(base_filters)
    term = (q or "").strip()
    if term:
        pattern = f"%{term}%"
        filtered.append(or_(
            Activity.name.ilike(pattern),
            Activity.sport_type.ilike(pattern),
            Activity.subsport_type.ilike(pattern),
            cast(Activity.raw, String).ilike(pattern),
        ))

    paginated = page is not None or per_page is not None
    if not paginated:
        rows = (await db.scalars(
            select(Activity).where(*filtered).order_by(Activity.started_at.desc()).limit(limit)
        )).all()
        return [_summary(x) for x in rows]

    current_page = page or 1
    page_size = per_page or 50
    total = int((await db.scalar(select(func.count(Activity.id)).where(*base_filters))) or 0)
    filtered_total = int((await db.scalar(select(func.count(Activity.id)).where(*filtered))) or 0)
    analyzed_total = int((await db.scalar(select(func.count(Activity.id)).where(
        Activity.user_id == user.id, Activity.fit_status == "parsed"
    ))) or 0)
    # JSONB source metadata is intentionally queried through its string
    # representation here so the same expression also works in lightweight
    # test databases without PostgreSQL-specific JSON operators.
    manual_total = int((await db.scalar(select(func.count(Activity.id)).where(
        Activity.user_id == user.id, cast(Activity.raw, String).ilike('%manual_upload%')
    ))) or 0)

    pages = max(1, (filtered_total + page_size - 1) // page_size)
    current_page = min(current_page, pages)
    offset = (current_page - 1) * page_size
    rows = (await db.scalars(
        select(Activity).where(*filtered).order_by(Activity.started_at.desc()).offset(offset).limit(page_size)
    )).all()
    return {
        "items": [_summary(x) for x in rows],
        "page": current_page,
        "per_page": page_size,
        "pages": pages,
        "total": total,
        "filtered_total": filtered_total,
        "analyzed_total": analyzed_total,
        "manual_total": manual_total,
        "query": term,
    }


@router.post("/import")
async def import_activity(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    sport_type: str | None = Form(default=None),
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
        )
    except ValueError as exc:
        code = str(exc)
        if code.startswith("DUPLICATE_UPLOAD:"):
            existing = code.split(":", 1)[1]
            raise HTTPException(status_code=409, detail={"code": "ACTIVITY_ALREADY_IMPORTED", "activity_id": existing}) from exc
        status = 413 if code == "UPLOAD_TOO_LARGE" else 400
        raise HTTPException(status_code=status, detail=code) from exc
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
    data = await asyncio.to_thread(load_activity_series, fit, limit) if fit else []
    return {"data": data}


@router.get("/{activity_id}/analysis")
async def activity_analysis(
    activity_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_activity(activity_id, user, db)
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == row.id))
    if not fit or fit.status != "parsed" or not fit.parquet_path:
        return {"stats": None, "splits": [], "fit_status": row.fit_status}
    result = await asyncio.to_thread(load_activity_detail, fit, row.sport_type)
    result["fit_status"] = row.fit_status
    return result


@router.post("/{activity_id}/fit/analyze")
async def enqueue_fit(
    activity_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_activity(activity_id, user, db)
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not conn or conn.status != "connected":
        raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    task = analyze_fit.apply_async(args=[str(user.id), str(row.id)], queue="fit")
    return {"queued": True, "task_id": task.id}
