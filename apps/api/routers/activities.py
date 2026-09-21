import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import Activity, ActivityMetric, FitFile, GarminConnection, User
from pengucoach.db.session import get_db
from pengucoach.fit.service import load_activity_series
from worker.tasks.fit import analyze_fit

router = APIRouter(prefix="/activities", tags=["activities"])


def _summary(x: Activity) -> dict:
    return {"id": str(x.id), "garmin_activity_id": x.garmin_activity_id, "name": x.name, "sport_type": x.sport_type, "started_at": x.started_at, "duration_seconds": x.duration_seconds, "distance_m": x.distance_m, "calories": x.calories, "avg_hr": x.avg_hr, "max_hr": x.max_hr, "avg_speed": x.avg_speed, "avg_power": x.avg_power, "avg_cadence": x.avg_cadence, "elevation_gain": x.elevation_gain, "training_load": x.training_load, "aerobic_training_effect": x.aerobic_training_effect, "fit_status": x.fit_status}


@router.get("")
async def list_activities(limit: int = Query(default=50, ge=1, le=500), sport: str | None = None, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Activity).where(Activity.user_id == user.id)
    if sport: stmt = stmt.where(Activity.sport_type == sport)
    rows = (await db.scalars(stmt.order_by(Activity.started_at.desc()).limit(limit))).all()
    return [_summary(x) for x in rows]


@router.get("/{activity_id}")
async def detail(activity_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(Activity, activity_id)
    if not row or row.user_id != user.id: raise HTTPException(status_code=404, detail="ACTIVITY_NOT_FOUND")
    metric = await db.scalar(select(ActivityMetric).where(ActivityMetric.activity_id == row.id))
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == row.id))
    return {**_summary(row), "metrics": {"hr_drift": metric.hr_drift, "pace_drift": metric.pace_drift, "power_drift": metric.power_drift, "aerobic_decoupling": metric.aerobic_decoupling, "pace_consistency": metric.pace_consistency, "cadence_drift": metric.cadence_drift, "data_quality_score": metric.data_quality_score, "details": metric.details} if metric else None, "fit": {"status": fit.status, "downloaded_at": fit.downloaded_at, "parsed_at": fit.parsed_at, "quality": fit.data_quality} if fit else None, "garmin": row.raw}


@router.get("/{activity_id}/series")
async def series(activity_id: uuid.UUID, limit: int = Query(default=2500, ge=100, le=10000), user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(Activity, activity_id)
    if not row or row.user_id != user.id: raise HTTPException(status_code=404, detail="ACTIVITY_NOT_FOUND")
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == row.id))
    return {"data": load_activity_series(fit, limit) if fit else []}


@router.post("/{activity_id}/fit/analyze")
async def enqueue_fit(activity_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(Activity, activity_id)
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not row or row.user_id != user.id: raise HTTPException(status_code=404, detail="ACTIVITY_NOT_FOUND")
    if not conn or conn.status != "connected": raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    task = analyze_fit.apply_async(args=[str(user.id), str(row.id)], queue="fit")
    return {"queued": True, "task_id": task.id}
