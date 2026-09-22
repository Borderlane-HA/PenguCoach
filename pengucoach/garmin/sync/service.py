import asyncio
import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import (
    Activity, BodyMeasurement, DailyHealth, GarminConnection, GarminSyncRun, GarminSyncSetting,
    HrvDaily, SleepSession, SourceRecord, User,
)
from pengucoach.garmin.gateway.factory import gateway_from_connection, serialize_refreshed_token


class GarminRequestTimeout(RuntimeError):
    def __init__(self, domain: str, seconds: int) -> None:
        self.domain = domain
        self.seconds = seconds
        super().__init__(f"GARMIN_REQUEST_TIMEOUT:{domain}:{seconds}s")


def _hash_payload(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _first_number(payload: Any, *keys: str) -> float | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        for value in payload.values():
            found = _first_number(value, *keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _first_number(item, *keys)
            if found is not None:
                return found
    return None


def _first_text(payload: Any, *keys: str) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _first_text(value, *keys)
            if found:
                return found
    return None


async def _store_raw(db: AsyncSession, user: User, domain: str, day: date, payload: Any, external_id: str | None = None) -> bool:
    if payload in (None, {}, []):
        return False
    digest = _hash_payload(payload)
    exists = await db.scalar(select(SourceRecord.id).where(
        SourceRecord.user_id == user.id, SourceRecord.domain == domain,
        SourceRecord.record_date == day, SourceRecord.content_hash == digest,
    ))
    if not exists:
        db.add(SourceRecord(user_id=user.id, source="garmin", domain=domain, external_id=external_id, record_date=day, content_hash=digest, payload=payload))
        return True
    return False


async def _call(domain: str, func: Callable[[], Any], domains: dict[str, Any], timeout_seconds: int = 90) -> Any:
    try:
        value = await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout_seconds)
        domains[domain] = {"ok": True, "available": value not in (None, {}, [])}
        return value
    except asyncio.TimeoutError as exc:
        domains[domain] = {"ok": False, "error": "GarminRequestTimeout", "timeout_seconds": timeout_seconds}
        raise GarminRequestTimeout(domain, timeout_seconds) from exc
    except GarminConnectTooManyRequestsError:
        raise
    except GarminConnectAuthenticationError:
        raise
    except Exception as exc:
        # One missing/unsupported Garmin endpoint must not fail the whole daily sync.
        domains[domain] = {"ok": False, "error": type(exc).__name__}
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def _upsert_health(db: AsyncSession, user: User, day: date, data: dict[str, Any], preserve_missing: bool = False) -> None:
    row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date == day))
    if not row:
        row = DailyHealth(user_id=user.id, date=day)
        db.add(row)
    summary = data.get("daily") or {}
    heart = data.get("heart") or {}
    hydration = data.get("hydration") or {}
    stress = data.get("stress") or {}
    body_battery = data.get("body_battery") or {}
    respiration = data.get("respiration") or {}
    spo2 = data.get("spo2") or {}
    readiness = data.get("training_readiness") or {}
    max_metrics = data.get("max_metrics") or {}
    intensity = data.get("intensity") or {}
    row.steps = int(_first_number(summary, "totalSteps", "steps") or 0) or None
    row.distance_m = _first_number(summary, "totalDistanceMeters", "distance", "totalDistance")
    row.active_calories = _first_number(summary, "activeKilocalories", "activeCalories")
    row.resting_calories = _first_number(summary, "bmrKilocalories", "restingCalories")
    row.resting_hr = int(_first_number(heart, "restingHeartRate") or _first_number(summary, "restingHeartRate") or 0) or None
    if heart or not preserve_missing:
        row.min_hr = int(_first_number(heart, "minHeartRate", "minHeartRateInBeatsPerMinute") or 0) or None
        row.max_hr = int(_first_number(heart, "maxHeartRate", "maxHeartRateInBeatsPerMinute") or 0) or None
    row.stress_avg = _first_number(stress, "avgStressLevel", "averageStressLevel", "overallStressLevel")
    if isinstance(body_battery, list) and body_battery:
        values = []
        for item in body_battery:
            if isinstance(item, dict):
                for k in ("charged", "drained", "bodyBatteryLevel", "bodyBattery"):
                    if isinstance(item.get(k), (int, float)):
                        values.append(float(item[k]))
        if values:
            row.body_battery_high, row.body_battery_low = int(max(values)), int(min(values))
    if hydration or not preserve_missing:
        row.hydration_ml = int(_first_number(hydration, "valueInML", "waterConsumedInML", "hydrationAmount", "totalHydration") or 0) or None
        row.hydration_goal_ml = int(_first_number(hydration, "goalInML", "hydrationGoal", "goal") or 0) or None
    if intensity or not preserve_missing:
        row.intensity_moderate = int(_first_number(intensity, "moderateIntensityMinutes", "moderateMinutes") or 0) or None
        row.intensity_vigorous = int(_first_number(intensity, "vigorousIntensityMinutes", "vigorousMinutes") or 0) or None
    if respiration or not preserve_missing:
        row.respiration_avg = _first_number(respiration, "avgWakingRespirationValue", "avgRespiration", "averageRespiration")
    if spo2 or not preserve_missing:
        row.spo2_avg = _first_number(spo2, "averageSpO2", "avgSpO2", "averageSpo2")
    if readiness or not preserve_missing:
        row.training_readiness = _first_number(readiness, "score", "trainingReadinessScore")
    row.vo2max_running = _first_number(max_metrics, "vo2MaxPreciseValue", "vo2MaxValue", "vo2Max")
    row.raw = data


async def _upsert_sleep(db: AsyncSession, user: User, day: date, payload: Any) -> None:
    if not isinstance(payload, dict) or not payload:
        return
    row = await db.scalar(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date == day))
    if not row:
        row = SleepSession(user_id=user.id, date=day)
        db.add(row)
    dto = payload.get("dailySleepDTO") if isinstance(payload.get("dailySleepDTO"), dict) else payload
    row.start_at = _parse_dt(dto.get("sleepStartTimestampGMT") or dto.get("sleepStartTimestampLocal") or dto.get("sleepStartTimestamp"))
    row.end_at = _parse_dt(dto.get("sleepEndTimestampGMT") or dto.get("sleepEndTimestampLocal") or dto.get("sleepEndTimestamp"))
    row.duration_seconds = int(_first_number(dto, "sleepTimeSeconds", "durationInSeconds") or 0) or None
    row.deep_seconds = int(_first_number(dto, "deepSleepSeconds") or 0) or None
    row.light_seconds = int(_first_number(dto, "lightSleepSeconds") or 0) or None
    row.rem_seconds = int(_first_number(dto, "remSleepSeconds") or 0) or None
    row.awake_seconds = int(_first_number(dto, "awakeSleepSeconds", "awakeSeconds") or 0) or None
    row.sleep_score = _first_number(payload, "overallScore", "sleepScore", "value")
    row.avg_respiration = _first_number(payload, "averageRespirationValue", "avgRespiration")
    row.avg_spo2 = _first_number(payload, "averageSpO2Value", "averageSpO2")
    row.min_spo2 = _first_number(payload, "lowestSpO2Value", "minSpO2")
    row.raw = payload


async def _upsert_hrv(db: AsyncSession, user: User, day: date, payload: Any) -> None:
    if not isinstance(payload, dict) or not payload:
        return
    row = await db.scalar(select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date == day))
    if not row:
        row = HrvDaily(user_id=user.id, date=day)
        db.add(row)
    row.overnight_average = _first_number(payload, "lastNightAvg", "weeklyAvg", "overnightAvg")
    row.highest_5min = _first_number(payload, "lastNight5MinHigh", "highest5Min")
    row.garmin_baseline_low = _first_number(payload, "balancedLow", "baselineLowUpper")
    row.garmin_baseline_high = _first_number(payload, "balancedUpper", "baselineBalancedUpper")
    row.garmin_status = _first_text(payload, "status", "hrvStatus")
    row.raw = payload


async def _upsert_body(db: AsyncSession, user: User, day: date, payload: Any) -> None:
    if not isinstance(payload, (dict, list)) or not payload:
        return
    # Normalize a best-effort daily body snapshot while retaining the complete raw Garmin payload.
    weight = _first_number(payload, "weight", "weightKg", "weightInGrams")
    if weight is not None and weight > 500:
        weight = weight / 1000.0
    measured_at = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    row = await db.scalar(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.measured_at == measured_at))
    if not row:
        row = BodyMeasurement(user_id=user.id, measured_at=measured_at)
        db.add(row)
    row.weight_kg = weight
    row.bmi = _first_number(payload, "bmi")
    row.body_fat_percent = _first_number(payload, "bodyFat", "bodyFatPercentage", "percentFat")
    row.body_water_percent = _first_number(payload, "bodyWater", "bodyWaterPercentage", "percentHydration")
    muscle = _first_number(payload, "muscleMass", "muscleMassKg", "muscleMassInGrams")
    if muscle is not None and muscle > 500:
        muscle = muscle / 1000.0
    row.muscle_mass_kg = muscle
    row.raw = payload if isinstance(payload, dict) else {"records": payload}


async def _upsert_activities(db: AsyncSession, user: User, activities: list[dict[str, Any]] | None) -> tuple[int, list[Activity]]:
    """Upsert an activity page with one lookup instead of one query per row.

    Historical Garmin accounts can contain thousands of activities. Batch-loading
    existing IDs keeps a full-history import bounded by pages rather than by an
    N+1 database query pattern.
    """
    payloads: list[tuple[int, dict[str, Any]]] = []
    seen: set[int] = set()
    for item in activities or []:
        raw_id = item.get("activityId")
        if raw_id in (None, ""):
            continue
        try:
            activity_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if activity_id in seen:
            continue
        seen.add(activity_id)
        payloads.append((activity_id, item))

    if not payloads:
        return 0, []

    ids = [activity_id for activity_id, _ in payloads]
    existing = (await db.scalars(select(Activity).where(
        Activity.user_id == user.id, Activity.garmin_activity_id.in_(ids)
    ))).all()
    by_id = {int(row.garmin_activity_id): row for row in existing}

    inserted = 0
    rows: list[Activity] = []
    for activity_id, item in payloads:
        row = by_id.get(activity_id)
        if row is None:
            row = Activity(user_id=user.id, garmin_activity_id=activity_id)
            db.add(row)
            by_id[activity_id] = row
            inserted += 1
        row.name = item.get("activityName")
        atype = item.get("activityType") or {}
        row.sport_type = atype.get("typeKey") if isinstance(atype, dict) else str(atype)
        row.subsport_type = str(atype.get("parentTypeId")) if isinstance(atype, dict) and atype.get("parentTypeId") is not None else None
        row.started_at = _parse_dt(item.get("startTimeGMT") or item.get("startTimeLocal") or item.get("beginTimestamp"))
        row.duration_seconds = int(item.get("duration") or 0) or None
        row.moving_seconds = int(item.get("movingDuration") or 0) or None
        row.distance_m = float(item.get("distance") or 0) or None
        row.calories = float(item.get("calories") or 0) or None
        row.avg_hr = int(item.get("averageHR") or 0) or None
        row.max_hr = int(item.get("maxHR") or 0) or None
        row.avg_speed = float(item.get("averageSpeed") or 0) or None
        row.avg_power = float(item.get("avgPower") or item.get("averagePower") or 0) or None
        row.avg_cadence = float(item.get("averageRunningCadenceInStepsPerMinute") or item.get("averageBikingCadenceInRevPerMinute") or 0) or None
        row.vo2max = float(item.get("vO2MaxValue") or item.get("vo2MaxValue") or 0) or None
        row.elevation_gain = float(item.get("elevationGain") or 0) or None
        row.training_load = float(item.get("activityTrainingLoad") or 0) or None
        row.aerobic_training_effect = float(item.get("aerobicTrainingEffect") or 0) or None
        row.anaerobic_training_effect = float(item.get("anaerobicTrainingEffect") or 0) or None
        row.raw = item
        rows.append(row)
    await db.flush()
    return inserted, rows


async def sync_day(
    db: AsyncSession,
    user: User,
    connection: GarminConnection,
    day: date,
    include_activities: bool = True,
    gateway=None,
    raw_client=None,
    detail_level: str = "full",
) -> dict[str, Any]:
    if gateway is None or raw_client is None:
        gateway, raw_client = await gateway_from_connection(connection)
    setting = await db.get(GarminSyncSetting, user.id)
    domains: dict[str, Any] = {}
    data: dict[str, Any] = {}
    calls: list[tuple[str, Callable[[], Any]]] = []
    core_history = detail_level == "core"
    if not setting or setting.sync_health:
        calls.extend([
            ("daily", lambda: gateway.get_user_summary(day)),
            ("sleep", lambda: gateway.get_sleep_data(day)),
            ("hrv", lambda: gateway.get_hrv_data(day)),
            ("stress", lambda: gateway.get_stress_data(day)),
            ("body_battery", lambda: gateway.get_body_battery(day)),
        ])
        if not core_history:
            calls.extend([
                ("heart", lambda: gateway.get_heart_rates(day)),
                ("hydration", lambda: gateway.get_hydration_data(day)),
                ("respiration", lambda: gateway.get_respiration_data(day)),
                ("spo2", lambda: gateway.get_spo2_data(day)),
                ("intensity", lambda: gateway.get_intensity_minutes_data(day)),
                ("floors", lambda: gateway.get_floors(day)),
            ])
    if not setting or setting.sync_training:
        if core_history:
            calls.append(("max_metrics", lambda: gateway.get_max_metrics(day)))
        else:
            calls.extend([
                ("training_readiness", lambda: gateway.get_training_readiness(day)),
                ("training_status", lambda: gateway.get_training_status(day)),
                ("max_metrics", lambda: gateway.get_max_metrics(day)),
            ])
    if not setting or setting.sync_body:
        # The full endpoint bundles stats + body. Historical core mode already
        # requested daily stats, so use the body-only date-range call to avoid
        # fetching the same daily summary twice.
        if core_history:
            calls.append(("body", lambda: gateway.get_body_composition(day, day)))
        else:
            calls.append(("body", lambda: gateway.get_stats_and_body(day)))
    for domain, func in calls:
        value = await _call(domain, func, domains)
        data[domain] = value
        await _store_raw(db, user, domain, day, value)
    activities = None
    activity_rows: list[Activity] = []
    inserted = 0
    if include_activities and (not setting or setting.sync_activities):
        activities = await _call("activities", lambda: gateway.get_activities_by_date(day, day), domains)
        if isinstance(activities, list):
            inserted, activity_rows = await _upsert_activities(db, user, activities)
            await _store_raw(db, user, "activities", day, activities)
    if not setting or setting.sync_health:
        await _upsert_health(db, user, day, data, preserve_missing=core_history)
        await _upsert_sleep(db, user, day, data.get("sleep"))
        await _upsert_hrv(db, user, day, data.get("hrv"))
    if (not setting or setting.sync_body) and data.get("body"):
        await _upsert_body(db, user, day, data.get("body"))
    connection.token_ciphertext = serialize_refreshed_token(raw_client)
    connection.last_validated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"date": day.isoformat(), "domains": domains, "activities": len(activities or []), "activity_rows": activity_rows, "inserted": inserted}


async def run_incremental_sync(db: AsyncSession, user: User, connection: GarminConnection) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    if connection.cooldown_until and connection.cooldown_until > now:
        return {"status": "cooldown", "until": connection.cooldown_until.isoformat()}
    run = GarminSyncRun(user_id=user.id, sync_type="incremental")
    db.add(run); await db.flush()
    try:
        # Look back one day because Garmin can finalize sleep/recovery values later.
        results = []
        for day in (date.today() - timedelta(days=1), date.today()):
            results.append(await sync_day(db, user, connection, day, include_activities=True))
        setting = await db.get(GarminSyncSetting, user.id)
        interval = setting.interval_minutes if setting else settings.garmin_default_interval_minutes
        jitter = random.randint(0, max(1, min(5, interval // 6)))
        connection.last_successful_sync_at = now
        connection.next_sync_at = now + timedelta(minutes=interval + jitter)
        connection.cooldown_until = None
        connection.consecutive_errors = 0
        connection.last_error_code = None
        run.status = "success"; run.finished_at = datetime.now(timezone.utc)
        run.domains = {r["date"]: r["domains"] for r in results}
        run.records_read = sum(r["activities"] for r in results)
        run.records_inserted = sum(r["inserted"] for r in results)
        await db.commit()
        return {"status": "success", "days": results, "read_only": True}
    except GarminConnectTooManyRequestsError:
        connection.consecutive_errors += 1
        minutes = min(360, settings.garmin_rate_limit_cooldown_minutes * max(1, 2 ** (connection.consecutive_errors - 1)))
        connection.cooldown_until = now + timedelta(minutes=minutes)
        connection.last_error_code = "GARMIN_RATE_LIMITED"; connection.last_error_at = now
        run.status = "rate_limited"; run.error_code = "GARMIN_RATE_LIMITED"; run.finished_at = now
        await db.commit()
        return {"status": "rate_limited", "cooldown_until": connection.cooldown_until.isoformat()}
    except GarminConnectAuthenticationError:
        connection.status = "reauth_required"; connection.last_error_code = "GARMIN_REAUTH_REQUIRED"; connection.last_error_at = now
        run.status = "failed"; run.error_code = "GARMIN_REAUTH_REQUIRED"; run.finished_at = now
        await db.commit()
        return {"status": "reauth_required"}
    except Exception as exc:
        connection.consecutive_errors += 1; connection.last_error_code = "GARMIN_SYNC_FAILED"; connection.last_error_at = now
        run.status = "failed"; run.error_code = "GARMIN_SYNC_FAILED"; run.error_message_safe = type(exc).__name__; run.finished_at = now
        await db.commit()
        raise
