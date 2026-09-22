from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import Activity, BodyMeasurement, DailyHealth, HrvDaily, SleepSession, SourceRecord, SparkyFitnessConnection
from pengucoach.security.crypto import SecretBox
from pengucoach.sparkyfitness.client import SparkyFitnessClient, SparkyFitnessError


def _json_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return None if n is None else int(round(n))


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _list_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("sessions", "items", "entries", "history", "data", "results", "profiles"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _session_date(item: dict[str, Any]) -> date | None:
    return _as_date(_first(item, "entry_date", "entryDate", "date", "started_at", "start_time", "startTime", "created_at", "createdAt"))


def _session_id(item: dict[str, Any], index: int) -> str:
    value = _first(item, "id", "session_id", "exercise_entry_id", "external_id")
    if value is not None:
        return str(value)
    return f"derived-{_json_hash(item)[:24]}-{index}"


def _nested_first(item: dict[str, Any], *keys: str) -> Any:
    value = _first(item, *keys)
    if value is not None:
        return value
    for container in ("activity", "activity_details", "activityDetails", "garmin_activity_details", "garminActivityDetails", "workout", "session", "exercise"):
        nested = item.get(container)
        if isinstance(nested, dict):
            value = _first(nested, *keys)
            if value is not None:
                return value
    return None


def _duration_seconds(item: dict[str, Any]) -> int | None:
    seconds = _num(_nested_first(item, "duration_seconds", "durationSeconds", "duration_in_seconds", "durationInSeconds", "elapsed_seconds", "elapsedSeconds", "total_timer_time", "totalTimerTime"))
    if seconds is not None:
        return max(0, int(round(seconds)))
    minutes = _num(_nested_first(item, "duration_minutes", "durationMinutes", "minutes"))
    if minutes is not None:
        return max(0, int(round(minutes * 60)))
    start = _as_dt(_nested_first(item, "started_at", "start_time", "startTime", "start_at", "startAt", "timestamp"))
    end = _as_dt(_nested_first(item, "ended_at", "end_time", "endTime", "end_at", "endAt"))
    if start and end and end >= start:
        return int((end - start).total_seconds())
    return None


def _distance_m(item: dict[str, Any]) -> float | None:
    value = _num(_nested_first(item, "distance_m", "distanceMeters", "distance_in_meters", "distanceInMeters", "total_distance", "totalDistance"))
    if value is not None:
        return max(0.0, value)
    km = _num(_nested_first(item, "distance_km", "distanceKm", "distance_in_km", "distanceInKm"))
    if km is not None:
        return max(0.0, km * 1000.0)
    raw = _num(_nested_first(item, "distance"))
    if raw is None:
        return None
    unit = str(_nested_first(item, "distance_unit", "distanceUnit", "unit") or "").lower()
    if "km" in unit or "kilomet" in unit:
        return max(0.0, raw * 1000.0)
    return max(0.0, raw)


def _sport(item: dict[str, Any]) -> str:
    raw = str(_nested_first(item, "sport_type", "sportType", "activity_type", "activityType", "type", "exercise_type", "exerciseType", "category") or "other").strip().lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    if any(token in normalized for token in ("road_bik", "cycling", "biking", "bicycle", "bike")):
        return "cycling"
    if "run" in normalized or "jog" in normalized:
        return "running"
    if "swim" in normalized:
        return "swimming"
    if "walk" in normalized:
        return "walking"
    if "hik" in normalized:
        return "hiking"
    if any(token in normalized for token in ("strength", "weight", "resistance")):
        return "strength"
    if "yoga" in normalized:
        return "yoga"
    if "pilates" in normalized:
        return "pilates"
    if any(token in normalized for token in ("mobility", "stretch")):
        return "mobility"
    return normalized or "other"


def _sport_family(value: str | None) -> str:
    v = (value or "").lower()
    if any(x in v for x in ("cycl", "bike", "biking")):
        return "cycling"
    if "run" in v or "jog" in v:
        return "running"
    if "swim" in v:
        return "swimming"
    if "walk" in v:
        return "walking"
    if "hik" in v:
        return "hiking"
    if any(x in v for x in ("strength", "weight", "resistance")):
        return "strength"
    if any(x in v for x in ("mobility", "stretch", "yoga", "pilates")):
        return "mobility"
    return v or "other"


def _session_started_at(item: dict[str, Any]) -> datetime | None:
    return _as_dt(_nested_first(item, "started_at", "start_time", "startTime", "start_at", "startAt", "timestamp", "entry_timestamp", "entryTimestamp", "created_at", "createdAt", "entry_date", "date"))


def _session_name(item: dict[str, Any]) -> str:
    value = _nested_first(item, "name", "activity_name", "activityName", "workout_name", "workoutName", "exercise_name", "exerciseName", "title")
    return str(value).strip()[:255] if value else "SparkyFitness activity"


def _provider(item: dict[str, Any]) -> str | None:
    value = _nested_first(item, "provider", "provider_name", "providerName", "source", "source_name", "sourceName", "origin")
    return str(value).strip()[:128] if value else None


def _synthetic_activity_id(external_id: str) -> int:
    value = int.from_bytes(hashlib.sha256(f"sparkyfitness:{external_id}".encode()).digest()[:8], "big") & ((1 << 62) - 1)
    return -max(1, value)


def _close_number(a: float | int | None, b: float | int | None, *, absolute: float, relative: float) -> bool:
    if a is None or b is None:
        return True
    aa, bb = float(a), float(b)
    return abs(aa - bb) <= max(absolute, max(abs(aa), abs(bb)) * relative)


async def _merge_activity(db: AsyncSession, user_id: uuid.UUID, item: dict[str, Any], external_id: str) -> tuple[str, uuid.UUID | None]:
    started_at = _session_started_at(item)
    if started_at is None:
        return "skipped", None
    duration = _duration_seconds(item)
    distance = _distance_m(item)
    sport = _sport(item)
    name = _session_name(item)
    provider = _provider(item)

    # A SparkyFitness history row can also represent one strength exercise
    # rather than a complete workout. Only expose rows with session-level
    # evidence in the activity diary; every row is still kept as SourceRecord
    # for AI/context use.
    session_marker = _nested_first(
        item, "activity_id", "activityId", "workout_id", "workoutId",
        "session_id", "sessionId", "workout_session_id", "workoutSessionId",
        "exercise_preset_entry_id", "exercisePresetEntryId",
    )
    session_name = _nested_first(item, "activity_name", "activityName", "workout_name", "workoutName")
    has_activity_container = any(isinstance(item.get(k), dict) for k in (
        "activity", "activity_details", "activityDetails", "garmin_activity_details", "garminActivityDetails", "workout", "session"
    ))
    if duration is None and distance is None and session_marker is None and session_name is None and not has_activity_container:
        return "skipped", None

    window_start = started_at - timedelta(minutes=3)
    window_end = started_at + timedelta(minutes=3)
    candidates = (await db.scalars(select(Activity).where(
        Activity.user_id == user_id,
        Activity.garmin_activity_id > 0,
        Activity.started_at >= window_start,
        Activity.started_at <= window_end,
    ))).all()
    for candidate in candidates:
        if _sport_family(candidate.sport_type) != _sport_family(sport):
            continue
        if not _close_number(candidate.duration_seconds, duration, absolute=180, relative=0.08):
            continue
        if not _close_number(candidate.distance_m, distance, absolute=500, relative=0.03):
            continue
        raw = dict(candidate.raw or {})
        raw["sparkyfitness"] = item
        ids = list(dict.fromkeys([*(raw.get("sparkyfitness_external_ids") or []), external_id]))
        raw["sparkyfitness_external_ids"] = ids[-20:]
        if provider:
            raw["sparkyfitness_provider"] = provider
        candidate.raw = raw
        return "merged", candidate.id

    synthetic = _synthetic_activity_id(external_id)
    while await db.scalar(select(Activity.id).where(Activity.user_id == user_id, Activity.garmin_activity_id == synthetic)):
        existing = await db.scalar(select(Activity).where(Activity.user_id == user_id, Activity.garmin_activity_id == synthetic))
        if existing and str((existing.raw or {}).get("sparkyfitness_external_id")) == external_id:
            raw = dict(existing.raw or {})
            raw["sparkyfitness"] = item
            if provider:
                raw["sparkyfitness_provider"] = provider
            existing.raw = raw
            for field, value in {
                "name": name,
                "sport_type": sport,
                "started_at": started_at,
                "duration_seconds": duration,
                "moving_seconds": duration,
                "distance_m": distance,
                "calories": _num(_nested_first(item, "calories", "active_calories", "activeCalories", "total_calories", "totalCalories")),
                "avg_hr": _int(_nested_first(item, "avg_hr", "average_hr", "averageHeartRate", "avgHeartRate", "heart_rate_avg")),
                "max_hr": _int(_nested_first(item, "max_hr", "maxHeartRate", "maximumHeartRate", "heart_rate_max")),
            }.items():
                if value is not None:
                    setattr(existing, field, value)
            return "updated", existing.id
        synthetic -= 1

    activity = Activity(
        user_id=user_id,
        garmin_activity_id=synthetic,
        name=name,
        sport_type=sport,
        started_at=started_at,
        duration_seconds=duration,
        moving_seconds=duration,
        distance_m=distance,
        calories=_num(_nested_first(item, "calories", "active_calories", "activeCalories", "total_calories", "totalCalories")),
        avg_hr=_int(_nested_first(item, "avg_hr", "average_hr", "averageHeartRate", "avgHeartRate", "heart_rate_avg")),
        max_hr=_int(_nested_first(item, "max_hr", "maxHeartRate", "maximumHeartRate", "heart_rate_max")),
        avg_power=_num(_nested_first(item, "avg_power", "averagePower", "avgPower")),
        avg_cadence=_num(_nested_first(item, "avg_cadence", "averageCadence", "avgCadence")),
        elevation_gain=_num(_nested_first(item, "elevation_gain", "elevationGain", "totalAscent")),
        training_load=_num(_nested_first(item, "training_load", "trainingLoad")),
        fit_status="unavailable",
        raw={
            "source": "sparkyfitness",
            "sparkyfitness_external_id": external_id,
            "sparkyfitness_provider": provider,
            "sparkyfitness": item,
        },
    )
    db.add(activity)
    await db.flush()
    return "created", activity.id


async def _upsert_source_record(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    domain: str,
    external_id: str,
    record_date: date | None,
    payload: dict[str, Any] | list,
) -> bool:
    row = await db.scalar(select(SourceRecord).where(
        SourceRecord.user_id == user_id,
        SourceRecord.source == "sparkyfitness",
        SourceRecord.domain == domain,
        SourceRecord.external_id == external_id,
    ).order_by(SourceRecord.fetched_at.desc()).limit(1))
    digest = _json_hash(payload)
    if row:
        changed = row.content_hash != digest
        row.record_date = record_date
        row.content_hash = digest
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
        return changed
    db.add(SourceRecord(
        user_id=user_id,
        source="sparkyfitness",
        domain=domain,
        external_id=external_id,
        record_date=record_date,
        content_hash=digest,
        schema_version=1,
        payload=payload,
    ))
    return True


def _source_tag(raw: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw or {})
    data["sparkyfitness"] = payload
    return data


def _metric_sources(raw: dict[str, Any] | None) -> dict[str, str]:
    values = (raw or {}).get("_metric_sources") if isinstance(raw, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def _tag_metric_source(raw: dict[str, Any] | None, field: str, source: str = "sparkyfitness") -> dict[str, Any]:
    data = dict(raw or {})
    sources = _metric_sources(data)
    sources[field] = source
    data["_metric_sources"] = sources
    return data


def _kg(value: Any) -> float | None:
    result = _num(value)
    if result is not None and result > 500:
        result /= 1000.0
    return result


def _height_cm(value: Any) -> float | None:
    result = _num(value)
    if result is None:
        return None
    if 0.5 < result < 3.0:
        result *= 100.0
    elif result > 1000:
        result /= 10.0
    return result if 50 <= result <= 260 else None


async def _merge_checkins(db: AsyncSession, user_id: uuid.UUID, rows: Iterable[dict[str, Any]]) -> int:
    changed = 0
    for item in rows:
        day = _as_date(_first(item, "entry_date", "entryDate", "date"))
        if not day:
            continue
        await _upsert_source_record(db, user_id, domain="checkin", external_id=str(_first(item, "id") or day), record_date=day, payload=item)
        health = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user_id, DailyHealth.date == day))
        if not health:
            health = DailyHealth(user_id=user_id, date=day, raw={})
            db.add(health)
        fill = {
            "steps": _int(_first(item, "steps", "step_count", "stepCount")),
            "resting_hr": _int(_first(item, "resting_hr", "restingHeartRate", "resting_heart_rate")),
            "active_calories": _num(_first(item, "active_calories", "activeCalories")),
            "distance_m": _num(_first(item, "distance_m", "distanceMeters")),
            "stress_avg": _num(_first(item, "stress_avg", "stressAverage", "average_stress")),
            "respiration_avg": _num(_first(item, "respiration_avg", "respirationAverage")),
            "spo2_avg": _num(_first(item, "spo2_avg", "spo2Average", "averageSpo2")),
        }
        prior_health_raw = dict(health.raw or {})
        prior_health_sources = _metric_sources(prior_health_raw)
        prior_health_non_meta = {key for key in prior_health_raw if not str(key).startswith("_") and key != "sparkyfitness"}
        health.raw = _source_tag(health.raw, item)
        for field, value in fill.items():
            if value is None:
                continue
            if getattr(health, field) is None:
                setattr(health, field, value)
                health.raw = _tag_metric_source(health.raw, field)
                changed += 1
            elif field not in prior_health_sources and not prior_health_non_meta:
                # Backfill provenance for values imported by alpha.24/25 before
                # per-metric source tracking existed.
                health.raw = _tag_metric_source(health.raw, field)

        body_values = {
            "weight_kg": _kg(_first(item, "weight", "weight_kg", "weightKg", "weightInGrams")),
            "height_cm": _height_cm(_first(item, "height", "height_cm", "heightCm", "heightInCentimeters", "heightInMeters")),
            "bmi": _num(_first(item, "bmi", "bodyMassIndex")),
            "body_fat_percent": _num(_first(item, "body_fat_percentage", "body_fat", "bodyFat", "bodyFatPercentage", "percentFat")),
            "body_water_percent": _num(_first(item, "body_water_percentage", "bodyWater", "bodyWaterPercentage", "percentHydration")),
            "muscle_mass_kg": _kg(_first(item, "muscle_mass", "muscleMass", "muscleMassKg", "muscleMassInGrams")),
            "bone_mass_kg": _kg(_first(item, "bone_mass", "boneMass", "boneMassKg", "boneMassInGrams")),
        }
        if any(value is not None for value in body_values.values()):
            measured_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
            body = await db.scalar(select(BodyMeasurement).where(
                BodyMeasurement.user_id == user_id, BodyMeasurement.measured_at == measured_at
            ))
            if not body:
                body = BodyMeasurement(user_id=user_id, measured_at=measured_at, raw={})
                db.add(body)
            prior_body_raw = dict(body.raw or {})
            prior_body_sources = _metric_sources(prior_body_raw)
            prior_body_non_meta = {key for key in prior_body_raw if not str(key).startswith("_") and key != "sparkyfitness"}
            body.raw = _source_tag(body.raw, item)
            for field, value in body_values.items():
                if value is None:
                    continue
                if getattr(body, field) is None:
                    setattr(body, field, value)
                    body.raw = _tag_metric_source(body.raw, field)
                    changed += 1
                elif field not in prior_body_sources and not prior_body_non_meta:
                    body.raw = _tag_metric_source(body.raw, field)
    return changed


async def _merge_profile(db: AsyncSession, user_id: uuid.UUID, payload: Any) -> int:
    rows = _list_payload(payload)
    if isinstance(payload, dict) and not rows:
        rows = [payload]
    changed = 0
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        await _upsert_source_record(
            db, user_id, domain="profile", external_id=str(_first(item, "id", "user_id", "userId") or index),
            record_date=date.today(), payload=item,
        )
        height = _height_cm(_first(item, "height", "height_cm", "heightCm", "heightInCentimeters", "heightInMeters"))
        if height is None:
            continue
        measured_at = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
        body = await db.scalar(select(BodyMeasurement).where(
            BodyMeasurement.user_id == user_id, BodyMeasurement.measured_at == measured_at
        ))
        if not body:
            body = BodyMeasurement(user_id=user_id, measured_at=measured_at, raw={})
            db.add(body)
        body.raw = _source_tag(body.raw, item)
        if body.height_cm is None:
            body.height_cm = height
            body.raw = _tag_metric_source(body.raw, "height_cm")
            changed += 1
    return changed


def _stage_seconds(item: dict[str, Any]) -> dict[str, int | None]:
    result: dict[str, int] = {"deep": 0, "light": 0, "rem": 0, "awake": 0}
    seen = False
    events = item.get("stage_events") or item.get("stageEvents") or item.get("sleep_stages") or item.get("sleepStages") or []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            stage = str(_first(event, "stage", "type", "sleep_stage", "name") or "").lower()
            duration = _int(_first(event, "duration_in_seconds", "duration_seconds", "duration"))
            if duration is None:
                start, end = _as_dt(event.get("start")), _as_dt(event.get("end"))
                duration = int((end - start).total_seconds()) if start and end and end >= start else None
            if duration is None:
                continue
            for key in result:
                if key in stage:
                    result[key] += max(0, duration)
                    seen = True
                    break
    return {key: value if seen else None for key, value in result.items()}


async def _merge_sleep(db: AsyncSession, user_id: uuid.UUID, rows: Iterable[dict[str, Any]]) -> int:
    changed = 0
    for item in rows:
        day = _as_date(_first(item, "entry_date", "entryDate", "date", "wake_date", "wakeDate"))
        start_at = _as_dt(_first(item, "bedtime", "bed_time", "start_at", "start_time", "startTime", "sleepStart", "sleep_start"))
        end_at = _as_dt(_first(item, "wake_time", "wakeTime", "end_at", "end_time", "endTime", "sleepEnd", "sleep_end"))
        if not day and end_at:
            day = end_at.date()
        if not day and start_at:
            day = start_at.date()
        if not day:
            continue
        await _upsert_source_record(db, user_id, domain="sleep", external_id=str(_first(item, "id") or day), record_date=day, payload=item)
        row = await db.scalar(select(SleepSession).where(SleepSession.user_id == user_id, SleepSession.date == day))
        if not row:
            row = SleepSession(user_id=user_id, date=day, raw={})
            db.add(row)
        duration = _int(_first(item, "duration_in_seconds", "duration_seconds", "durationSeconds", "sleep_duration_seconds", "sleepDurationSeconds"))
        if duration is None:
            minutes = _num(_first(item, "duration_minutes", "durationMinutes", "sleep_duration_minutes", "sleepDurationMinutes"))
            if minutes is not None:
                duration = int(round(minutes * 60))
        if duration is None and start_at and end_at and end_at >= start_at:
            duration = int((end_at - start_at).total_seconds())
        values = {
            "start_at": start_at,
            "end_at": end_at,
            "duration_seconds": duration,
            "sleep_score": _num(_first(item, "sleep_score", "sleepScore", "score")),
            "avg_spo2": _num(_first(item, "avg_spo2", "averageSpo2", "avgSpo2")),
            "min_spo2": _num(_first(item, "min_spo2", "minimumSpo2", "minSpo2")),
            "avg_respiration": _num(_first(item, "avg_respiration", "averageRespiration", "avgRespiration")),
        }
        stage = _stage_seconds(item)
        values.update({f"{key}_seconds": value for key, value in stage.items()})
        row.raw = _source_tag(row.raw, item)
        for field, value in values.items():
            if value is not None and getattr(row, field) is None:
                setattr(row, field, value)
                row.raw = _tag_metric_source(row.raw, field)
                changed += 1
    return changed


async def _merge_custom_metrics(
    db: AsyncSession,
    client: SparkyFitnessClient,
    user_id: uuid.UUID,
    categories: list[dict[str, Any]],
    start: date,
    end: date,
) -> tuple[int, int]:
    hrv_count = 0
    rhr_count = 0
    for category in categories:
        category_id = category.get("id")
        if not category_id:
            continue
        label = " ".join(str(category.get(k) or "") for k in ("name", "display_name", "measurement_type")).lower()
        kind = "hrv" if ("hrv" in label or "heart rate variability" in label) else "rhr" if ("resting" in label and "heart" in label) else None
        if not kind:
            continue
        entries: list[dict[str, Any]] = []
        try:
            for chunk_start, chunk_end in _date_chunks(start, end):
                payload = await client.request(
                    f"/measurements/custom-measurements-range/{category_id}/{chunk_start.isoformat()}/{chunk_end.isoformat()}"
                )
                batch = _list_payload(payload)
                if isinstance(payload, list):
                    batch = [x for x in payload if isinstance(x, dict)]
                entries.extend(batch)
        except SparkyFitnessError:
            continue
        unique_entries: dict[str, dict[str, Any]] = {}
        for item in entries:
            unique_entries[str(_first(item, "id") or _json_hash(item))] = item
        for item in unique_entries.values():
            day = _as_date(_first(item, "entry_date", "date", "entry_timestamp"))
            value = _num(item.get("value"))
            if not day or value is None:
                continue
            await _upsert_source_record(
                db, user_id, domain=f"custom_{kind}", external_id=str(_first(item, "id") or f"{category_id}:{day}"), record_date=day, payload=item
            )
            if kind == "hrv":
                row = await db.scalar(select(HrvDaily).where(HrvDaily.user_id == user_id, HrvDaily.date == day))
                if not row:
                    row = HrvDaily(user_id=user_id, date=day, raw={})
                    db.add(row)
                row.raw = _source_tag(row.raw, item)
                if row.overnight_average is None:
                    row.overnight_average = value
                    row.raw = _tag_metric_source(row.raw, "overnight_average")
                    hrv_count += 1
            else:
                row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user_id, DailyHealth.date == day))
                if not row:
                    row = DailyHealth(user_id=user_id, date=day, raw={})
                    db.add(row)
                row.raw = _source_tag(row.raw, item)
                if row.resting_hr is None:
                    row.resting_hr = int(round(value))
                    row.raw = _tag_metric_source(row.raw, "resting_hr")
                    rhr_count += 1
    return hrv_count, rhr_count


async def _sync_activities(
    db: AsyncSession,
    client: SparkyFitnessClient,
    user_id: uuid.UUID,
    start: date | None,
    *,
    progress=None,
) -> dict[str, int]:
    page = 1
    pages = 0
    seen = 0
    changed = 0
    created = 0
    merged = 0
    updated = 0
    skipped = 0
    while page <= 5000:
        payload = await client.request("/v2/exercise-entries/history", params={"page": page, "pageSize": 100})
        items = _list_payload(payload)
        if not items:
            break
        pages += 1
        oldest: date | None = None
        reached_older = False
        for index, item in enumerate(items):
            day = _session_date(item)
            if day and (oldest is None or day < oldest):
                oldest = day
            if start is not None and day and day < start:
                reached_older = True
                continue
            seen += 1
            external_id = _session_id(item, index)
            if await _upsert_source_record(
                db, user_id, domain="exercise_session", external_id=external_id, record_date=day, payload=item
            ):
                changed += 1
            activity_key = str(_nested_first(
                item, "session_id", "sessionId", "workout_session_id", "workoutSessionId",
                "workout_id", "workoutId", "exercise_preset_entry_id", "exercisePresetEntryId",
            ) or external_id)
            outcome, activity_id = await _merge_activity(db, user_id, item, activity_key)
            if activity_id is not None:
                materialized = await db.get(Activity, activity_id)
                if materialized is not None:
                    raw = dict(materialized.raw or {})
                    ids = list(dict.fromkeys([*(raw.get("sparkyfitness_external_ids") or []), external_id, activity_key]))
                    raw["sparkyfitness_external_ids"] = ids[-50:]
                    materialized.raw = raw
            if outcome == "created":
                created += 1
            elif outcome == "merged":
                merged += 1
            elif outcome == "updated":
                updated += 1
            else:
                skipped += 1
        if progress:
            progress({
                "phase": "activities", "pages": pages, "sessions": seen, "page": page,
                "created": created, "merged": merged, "updated": updated, "skipped": skipped,
            })
        await db.flush()
        if start is not None and ((oldest and oldest < start) or reached_older):
            break
        if len(items) < 100:
            break
        total_pages = None
        if isinstance(payload, dict):
            pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else payload
            total_pages = _int(_first(pagination, "totalPages", "total_pages", "pages"))
        if total_pages is not None and page >= total_pages:
            break
        page += 1
    return {
        "pages": pages, "sessions": seen, "changed": changed,
        "activities_created": created, "activities_merged": merged,
        "activities_updated": updated, "activities_skipped": skipped,
    }


def _date_chunks(start: date, end: date, *, chunk_days: int = 366):
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=chunk_days - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


async def _read_range_chunks(
    client: SparkyFitnessClient,
    path_builder,
    start: date,
    end: date,
    *,
    params_builder=None,
    progress=None,
    phase: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    chunks = list(_date_chunks(start, end))
    for idx, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        path = path_builder(chunk_start, chunk_end)
        params = params_builder(chunk_start, chunk_end) if params_builder else None
        payload = await client.request(path, params=params)
        batch = _list_payload(payload)
        if isinstance(payload, list):
            batch = [x for x in payload if isinstance(x, dict)]
        rows.extend(batch)
        if progress:
            progress({
                "phase": phase, "chunk": idx, "chunks": len(chunks),
                "records": len(rows), "from": chunk_start.isoformat(), "to": chunk_end.isoformat(),
            })
    # Some endpoints can return the same entry on adjacent/overlapping provider
    # boundaries. Keep one payload per stable id/hash before merging.
    unique: dict[str, dict[str, Any]] = {}
    for item in rows:
        key = str(_first(item, "id") or _json_hash(item))
        unique[key] = item
    return list(unique.values())


async def sync_sparkyfitness(db: AsyncSession, user_id: uuid.UUID, *, progress=None) -> dict[str, Any]:
    conn = await db.scalar(select(SparkyFitnessConnection).where(SparkyFitnessConnection.user_id == user_id))
    if not conn or conn.status != "connected":
        raise ValueError("SPARKYFITNESS_NOT_CONNECTED")
    client = SparkyFitnessClient(conn.base_url, SecretBox().decrypt(conn.api_key_ciphertext), timeout_seconds=45)
    configured_days = int(conn.sync_days if conn.sync_days is not None else 30)
    all_data = configured_days <= 0
    end = date.today()
    start = date(1970, 1, 1) if all_data else end - timedelta(days=max(1, configured_days) - 1)
    capabilities = dict(conn.capabilities or {})
    summary: dict[str, Any] = {
        "days": None if all_data else configured_days,
        "all": all_data,
        "from": start.isoformat(),
        "to": end.isoformat(),
    }
    try:
        if capabilities.get("identity"):
            try:
                profile_payload = await client.request("/identity/profiles")
                summary["profile_fields_filled"] = await _merge_profile(db, user_id, profile_payload)
            except SparkyFitnessError:
                summary["profile_fields_filled"] = 0
        if conn.sync_daily_health and capabilities.get("checkins"):
            if progress:
                progress({"phase": "daily_health", "message": "SparkyFitness daily health"})
            rows = await _read_range_chunks(
                client,
                lambda a, b: f"/measurements/check-in-measurements-range/{a.isoformat()}/{b.isoformat()}",
                start, end, progress=progress, phase="daily_health",
            )
            summary["checkins"] = len(rows)
            summary["health_fields_filled"] = await _merge_checkins(db, user_id, rows)
            if capabilities.get("custom_metrics"):
                categories_payload = await client.request("/measurements/custom-categories")
                categories = _list_payload(categories_payload)
                if isinstance(categories_payload, list):
                    categories = [x for x in categories_payload if isinstance(x, dict)]
                hrv, rhr = await _merge_custom_metrics(db, client, user_id, categories, start, end)
                summary["hrv_days_filled"] = hrv
                summary["resting_hr_days_filled"] = rhr
        if conn.sync_sleep and capabilities.get("sleep"):
            if progress:
                progress({"phase": "sleep", "message": "SparkyFitness sleep"})
            try:
                rows = await _read_range_chunks(
                    client, lambda _a, _b: "/sleep/details", start, end,
                    params_builder=lambda a, b: {"startDate": a.isoformat(), "endDate": b.isoformat()},
                    progress=progress, phase="sleep",
                )
                summary["sleep_endpoint"] = "details"
                if not rows:
                    rows = await _read_range_chunks(
                        client, lambda _a, _b: "/sleep", start, end,
                        params_builder=lambda a, b: {"startDate": a.isoformat(), "endDate": b.isoformat()},
                        progress=progress, phase="sleep",
                    )
                    summary["sleep_endpoint"] = "basic_fallback"
            except SparkyFitnessError:
                rows = await _read_range_chunks(
                    client, lambda _a, _b: "/sleep", start, end,
                    params_builder=lambda a, b: {"startDate": a.isoformat(), "endDate": b.isoformat()},
                    progress=progress, phase="sleep",
                )
                summary["sleep_endpoint"] = "basic"
            summary["sleep_entries"] = len(rows)
            summary["sleep_fields_filled"] = await _merge_sleep(db, user_id, rows)
        if conn.sync_activities and capabilities.get("activities"):
            summary["activities"] = await _sync_activities(db, client, user_id, None if all_data else start, progress=progress)
        conn.last_successful_sync_at = datetime.now(timezone.utc)
        conn.last_sync_summary = summary
        conn.last_error_code = None
        await db.commit()
        return summary
    except Exception as exc:
        conn.last_error_code = exc.code if isinstance(exc, SparkyFitnessError) else type(exc).__name__
        conn.last_error_at = datetime.now(timezone.utc)
        await db.commit()
        raise

