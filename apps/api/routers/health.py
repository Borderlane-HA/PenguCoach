from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import Activity, BodyMeasurement, DailyHealth, HrvDaily, SleepSession, User
from pengucoach.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


BODY_FIELDS = (
    "weight_kg", "height_cm", "bmi", "body_fat_percent",
    "body_water_percent", "muscle_mass_kg", "bone_mass_kg",
)


class ManualBodyMeasurementIn(BaseModel):
    measured_on: date = Field(default_factory=date.today)
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    height_cm: float | None = Field(default=None, ge=50, le=260)
    body_fat_percent: float | None = Field(default=None, ge=1, le=75)
    body_water_percent: float | None = Field(default=None, ge=10, le=90)
    muscle_mass_kg: float | None = Field(default=None, ge=1, le=300)
    bone_mass_kg: float | None = Field(default=None, ge=0.1, le=30)

    @model_validator(mode="after")
    def require_value(self):
        if all(getattr(self, field) is None for field in (
            "weight_kg", "height_cm", "body_fat_percent", "body_water_percent",
            "muscle_mass_kg", "bone_mass_kg",
        )):
            raise ValueError("BODY_MEASUREMENT_EMPTY")
        return self


def _source(raw: dict | None) -> str:
    data = raw or {}
    if data.get("source") == "manual_body":
        return "manual"
    metric_sources = data.get("_metric_sources") if isinstance(data, dict) else None
    if isinstance(metric_sources, dict) and metric_sources and set(metric_sources.values()) == {"manual"}:
        return "manual"
    if "sparkyfitness" not in data:
        return "garmin"
    non_meta = {key for key in data.keys() if not str(key).startswith("_")}
    return "sparkyfitness" if non_meta <= {"sparkyfitness"} else "garmin+sparkyfitness"


def _metric_source(raw: dict | None, field: str, default: str | None = None) -> str | None:
    data = raw or {}
    sources = data.get("_metric_sources") if isinstance(data, dict) else None
    if isinstance(sources, dict) and isinstance(sources.get(field), str):
        return sources[field]
    return default or _source(raw)


def _health(x: DailyHealth) -> dict:
    fields = {
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
    }
    sources = {key: _metric_source(x.raw, key) for key, value in fields.items() if value is not None}
    return {
        "date": x.date.isoformat(),
        **fields,
        "updated_at": x.updated_at,
        "source": _source(x.raw),
        "sources": sources,
    }


def _body_row(x: BodyMeasurement) -> dict[str, Any]:
    values = {field: getattr(x, field) for field in BODY_FIELDS}
    return {
        "measured_at": x.measured_at,
        **values,
        "source": _source(x.raw),
        "sources": {field: _metric_source(x.raw, field) for field, value in values.items() if value is not None},
    }


def _body_latest(rows: list[BodyMeasurement]) -> dict[str, Any] | None:
    if not rows:
        return None
    result: dict[str, Any] = {"measured_at": None, "sources": {}}
    latest_dt: datetime | None = None
    for row in sorted(rows, key=lambda item: item.measured_at, reverse=True):
        for field in BODY_FIELDS:
            if result.get(field) is None:
                value = getattr(row, field)
                if value is not None:
                    result[field] = value
                    result["sources"][field] = _metric_source(row.raw, field)
                    if latest_dt is None or row.measured_at > latest_dt:
                        latest_dt = row.measured_at
    result["measured_at"] = latest_dt
    if all(result.get(field) is None for field in BODY_FIELDS):
        return None
    return result


async def _body_rows(db: AsyncSession, user_id, start_date: date | None = None) -> list[BodyMeasurement]:
    stmt = select(BodyMeasurement).where(BodyMeasurement.user_id == user_id)
    if start_date is not None:
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(BodyMeasurement.measured_at >= start_dt)
    return list((await db.scalars(stmt.order_by(BodyMeasurement.measured_at.asc()))).all())


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
    body = _body_latest(await _body_rows(db, user.id))

    vo2 = _vo2_history(await _vo2_rows(db, user.id))
    latest_running = vo2["running"][-1]["value"] if vo2["running"] else None
    latest_cycling = vo2["cycling"][-1]["value"] if vo2["cycling"] else None

    if not row:
        return {
            "date": date.today().isoformat(),
            "available": False,
            "vo2max_running": latest_running,
            "vo2max_cycling": latest_cycling,
            "body": body,
        }
    result = _health(row)
    result["available"] = True
    result["vo2max_running"] = latest_running or result.get("vo2max_running")
    result["vo2max_cycling"] = latest_cycling
    result["sleep"] = {
        "duration_seconds": sleep.duration_seconds,
        "score": sleep.sleep_score,
        "deep_seconds": sleep.deep_seconds,
        "rem_seconds": sleep.rem_seconds,
        "source": _metric_source(sleep.raw, "duration_seconds") or _source(sleep.raw),
    } if sleep else None
    result["hrv"] = {
        "overnight_average": hrv.overnight_average,
        "highest_5min": hrv.highest_5min,
        "status": hrv.garmin_status,
        "source": _metric_source(hrv.raw, "overnight_average") or _source(hrv.raw),
    } if hrv else None
    result["body"] = body
    return result


@router.get("/range")
async def health_range(
    days: int = Query(default=30, ge=1, le=9132),
    all_data: bool = Query(default=False, alias="all"),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    if all_data:
        start = None
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
    body_rows = await _body_rows(db, user.id, start)
    # Current body/profile values are fallbacks rather than period-only facts:
    # a manually entered height/weight remains useful until a newer Garmin or
    # SparkyFitness measurement supplies that same metric. Charts still honour
    # the selected period, while the current cards use the latest known value.
    body_all_rows = await _body_rows(db, user.id)
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
            "source": _metric_source(x.raw, "duration_seconds") or _source(x.raw),
        } for x in sleeps],
        "hrv": [{
            "date": x.date.isoformat(),
            "overnight_average": x.overnight_average,
            "highest_5min": x.highest_5min,
            "status": x.garmin_status,
            "source": _metric_source(x.raw, "overnight_average") or _source(x.raw),
        } for x in hrvs],
        "body": [_body_row(x) for x in body_rows],
        "body_latest": _body_latest(body_all_rows),
    }


@router.put("/body/manual")
async def save_manual_body_measurement(
    payload: ManualBodyMeasurementIn,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    day_start = datetime.combine(payload.measured_on, time.min, tzinfo=timezone.utc)
    day_end = datetime.combine(payload.measured_on, time.max, tzinfo=timezone.utc)
    rows = list((await db.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user.id,
        BodyMeasurement.measured_at >= day_start,
        BodyMeasurement.measured_at <= day_end,
    ).order_by(BodyMeasurement.measured_at.desc()))).all())
    row = next((item for item in rows if (item.raw or {}).get("source") == "manual_body"), None)
    if row is None:
        # Keep the manual snapshot at the end of its calendar day. A measurement
        # from Garmin/SparkyFitness on a later day naturally supersedes it, while
        # the manual fallback remains available indefinitely if no newer value
        # exists for a specific metric.
        row = BodyMeasurement(
            user_id=user.id,
            measured_at=datetime.combine(payload.measured_on, time(23, 59, 59), tzinfo=timezone.utc),
            raw={"source": "manual_body", "_metric_sources": {}},
        )
        db.add(row)
    values = payload.model_dump(exclude={"measured_on"}, exclude_none=True)
    sources = dict((row.raw or {}).get("_metric_sources") or {})
    for field, value in values.items():
        setattr(row, field, value)
        sources[field] = "manual"

    # BMI is deterministic and useful to Coach/Training. Recalculate it only
    # when this manual entry actually changes weight or height; the other part
    # may come from the latest known profile value. This avoids relabelling
    # unrelated connected-source metrics as manual.
    if "weight_kg" in values or "height_cm" in values:
        all_rows = await _body_rows(db, user.id)
        latest = _body_latest([item for item in all_rows if item.id != row.id]) or {}
        effective_weight = row.weight_kg if row.weight_kg is not None else latest.get("weight_kg")
        effective_height = row.height_cm if row.height_cm is not None else latest.get("height_cm")
        if effective_weight and effective_height:
            row.bmi = round(float(effective_weight) / ((float(effective_height) / 100.0) ** 2), 2)
            sources["bmi"] = "manual"
    row.raw = {"source": "manual_body", "_metric_sources": sources}
    await db.commit()
    await db.refresh(row)
    return {"saved": True, "measurement": _body_row(row), "current": _body_latest(await _body_rows(db, user.id))}


@router.delete("/body/manual/{measured_on}")
async def delete_manual_body_measurement(
    measured_on: date,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    day_start = datetime.combine(measured_on, time.min, tzinfo=timezone.utc)
    day_end = datetime.combine(measured_on, time.max, tzinfo=timezone.utc)
    rows = list((await db.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user.id,
        BodyMeasurement.measured_at >= day_start,
        BodyMeasurement.measured_at <= day_end,
    ))).all())
    manual = [row for row in rows if (row.raw or {}).get("source") == "manual_body"]
    if not manual:
        raise HTTPException(status_code=404, detail="MANUAL_BODY_MEASUREMENT_NOT_FOUND")
    for row in manual:
        await db.delete(row)
    await db.commit()
    return {"deleted": True, "date": measured_on.isoformat()}


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
