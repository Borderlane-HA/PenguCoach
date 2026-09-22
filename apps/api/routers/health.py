from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import Activity, DailyHealth, HrvDaily, SleepSession, User
from pengucoach.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


def _health(x: DailyHealth) -> dict:
    return {
        "date": x.date.isoformat(),
        "steps": x.steps,
        "distance_m": x.distance_m,
        "active_calories": x.active_calories,
        "resting_hr": x.resting_hr,
        "min_hr": x.min_hr,
        "max_hr": x.max_hr,
        "stress_avg": x.stress_avg,
        "body_battery_high": x.body_battery_high,
        "body_battery_low": x.body_battery_low,
        "hydration_ml": x.hydration_ml,
        "hydration_goal_ml": x.hydration_goal_ml,
        "respiration_avg": x.respiration_avg,
        "spo2_avg": x.spo2_avg,
        "training_readiness": x.training_readiness,
        "vo2max_running": x.vo2max_running,
        "updated_at": x.updated_at,
        "source": "garmin",
    }


def _vo2_sport(sport_type: str | None) -> str | None:
    value = (sport_type or "").lower()
    if "cycl" in value or "bike" in value or "biking" in value:
        return "cycling"
    if "run" in value:
        return "running"
    return None


async def _vo2_rows(db: AsyncSession, user_id, start_date: date | None = None) -> list:
    stmt = select(Activity.id, Activity.sport_type, Activity.started_at, Activity.vo2max).where(
        Activity.user_id == user_id,
        Activity.vo2max.is_not(None),
        Activity.started_at.is_not(None),
    )
    if start_date is not None:
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(Activity.started_at >= start_dt)
    result = await db.execute(stmt.order_by(Activity.started_at.asc()))
    return list(result.all())


def _vo2_history(rows: list) -> dict:
    series: dict[str, list[dict]] = {"running": [], "cycling": []}
    for row in rows:
        kind = _vo2_sport(row.sport_type)
        if kind and row.vo2max is not None and row.started_at is not None:
            series[kind].append({
                "date": row.started_at.date().isoformat(),
                "value": round(float(row.vo2max), 2),
                "activity_id": str(row.id),
            })
    return series


@router.get("/today")
async def today(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date == date.today()))
    sleep = await db.scalar(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date == date.today()))
    hrv = await db.scalar(select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date == date.today()))

    vo2 = _vo2_history(await _vo2_rows(db, user.id))
    latest_running = vo2["running"][-1]["value"] if vo2["running"] else None
    latest_cycling = vo2["cycling"][-1]["value"] if vo2["cycling"] else None

    if not row:
        return {
            "date": date.today().isoformat(),
            "available": False,
            "vo2max_running": latest_running,
            "vo2max_cycling": latest_cycling,
        }
    result = _health(row)
    result["available"] = True
    # Daily Garmin max-metrics remains the preferred current running value;
    # activity VO2 is the fallback and the source for sport-specific history.
    result["vo2max_running"] = latest_running or result.get("vo2max_running")
    result["vo2max_cycling"] = latest_cycling
    result["sleep"] = {
        "duration_seconds": sleep.duration_seconds,
        "score": sleep.sleep_score,
        "deep_seconds": sleep.deep_seconds,
        "rem_seconds": sleep.rem_seconds,
    } if sleep else None
    result["hrv"] = {
        "overnight_average": hrv.overnight_average,
        "highest_5min": hrv.highest_5min,
        "status": hrv.garmin_status,
    } if hrv else None
    return result


@router.get("/range")
async def health_range(
    days: int = Query(default=30, ge=1, le=9132),
    all_data: bool = Query(default=False, alias="all"),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    if all_data:
        health_stmt = select(DailyHealth).where(DailyHealth.user_id == user.id).order_by(DailyHealth.date)
        sleep_stmt = select(SleepSession).where(SleepSession.user_id == user.id).order_by(SleepSession.date)
        hrv_stmt = select(HrvDaily).where(HrvDaily.user_id == user.id).order_by(HrvDaily.date)
    else:
        start = date.today() - timedelta(days=days - 1)
        health_stmt = select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date >= start).order_by(DailyHealth.date)
        sleep_stmt = select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date >= start).order_by(SleepSession.date)
        hrv_stmt = select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date >= start).order_by(HrvDaily.date)

    health = (await db.scalars(health_stmt)).all()
    sleeps = (await db.scalars(sleep_stmt)).all()
    hrvs = (await db.scalars(hrv_stmt)).all()
    return {
        "days": None if all_data else days,
        "all": all_data,
        "health": [_health(x) for x in health],
        "sleep": [{
            "date": x.date.isoformat(),
            "duration_seconds": x.duration_seconds,
            "score": x.sleep_score,
            "deep_seconds": x.deep_seconds,
            "rem_seconds": x.rem_seconds,
            "avg_spo2": x.avg_spo2,
        } for x in sleeps],
        "hrv": [{
            "date": x.date.isoformat(),
            "overnight_average": x.overnight_average,
            "highest_5min": x.highest_5min,
            "status": x.garmin_status,
        } for x in hrvs],
    }


@router.get("/vo2-history")
async def vo2_history(
    days: int = Query(default=30, ge=1, le=9132),
    all_data: bool = Query(default=False, alias="all"),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    start = None if all_data else date.today() - timedelta(days=days - 1)
    series = _vo2_history(await _vo2_rows(db, user.id, start_date=start))
    return {
        **series,
        "days": None if all_data else days,
        "all": all_data,
        "latest": {
            "running": series["running"][-1]["value"] if series["running"] else None,
            "cycling": series["cycling"][-1]["value"] if series["cycling"] else None,
        },
        "source": "garmin_activity_summary",
    }
