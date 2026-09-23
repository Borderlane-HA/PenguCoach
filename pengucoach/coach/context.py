from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import Activity, ActivityMetric, BodyMeasurement, DailyHealth, FitFile, HrvDaily, SleepSession, SourceRecord, User
from pengucoach.fit.activity_detail import selected_activity_extras
from pengucoach.fit.service import load_activity_detail
from pengucoach.garmin.zones import activity_zone_time, training_zone_snapshot


SOURCE_NOTICE = (
    "Each summary contains a source field. Direct Garmin summaries are authoritative Garmin totals when present; "
    "SparkyFitness is a secondary read-only source that can include Apple Health and other providers and may overlap "
    "with direct Garmin data. Do not double-count apparently identical sessions. manual_upload summaries come from "
    "imported FIT/GPX/TCX files. PenguCoach analytics are locally calculated supplements. Missing values are null and "
    "must not be invented."
)


def _context_start_date(end_date: date, lookback_days: int) -> date:
    """Return the first calendar date for an inclusive activity-analysis context window."""
    days = lookback_days if lookback_days in {0, 1, 3, 7} else 7
    if days == 0:
        return end_date
    return end_date - timedelta(days=days - 1)


def _activity_garmin(a: Activity) -> dict[str, Any]:
    raw = a.raw or {}
    source = raw.get("source", "garmin")
    if source == "garmin" and "sparkyfitness" in raw:
        source = "garmin+sparkyfitness"
    extra = selected_activity_extras(raw)
    return {
        "activity_id": str(a.id),
        "garmin_activity_id": a.garmin_activity_id if source in {"garmin", "garmin+sparkyfitness"} else None,
        "name": a.name,
        "sport": a.sport_type,
        "subsport": a.subsport_type,
        "started_at": a.started_at,
        "duration_s": a.duration_seconds,
        "moving_s": a.moving_seconds,
        "distance_m": a.distance_m,
        "calories_kcal": a.calories,
        "heart_rate": {
            "min_bpm": extra.get("min_hr_bpm"),
            "avg_bpm": a.avg_hr,
            "max_bpm": a.max_hr,
        },
        "speed": {
            "avg_mps": a.avg_speed,
            "max_mps": extra.get("max_speed_mps"),
        },
        "elevation": {
            "gain_m": a.elevation_gain if a.elevation_gain is not None else extra.get("elevation_gain_m"),
            "loss_m": extra.get("elevation_loss_m"),
            "min_m": extra.get("min_elevation_m"),
            "max_m": extra.get("max_elevation_m"),
        },
        "power": {
            "avg_w": a.avg_power,
            "max_w": extra.get("max_power_w"),
            "normalized_w": extra.get("normalized_power_w"),
        },
        "cadence": {
            "avg_rpm": a.avg_cadence,
            "max_rpm": extra.get("max_cadence"),
        },
        "vo2max_ml_kg_min": a.vo2max,
        "training_load": a.training_load,
        "aerobic_training_effect": a.aerobic_training_effect,
        "anaerobic_training_effect": a.anaerobic_training_effect,
        "fit_status": a.fit_status,
        "source": source,
        "source_file": raw.get("filename") if source == "manual_upload" else None,
    }


def _metric_payload(metric: ActivityMetric | None) -> dict[str, Any] | None:
    if not metric:
        return None
    return {
        "analytics_version": metric.analytics_version,
        "hr_drift_pct": metric.hr_drift,
        "pace_drift_pct": metric.pace_drift,
        "power_drift_pct": metric.power_drift,
        "aerobic_decoupling_pct": metric.aerobic_decoupling,
        "pace_consistency": metric.pace_consistency,
        "cadence_drift_pct": metric.cadence_drift,
        "data_quality_score": metric.data_quality_score,
        "source": "pengucoach",
    }


def _window_summary(rows: list[Activity], end_date: date, days: int) -> dict[str, Any]:
    start_date = end_date - timedelta(days=max(0, days - 1))
    selected = [a for a in rows if a.started_at and start_date <= a.started_at.date() <= end_date]
    loads = [float(a.training_load) for a in selected if a.training_load is not None]
    durations = [float(a.duration_seconds) for a in selected if a.duration_seconds is not None]
    distances = [float(a.distance_m) for a in selected if a.distance_m is not None]
    training_dates = {a.started_at.date() for a in selected if a.started_at}
    sports = Counter((a.sport_type or "unknown") for a in selected)
    return {
        "days": days,
        "from": start_date,
        "to": end_date,
        "activity_count": len(selected),
        "training_days": len(training_dates),
        "rest_days": max(0, days - len(training_dates)),
        "duration_hours": round(sum(durations) / 3600.0, 2),
        "distance_km": round(sum(distances) / 1000.0, 2),
        "garmin_training_load_total": round(sum(loads), 1) if loads else None,
        "garmin_training_load_avg": round(sum(loads) / len(loads), 1) if loads else None,
        "sport_counts": dict(sports),
    }


def _row_source(raw: dict[str, Any] | None) -> str:
    data = raw or {}
    if "sparkyfitness" not in data:
        return "garmin"
    # New rows created only from SparkyFitness contain just the namespaced raw payload.
    # Existing Garmin rows retain their original raw keys and are therefore mixed-source.
    return "sparkyfitness" if set(data.keys()) <= {"sparkyfitness"} else "garmin+sparkyfitness"


def _compact_sparky_session(record: SourceRecord) -> dict[str, Any]:
    payload = record.payload if isinstance(record.payload, dict) else {}
    def first(*keys: str):
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return value
        return None
    return {
        "date": record.record_date,
        "name": first("name", "workout_name", "title", "exercise_name"),
        "sport": first("sport", "sport_type", "activity_type", "exercise_type", "category"),
        "duration_minutes": first("duration_minutes", "total_duration_minutes", "duration"),
        "distance": first("distance", "distance_km", "distance_m"),
        "calories": first("calories_burned", "calories"),
        "avg_heart_rate": first("avg_heart_rate", "average_heart_rate", "avg_hr"),
        "provider_source": first("source", "provider", "provider_name"),
        "source": "sparkyfitness",
    }


async def _sparky_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: date,
    end_date: date,
    limit: int = 80,
    exclude_external_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(SourceRecord).where(
        SourceRecord.user_id == user_id,
        SourceRecord.source == "sparkyfitness",
        SourceRecord.domain == "exercise_session",
        SourceRecord.record_date >= start_date,
        SourceRecord.record_date <= end_date,
    ).order_by(SourceRecord.record_date.desc(), SourceRecord.fetched_at.desc()).limit(max(limit * 3, limit)))).all()
    excluded = exclude_external_ids or set()
    selected = [x for x in rows if not x.external_id or str(x.external_id) not in excluded][:limit]
    return [_compact_sparky_session(x) for x in selected]


def _materialized_sparky_ids(rows: list[Activity]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        raw = row.raw or {}
        one = raw.get("sparkyfitness_external_id")
        if one:
            ids.add(str(one))
        for value in raw.get("sparkyfitness_external_ids") or []:
            ids.add(str(value))
    return ids


def _metric_source(raw: dict[str, Any] | None, field: str) -> str:
    data = raw or {}
    sources = data.get("_metric_sources") if isinstance(data, dict) else None
    if isinstance(sources, dict) and isinstance(sources.get(field), str):
        return str(sources[field])
    return _row_source(raw)


BODY_CONTEXT_FIELDS = (
    "weight_kg", "height_cm", "bmi", "body_fat_percent",
    "body_water_percent", "muscle_mass_kg", "bone_mass_kg",
)


def _body_snapshot(rows: list[BodyMeasurement]) -> dict[str, Any] | None:
    result: dict[str, Any] = {"sources": {}, "measured_at": None}
    latest_dt = None
    for row in sorted(rows, key=lambda x: x.measured_at, reverse=True):
        for field in BODY_CONTEXT_FIELDS:
            if result.get(field) is None:
                value = getattr(row, field, None)
                if value is not None:
                    result[field] = value
                    result["sources"][field] = _metric_source(row.raw, field)
                    if latest_dt is None or row.measured_at > latest_dt:
                        latest_dt = row.measured_at
    if all(result.get(field) is None for field in BODY_CONTEXT_FIELDS):
        return None
    result["measured_at"] = latest_dt
    return result


async def _body_context(db: AsyncSession, user_id: uuid.UUID, start_date: date, end_date: date) -> dict[str, Any] | None:
    recent = list((await db.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user_id,
        BodyMeasurement.measured_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
        BodyMeasurement.measured_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc),
    ).order_by(BodyMeasurement.measured_at))).all())
    all_rows = list((await db.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user_id
    ).order_by(BodyMeasurement.measured_at.desc()).limit(1000))).all())
    latest = _body_snapshot(all_rows)
    if latest is None and not recent:
        return None
    return {
        "latest": latest,
        "recent": [{
            "measured_at": row.measured_at,
            **{field: getattr(row, field, None) for field in BODY_CONTEXT_FIELDS},
            "sources": {field: _metric_source(row.raw, field) for field in BODY_CONTEXT_FIELDS if getattr(row, field, None) is not None},
        } for row in recent[-30:]],
    }


def _health_payload(rows: list[DailyHealth]) -> list[dict[str, Any]]:
    return [{
        "date": x.date,
        "steps": x.steps,
        "resting_hr_bpm": x.resting_hr,
        "stress_avg": x.stress_avg,
        "body_battery_high": x.body_battery_high,
        "body_battery_low": x.body_battery_low,
        "hydration_ml": x.hydration_ml,
        "hydration_goal_ml": x.hydration_goal_ml,
        "training_readiness": x.training_readiness,
        "vo2max_running": x.vo2max_running,
        "source": _row_source(x.raw),
        "sources": {
            field: _metric_source(x.raw, field) for field in (
                "steps", "resting_hr", "stress_avg", "body_battery_high",
                "hydration_ml", "training_readiness", "vo2max_running"
            ) if getattr(x, field, None) is not None
        },
    } for x in rows]


def _sleep_payload(rows: list[SleepSession]) -> list[dict[str, Any]]:
    return [{
        "date": x.date,
        "duration_s": x.duration_seconds,
        "score": x.sleep_score,
        "deep_s": x.deep_seconds,
        "light_s": x.light_seconds,
        "rem_s": x.rem_seconds,
        "awake_s": x.awake_seconds,
        "source": _row_source(x.raw),
    } for x in rows]


def _hrv_payload(rows: list[HrvDaily]) -> list[dict[str, Any]]:
    return [{
        "date": x.date,
        "overnight_ms": x.overnight_average,
        "highest_5min_ms": x.highest_5min,
        "baseline_low_ms": x.garmin_baseline_low,
        "baseline_high_ms": x.garmin_baseline_high,
        "status": x.garmin_status,
        "source": _row_source(x.raw),
    } for x in rows]


async def _recovery_window(db: AsyncSession, user_id: uuid.UUID, start_date: date, end_date: date) -> tuple[list[DailyHealth], list[SleepSession], list[HrvDaily]]:
    health = (await db.scalars(select(DailyHealth).where(
        DailyHealth.user_id == user_id, DailyHealth.date >= start_date, DailyHealth.date <= end_date
    ).order_by(DailyHealth.date))).all()
    sleep = (await db.scalars(select(SleepSession).where(
        SleepSession.user_id == user_id, SleepSession.date >= start_date, SleepSession.date <= end_date
    ).order_by(SleepSession.date))).all()
    hrv = (await db.scalars(select(HrvDaily).where(
        HrvDaily.user_id == user_id, HrvDaily.date >= start_date, HrvDaily.date <= end_date
    ).order_by(HrvDaily.date))).all()
    return list(health), list(sleep), list(hrv)


async def build_coach_context(db: AsyncSession, user: User, days: int = 30) -> dict[str, Any]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, days) - 1)
    health, sleep, hrv = await _recovery_window(db, user.id, start, end)
    activities = (await db.scalars(select(Activity).where(
        Activity.user_id == user.id,
        Activity.started_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
    ).order_by(Activity.started_at.desc()).limit(40))).all()
    activity_context: list[dict[str, Any]] = []
    for a in activities:
        metric = await db.scalar(select(ActivityMetric).where(ActivityMetric.activity_id == a.id))
        activity_context.append({"garmin": _activity_garmin(a), "pengucoach": _metric_payload(metric)})
    zones = await training_zone_snapshot(db, user.id)
    sparky_sessions = await _sparky_sessions(db, user.id, start, end, limit=40, exclude_external_ids=_materialized_sparky_ids(list(activities)))
    body = await _body_context(db, user.id, start, end)
    return {
        "source_notice": SOURCE_NOTICE,
        "training_zones": zones,
        "period_days": days,
        "summary_7d": _window_summary(list(activities), end, min(7, days)),
        "summary_28d": _window_summary(list(activities), end, min(28, days)),
        "health_30d": _health_payload(health),
        "sleep_30d": _sleep_payload(sleep),
        "hrv_30d": _hrv_payload(hrv),
        "recent_activities": activity_context[:20],
        "sparkyfitness_sessions": sparky_sessions[:20],
        "body_profile": body,
    }


async def build_activity_analysis_context(
    db: AsyncSession,
    user: User,
    activity_id: uuid.UUID,
    lookback_days: int = 7,
) -> dict[str, Any]:
    activity = await db.get(Activity, activity_id)
    if not activity or activity.user_id != user.id:
        raise ValueError("ACTIVITY_NOT_FOUND")
    metric = await db.scalar(select(ActivityMetric).where(ActivityMetric.activity_id == activity.id))
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == activity.id))
    fit_detail: dict[str, Any] = {"stats": None, "splits": []}
    if fit and fit.status == "parsed" and fit.parquet_path:
        try:
            fit_detail = await asyncio.to_thread(load_activity_detail, fit, activity.sport_type)
        except Exception:
            fit_detail = {"stats": None, "splits": []}

    zones = await training_zone_snapshot(db, user.id)
    zone_time = await asyncio.to_thread(
        activity_zone_time,
        fit.parquet_path if fit and fit.status == "parsed" else None,
        activity.sport_type,
        zones,
    )

    end_dt = activity.started_at or datetime.now(timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    end_date = end_dt.date()
    lookback_days = lookback_days if lookback_days in {0, 1, 3, 7} else 7
    # 0 = only this session; 1 = calendar day of the session; 3/7 = inclusive calendar-day windows.
    # Using days - 1 avoids accidentally turning a 3-day request into four calendar dates.
    start_date = _context_start_date(end_date, lookback_days)

    prior: list[Activity] = []
    health: list[DailyHealth] = []
    sleep: list[SleepSession] = []
    hrv: list[HrvDaily] = []
    if lookback_days:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        prior = list((await db.scalars(select(Activity).where(
            Activity.user_id == user.id,
            Activity.started_at >= start_dt,
            Activity.started_at < end_dt,
        ).order_by(Activity.started_at))).all())
        health, sleep, hrv = await _recovery_window(db, user.id, start_date, end_date)

    prior_payload = [_activity_garmin(a) for a in prior]
    current = {
        "garmin": _activity_garmin(activity),
        "pengucoach": _metric_payload(metric),
        "fit_analytics_source": "pengucoach_fit",
        "fit_analytics": fit_detail.get("stats"),
        "training_zones": zones,
        "time_in_zones": zone_time,
        "splits_source": "pengucoach_fit",
        "splits": (fit_detail.get("splits") or [])[:120],
    }
    scope = {0: "session_only", 1: "activity_day", 3: "three_days", 7: "seven_days"}[lookback_days]
    body = await _body_context(db, user.id, start_date, end_date)
    lookback: dict[str, Any] = {
        "scope": scope,
        "days": lookback_days,
        "from": start_date if lookback_days else None,
        "to": end_date if lookback_days else None,
        "activities": prior_payload,
        "health": _health_payload(health),
        "sleep": _sleep_payload(sleep),
        "hrv": _hrv_payload(hrv),
        "body_profile": body,
    }
    if lookback_days == 1:
        lookback["summary_day"] = _window_summary(prior, end_date, 1)
    if lookback_days >= 3:
        lookback["summary_3d"] = _window_summary(prior, end_date, 3)
    if lookback_days >= 7:
        lookback["summary_7d"] = _window_summary(prior, end_date, 7)
    return {"source_notice": SOURCE_NOTICE, "activity": current, "lookback": lookback}


async def build_training_plan_context(
    db: AsyncSession,
    user: User,
    days: int = 7,
    *,
    include_training: bool = True,
    include_zones: bool = True,
    include_sleep_hrv: bool = True,
    include_recovery: bool = True,
    include_daily_activity: bool = False,
) -> dict[str, Any]:
    """Build the explicitly selected training-plan context.

    Training plans intentionally use a short recent window (3/7/14/21/28 days).
    The caller also chooses which categories are disclosed to the model so the
    prompt mirrors the briefing a human coach would receive.
    """
    days = days if days in {3, 7, 14, 21, 28} else 7
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)

    activities: list[Activity] = []
    activity_payload: list[dict[str, Any]] = []
    if include_training:
        activities = list((await db.scalars(select(Activity).where(
            Activity.user_id == user.id, Activity.started_at >= start_dt
        ).order_by(Activity.started_at))).all())
        metric_map: dict[uuid.UUID, ActivityMetric] = {}
        activity_ids = [a.id for a in activities]
        if activity_ids:
            metrics = list((await db.scalars(select(ActivityMetric).where(ActivityMetric.activity_id.in_(activity_ids)))).all())
            metric_map = {m.activity_id: m for m in metrics}
        activity_payload = [
            {"garmin": _activity_garmin(a), "pengucoach_fit": _metric_payload(metric_map.get(a.id))}
            for a in activities[-40:]
        ]

    health: list[DailyHealth] = []
    sleep: list[SleepSession] = []
    hrv: list[HrvDaily] = []
    if include_sleep_hrv or include_recovery or include_daily_activity:
        health, sleep, hrv = await _recovery_window(db, user.id, start, end)

    body = await _body_context(db, user.id, start, end)

    lookback: dict[str, Any] = {
        "days": days,
        "from": start,
        "to": end,
        "selected_data": {
            "training_and_fit": include_training,
            "training_zones": include_zones,
            "sleep_and_hrv": include_sleep_hrv,
            "recovery": include_recovery,
            "steps_and_hydration": include_daily_activity,
        },
    }
    lookback["body_profile"] = body

    if include_training:
        lookback["summary_period"] = _window_summary(activities, end, days)
        lookback["sparkyfitness_sessions"] = await _sparky_sessions(db, user.id, start, end, limit=80, exclude_external_ids=_materialized_sparky_ids(activities))
        if days > 7:
            lookback["summary_recent_7d"] = _window_summary(activities, end, 7)
        lookback["activities"] = activity_payload

    if include_sleep_hrv:
        lookback["sleep"] = _sleep_payload(sleep)
        lookback["hrv"] = _hrv_payload(hrv)

    if include_recovery or include_daily_activity:
        daily: list[dict[str, Any]] = []
        for row in health:
            item: dict[str, Any] = {"date": row.date, "source": _row_source(row.raw), "sources": {}}
            if include_recovery:
                item.update({
                    "resting_hr_bpm": row.resting_hr,
                    "stress_avg": row.stress_avg,
                    "body_battery_high": row.body_battery_high,
                    "body_battery_low": row.body_battery_low,
                    "training_readiness": row.training_readiness,
                    "vo2max_running": row.vo2max_running,
                })
            if include_daily_activity:
                item.update({
                    "steps": row.steps,
                    "hydration_ml": row.hydration_ml,
                    "hydration_goal_ml": row.hydration_goal_ml,
                })
            for field in ("resting_hr", "stress_avg", "body_battery_high", "body_battery_low", "training_readiness", "vo2max_running", "steps", "hydration_ml", "hydration_goal_ml"):
                if getattr(row, field, None) is not None:
                    item["sources"][field] = _metric_source(row.raw, field)
            daily.append(item)
        lookback["daily_health"] = daily

    return {
        "source_notice": SOURCE_NOTICE,
        "training_zones": await training_zone_snapshot(db, user.id) if include_zones else None,
        "lookback": lookback,
    }
