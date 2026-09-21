from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import DailyHealth, HrvDaily, SleepSession, User
from pengucoach.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


def _health(x: DailyHealth) -> dict:
    return {"date": x.date.isoformat(), "steps": x.steps, "distance_m": x.distance_m, "active_calories": x.active_calories, "resting_hr": x.resting_hr, "min_hr": x.min_hr, "max_hr": x.max_hr, "stress_avg": x.stress_avg, "body_battery_high": x.body_battery_high, "body_battery_low": x.body_battery_low, "hydration_ml": x.hydration_ml, "hydration_goal_ml": x.hydration_goal_ml, "respiration_avg": x.respiration_avg, "spo2_avg": x.spo2_avg, "training_readiness": x.training_readiness, "vo2max_running": x.vo2max_running, "updated_at": x.updated_at, "source": "garmin"}


@router.get("/today")
async def today(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date == date.today()))
    sleep = await db.scalar(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date == date.today()))
    hrv = await db.scalar(select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date == date.today()))
    if not row: return {"date": date.today().isoformat(), "available": False}
    result = _health(row); result["available"] = True
    result["sleep"] = {"duration_seconds": sleep.duration_seconds, "score": sleep.sleep_score, "deep_seconds": sleep.deep_seconds, "rem_seconds": sleep.rem_seconds} if sleep else None
    result["hrv"] = {"overnight_average": hrv.overnight_average, "highest_5min": hrv.highest_5min, "status": hrv.garmin_status} if hrv else None
    return result


@router.get("/range")
async def health_range(days: int = Query(default=30, ge=1, le=3650), user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    start = date.today() - timedelta(days=days - 1)
    health = (await db.scalars(select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date >= start).order_by(DailyHealth.date))).all()
    sleeps = (await db.scalars(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date >= start).order_by(SleepSession.date))).all()
    hrvs = (await db.scalars(select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date >= start).order_by(HrvDaily.date))).all()
    return {"days": days, "health": [_health(x) for x in health], "sleep": [{"date": x.date.isoformat(), "duration_seconds": x.duration_seconds, "score": x.sleep_score, "deep_seconds": x.deep_seconds, "rem_seconds": x.rem_seconds, "avg_spo2": x.avg_spo2} for x in sleeps], "hrv": [{"date": x.date.isoformat(), "overnight_average": x.overnight_average, "highest_5min": x.highest_5min, "status": x.garmin_status} for x in hrvs]}
