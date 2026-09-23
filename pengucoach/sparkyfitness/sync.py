from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from sqlalchemy import delete, select
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


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except ValueError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def _mapping_first(mapping: dict[str, Any], *keys: str) -> Any:
    """Read a value from a Sparky row, including v3 workout telemetry/raw_data.

    SparkyFitness stores HealthKit/Health Connect workout payloads in a mixture
    of relational columns, ``telemetry`` and ``raw_data``.  The latter may be
    JSON or a JSON string depending on endpoint/version.
    """
    value = _first(mapping, *keys)
    if value is not None:
        return value
    for extra_name in ("telemetry", "raw_data", "rawData"):
        extra = _as_mapping(mapping.get(extra_name))
        if not extra:
            continue
        value = _first(extra, *keys)
        if value is not None:
            return value
        telemetry = _as_mapping(extra.get("telemetry"))
        if telemetry:
            value = _first(telemetry, *keys)
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
    # The actual recording timestamp is authoritative. Some HealthKit rows
    # carry an entry/import date from the day Sparky received them; that must
    # not move historical workouts onto the sync day.
    recorded = _as_dt(_nested_first(
        item, "started_at", "start_time", "startTime", "start_at", "startAt",
        "timestamp", "entry_timestamp", "entryTimestamp", "logged_at", "loggedAt",
        "measured_at", "measuredAt",
    ))
    if recorded:
        return recorded.date()
    explicit = _as_date(_nested_first(item, "entry_date", "entryDate", "date"))
    if explicit:
        return explicit
    return _as_date(_nested_first(item, "created_at", "createdAt"))


def _session_id(item: dict[str, Any], index: int) -> str:
    value = _first(item, "id", "session_id", "exercise_entry_id", "external_id")
    if value is not None:
        return str(value)
    return f"derived-{_json_hash(item)[:24]}-{index}"


def _nested_first(item: dict[str, Any], *keys: str) -> Any:
    # SparkyFitness' relational exercise-entry row is the authoritative source
    # for headline distance/duration/calories. Its own report UI prefers these
    # columns over compact history/provider blobs, so PenguCoach mirrors that
    # precedence when the detail row has been loaded.
    for container in ("exercise_entry_details", "exerciseEntryDetails"):
        nested = item.get(container)
        if isinstance(nested, dict):
            value = _mapping_first(nested, *keys)
            if value is not None:
                return value
            for inner_name in ("entry", "data"):
                inner = nested.get(inner_name)
                if isinstance(inner, dict):
                    value = _mapping_first(inner, *keys)
                    if value is not None:
                        return value
    value = _mapping_first(item, *keys)
    if value is not None:
        return value
    for container in (
        "provider_activity_details", "providerActivityDetails", "activity", "activity_details", "activityDetails",
        "garmin_activity_details", "garminActivityDetails", "workout", "session", "exercise", "entry", "data",
    ):
        nested = item.get(container)
        if isinstance(nested, dict):
            value = _mapping_first(nested, *keys)
            if value is not None:
                return value
            for inner_name in ("activity", "details", "entry", "data"):
                inner = nested.get(inner_name)
                if isinstance(inner, dict):
                    value = _mapping_first(inner, *keys)
                    if value is not None:
                        return value
    return None


def _duration_seconds(item: dict[str, Any]) -> int | None:
    detail = item.get("exercise_entry_details") or item.get("exerciseEntryDetails")
    if isinstance(detail, dict):
        detail_seconds = _num(_first(
            detail, "duration_seconds", "durationSeconds", "duration_in_seconds", "durationInSeconds",
            "elapsed_seconds", "elapsedSeconds", "elapsed_time_seconds", "elapsedTimeSeconds",
        ))
        if detail_seconds is not None:
            return max(0, int(round(detail_seconds)))
        detail_minutes = _num(_first(detail, "duration_minutes", "durationMinutes", "duration"))
        if detail_minutes is not None:
            return max(0, int(round(detail_minutes * 60)))
    seconds = _num(_nested_first(
        item, "duration_seconds", "durationSeconds", "duration_in_seconds", "durationInSeconds",
        "elapsed_seconds", "elapsedSeconds", "elapsed_time_seconds", "elapsedTimeSeconds",
        "total_timer_time", "totalTimerTime",
    ))
    if seconds is not None:
        return max(0, int(round(seconds)))
    minutes = _num(_nested_first(item, "duration_minutes", "durationMinutes", "minutes"))
    if minutes is not None:
        return max(0, int(round(minutes * 60)))
    duration_obj = _nested_first(item, "duration")
    if isinstance(duration_obj, dict):
        quantity = _num(_first(duration_obj, "quantity", "value"))
        unit = str(_first(duration_obj, "unit", "unitString") or "s").strip().lower()
        if quantity is not None:
            if unit in {"ms", "millisecond", "milliseconds"}:
                quantity /= 1000.0
            elif unit in {"min", "minute", "minutes", "m"}:
                quantity *= 60.0
            elif unit in {"h", "hr", "hour", "hours"}:
                quantity *= 3600.0
            return max(0, int(round(quantity)))
    # SparkyFitness' relational exercise_entries API stores the headline duration
    # in minutes. Keep this behind the explicit minute fields so provider blobs
    # that expose seconds under another canonical key still win.
    relational_minutes = _num(_nested_first(item, "duration"))
    if relational_minutes is not None and (
        _nested_first(item, "exercise_name", "exerciseName", "calories_burned", "caloriesBurned") is not None
        or "exercise_entry_details" in item
    ):
        return max(0, int(round(relational_minutes * 60)))
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
    # SparkyFitness exercise_entries.distance is stored in kilometres and is
    # exactly what the Sparky UI uses for the headline activity distance.
    if _nested_first(item, "exercise_name", "exerciseName", "duration_minutes", "durationMinutes", "calories_burned", "caloriesBurned") is not None or "exercise_entry_details" in item:
        return max(0.0, raw * 1000.0)
    return max(0.0, raw)


def _avg_speed_mps(item: dict[str, Any]) -> float | None:
    explicit = _num(_nested_first(item, "avg_speed_mps", "avgSpeedMps", "averageSpeed", "avg_speed"))
    if explicit is not None and explicit > 0:
        return explicit
    distance = _distance_m(item)
    duration = _duration_seconds(item)
    if distance is not None and duration and duration > 0:
        return distance / duration
    return None


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
    # Recording timestamps first.  A relational detail row may have a fresh
    # ``created_at`` from the Sparky import; treating that as workout time is
    # what caused historical HealthKit sessions to appear on the import day.
    recorded = _as_dt(_nested_first(
        item, "started_at", "start_time", "startTime", "start_at", "startAt",
        "timestamp", "entry_timestamp", "entryTimestamp", "logged_at", "loggedAt",
        "measured_at", "measuredAt",
    ))
    if recorded:
        return recorded
    recorded_day = _as_dt(_nested_first(item, "entry_date", "entryDate", "date"))
    if recorded_day:
        return recorded_day
    return _as_dt(_nested_first(item, "created_at", "createdAt"))


def _session_name(item: dict[str, Any]) -> str:
    value = _nested_first(item, "name", "activity_name", "activityName", "workout_name", "workoutName", "exercise_name", "exerciseName", "title")
    return str(value).strip()[:255] if value else "SparkyFitness activity"


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _is_daily_metric_entry(item: dict[str, Any]) -> bool:
    """Exclude Apple/HealthKit day metrics that Sparky exposes as exercise rows."""
    labels = {
        _normalized_label(_nested_first(item, "name", "exercise_name", "exerciseName", "activity_name", "activityName", "title")),
        _normalized_label(_nested_first(item, "activity_type", "activityType", "type", "category")),
    }
    return bool(labels & {
        "active calories", "active calorie", "active energy", "active energy burned",
        "move calories", "move energy",
    })


def _provider(item: dict[str, Any]) -> str | None:
    value = _nested_first(item, "provider", "provider_name", "providerName", "source", "source_name", "sourceName", "origin")
    return str(value).strip()[:128] if value else None


def _activity_entry_id(item: dict[str, Any]) -> str | None:
    value = _first(item, "id", "exercise_entry_id", "exerciseEntryId", "entry_id", "entryId")
    return str(value) if value not in (None, "") else None


def _activity_candidate(item: dict[str, Any]) -> bool:
    if _is_daily_metric_entry(item):
        return False
    session_marker = _nested_first(
        item, "activity_id", "activityId", "workout_id", "workoutId",
        "session_id", "sessionId", "workout_session_id", "workoutSessionId",
        "exercise_preset_entry_id", "exercisePresetEntryId",
    )
    session_name = _nested_first(item, "activity_name", "activityName", "workout_name", "workoutName")
    has_activity_container = any(isinstance(item.get(k), dict) for k in (
        "activity", "activity_details", "activityDetails", "garmin_activity_details", "garminActivityDetails",
        "workout", "session", "exercise_entry_details", "exerciseEntryDetails",
    ))
    return not (
        _duration_seconds(item) is None and _distance_m(item) is None
        and session_marker is None and session_name is None and not has_activity_container
    )


def _activity_detail_missing(item: dict[str, Any]) -> bool:
    values = (
        _distance_m(item),
        _duration_seconds(item),
        _num(_nested_first(item, "calories_burned", "caloriesBurned", "calories", "active_calories", "activeCalories", "totalEnergyBurned")),
        _num(_nested_first(item, "avg_heart_rate", "avgHeartRate", "averageHeartRate", "average_hr", "avg_hr")),
        _num(_nested_first(item, "elevation_gain_meters", "elevationGainMeters", "elevation_gain", "elevationGain", "totalAscent")),
    )
    # History rows are intentionally compact. Enrich when at least one useful
    # headline metric is absent; the relational entry endpoint is lightweight
    # and is the same source SparkyFitness itself prefers in its report UI.
    return any(value is None for value in values)


def _activity_core_missing(item: dict[str, Any]) -> bool:
    return any(value is None for value in (
        _distance_m(item),
        _duration_seconds(item),
        _num(_nested_first(item, "calories_burned", "caloriesBurned", "calories", "active_calories", "activeCalories", "totalEnergyBurned")),
    ))


def _unwrap_detail_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("entry", "exerciseEntry", "exercise_entry", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict) and any(k in nested for k in (
            "duration_minutes", "distance", "calories_burned", "exercise_name", "source", "provider_name"
        )):
            return nested
    return payload


async def _enrich_activity_item(client: SparkyFitnessClient, item: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if not _activity_candidate(item) or not _activity_detail_missing(item):
        return item, 0
    entry_id = _activity_entry_id(item)
    if not entry_id:
        return item, 0
    enriched = dict(item)
    requests = 0
    try:
        payload = await client.request(f"/exercise-entries/{quote(entry_id, safe='')}")
        requests += 1
        detail = _unwrap_detail_payload(payload)
        if detail:
            enriched["exercise_entry_details"] = detail
    except SparkyFitnessError as exc:
        # Detail enrichment is best-effort; a history row is still useful even
        # if an older SparkyFitness version/API key cannot read its detail.
        if exc.status_code not in {400, 404}:
            raise

    # Provider details can carry HR/elevation/cadence not present in the
    # relational row.  Quality is more important here than saving one request:
    # fetch them whenever *any* useful activity detail is still missing.
    provider = _provider(enriched)
    if provider and _activity_detail_missing(enriched):
        try:
            payload = await client.request(
                f"/exercises/activity-details/{quote(entry_id, safe='')}/{quote(provider, safe='')}"
            )
            requests += 1
            if isinstance(payload, dict):
                enriched["provider_activity_details"] = payload
        except SparkyFitnessError as exc:
            if exc.status_code not in {400, 404}:
                raise
    return enriched, requests


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
    if not _activity_candidate(item):
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
                "calories": _num(_nested_first(item, "calories_burned", "caloriesBurned", "calories", "active_calories", "activeCalories", "total_calories", "totalCalories", "totalEnergyBurned")),
                "avg_hr": _int(_nested_first(item, "avg_heart_rate", "avgHeartRate", "avg_hr", "average_hr", "averageHeartRate", "heart_rate_avg")),
                "max_hr": _int(_nested_first(item, "max_heart_rate", "maxHeartRate", "max_hr", "maximumHeartRate", "heart_rate_max")),
                "avg_speed": _avg_speed_mps(item),
                "avg_cadence": _num(_nested_first(item, "avg_cadence", "avgCadence", "averageCadence")),
                "avg_power": _num(_nested_first(item, "avg_power_watts", "avgPowerWatts", "avg_power", "averagePower", "avgPower")),
                "elevation_gain": _num(_nested_first(item, "elevation_gain_meters", "elevationGainMeters", "elevation_gain", "elevationGain", "totalAscent")),
                "training_load": _num(_nested_first(item, "training_load", "trainingLoad")),
                "aerobic_training_effect": _num(_nested_first(item, "aerobic_effect", "aerobicEffect", "aerobic_training_effect", "aerobicTrainingEffect")),
                "anaerobic_training_effect": _num(_nested_first(item, "anaerobic_effect", "anaerobicEffect", "anaerobic_training_effect", "anaerobicTrainingEffect")),
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
        calories=_num(_nested_first(item, "calories_burned", "caloriesBurned", "calories", "active_calories", "activeCalories", "total_calories", "totalCalories", "totalEnergyBurned")),
        avg_hr=_int(_nested_first(item, "avg_heart_rate", "avgHeartRate", "avg_hr", "average_hr", "averageHeartRate", "heart_rate_avg")),
        max_hr=_int(_nested_first(item, "max_heart_rate", "maxHeartRate", "max_hr", "maximumHeartRate", "heart_rate_max")),
        avg_speed=_avg_speed_mps(item),
        avg_power=_num(_nested_first(item, "avg_power_watts", "avgPowerWatts", "avg_power", "averagePower", "avgPower")),
        avg_cadence=_num(_nested_first(item, "avg_cadence", "avgCadence", "averageCadence")),
        elevation_gain=_num(_nested_first(item, "elevation_gain_meters", "elevationGainMeters", "elevation_gain", "elevationGain", "totalAscent")),
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
    observed_at: datetime | None = None,
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
        row.observed_at = observed_at
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
        observed_at=observed_at,
        content_hash=digest,
        schema_version=1,
        payload=payload,
    ))
    return True


def _measurement_observed_at(item: dict[str, Any]) -> datetime | None:
    recorded = _as_dt(_nested_first(
        item, "entry_timestamp", "entryTimestamp", "timestamp", "measured_at", "measuredAt",
        "logged_at", "loggedAt", "start_time", "startTime", "started_at",
    ))
    if recorded:
        return recorded
    day = _as_dt(_nested_first(item, "entry_date", "entryDate", "date"))
    if day:
        return day
    return _as_dt(_nested_first(item, "created_at", "createdAt"))


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


async def _remove_legacy_daily_metric_activities(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Repair activity rows created before daily HealthKit metrics were filtered."""
    activities_removed = 0
    for row in (await db.scalars(select(Activity).where(
        Activity.user_id == user_id, Activity.garmin_activity_id < 0
    ))).all():
        raw = row.raw or {}
        payload = raw.get("sparkyfitness") if isinstance(raw, dict) else None
        if isinstance(payload, dict) and _is_daily_metric_entry(payload):
            await db.delete(row)
            activities_removed += 1

    source_records_removed = 0
    for row in (await db.scalars(select(SourceRecord).where(
        SourceRecord.user_id == user_id,
        SourceRecord.source == "sparkyfitness",
        SourceRecord.domain == "exercise_session",
    ))).all():
        payload = row.payload if isinstance(row.payload, dict) else None
        if payload and _is_daily_metric_entry(payload):
            await db.delete(row)
            source_records_removed += 1
    return {
        "activities_removed": activities_removed,
        "source_records_removed": source_records_removed,
    }


def _row_has_only_sparky_raw(raw: dict[str, Any]) -> bool:
    meaningful = {
        key for key in raw
        if key not in {"sparkyfitness", "_metric_sources"} and not str(key).startswith("_")
    }
    return not meaningful and "sparkyfitness" in raw


async def _remove_sparky_from_metric_rows(
    db: AsyncSession,
    user_id: uuid.UUID,
    model,
    fields: tuple[str, ...],
) -> tuple[int, int]:
    """Remove only values known to originate in SparkyFitness.

    Mixed Garmin/manual rows are retained.  Legacy Sparky-only rows from before
    per-field provenance tracking are recognised by their raw payload shape.
    """
    rows_touched = 0
    rows_deleted = 0
    for row in (await db.scalars(select(model).where(model.user_id == user_id))).all():
        raw = dict(row.raw or {})
        sources = _metric_sources(raw)
        sparky_fields = {field for field, source in sources.items() if source == "sparkyfitness" and field in fields}
        legacy_sparky_only = _row_has_only_sparky_raw(raw) and not sources
        if not sparky_fields and not legacy_sparky_only and "sparkyfitness" not in raw:
            continue
        rows_touched += 1
        if legacy_sparky_only:
            sparky_fields = set(fields)
        for field in sparky_fields:
            if hasattr(row, field):
                setattr(row, field, None)

        raw.pop("sparkyfitness", None)
        remaining_sources = {field: source for field, source in sources.items() if source != "sparkyfitness"}
        if remaining_sources:
            raw["_metric_sources"] = remaining_sources
        else:
            raw.pop("_metric_sources", None)
        row.raw = raw

        if all(getattr(row, field, None) is None for field in fields) and not {
            key for key in raw if not str(key).startswith("_")
        }:
            await db.delete(row)
            rows_deleted += 1
    return rows_touched, rows_deleted


async def delete_local_sparkyfitness_data(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Delete PenguCoach's local SparkyFitness imports without touching SparkyFitness."""
    counts: dict[str, int] = {
        "source_records": 0,
        "activities_deleted": 0,
        "activities_detached": 0,
        "health_rows_touched": 0,
        "health_rows_deleted": 0,
        "sleep_rows_touched": 0,
        "sleep_rows_deleted": 0,
        "hrv_rows_touched": 0,
        "hrv_rows_deleted": 0,
        "body_rows_touched": 0,
        "body_rows_deleted": 0,
    }

    source_ids = (await db.scalars(select(SourceRecord.id).where(
        SourceRecord.user_id == user_id, SourceRecord.source == "sparkyfitness"
    ))).all()
    counts["source_records"] = len(source_ids)
    await db.execute(delete(SourceRecord).where(
        SourceRecord.user_id == user_id, SourceRecord.source == "sparkyfitness"
    ))

    for activity in (await db.scalars(select(Activity).where(Activity.user_id == user_id))).all():
        raw = dict(activity.raw or {})
        has_sparky = any(key in raw for key in (
            "sparkyfitness", "sparkyfitness_external_id", "sparkyfitness_external_ids", "sparkyfitness_provider"
        ))
        if not has_sparky:
            continue
        if activity.garmin_activity_id < 0 or raw.get("source") == "sparkyfitness":
            await db.delete(activity)
            counts["activities_deleted"] += 1
            continue
        for key in ("sparkyfitness", "sparkyfitness_external_id", "sparkyfitness_external_ids", "sparkyfitness_provider"):
            raw.pop(key, None)
        activity.raw = raw
        counts["activities_detached"] += 1

    metric_specs = (
        ("health", DailyHealth, (
            "steps", "distance_m", "active_calories", "resting_calories", "resting_hr", "min_hr", "max_hr",
            "stress_avg", "body_battery_high", "body_battery_low", "hydration_ml", "hydration_goal_ml",
            "intensity_moderate", "intensity_vigorous", "respiration_avg", "spo2_avg", "training_readiness",
            "vo2max_running",
        )),
        ("sleep", SleepSession, (
            "start_at", "end_at", "duration_seconds", "sleep_score", "deep_seconds", "light_seconds", "rem_seconds",
            "awake_seconds", "avg_respiration", "avg_spo2", "min_spo2",
        )),
        ("hrv", HrvDaily, (
            "overnight_average", "highest_5min", "garmin_baseline_low", "garmin_baseline_high", "garmin_status",
        )),
        ("body", BodyMeasurement, (
            "weight_kg", "height_cm", "bmi", "body_fat_percent", "body_water_percent", "muscle_mass_kg", "bone_mass_kg",
        )),
    )
    for prefix, model, fields in metric_specs:
        touched, removed = await _remove_sparky_from_metric_rows(db, user_id, model, fields)
        counts[f"{prefix}_rows_touched"] = touched
        counts[f"{prefix}_rows_deleted"] = removed

    connection = await db.scalar(select(SparkyFitnessConnection).where(SparkyFitnessConnection.user_id == user_id))
    if connection:
        connection.last_sync_summary = {}
        connection.last_successful_sync_at = None
        connection.last_error_code = None
    await db.commit()
    return counts


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
        observed_at = _measurement_observed_at(item)
        day = (observed_at.date() if observed_at else None) or _as_date(_first(item, "entry_date", "entryDate", "date"))
        if not day:
            continue
        await _upsert_source_record(
            db, user_id, domain="checkin", external_id=str(_first(item, "id") or day),
            record_date=day, observed_at=observed_at, payload=item,
        )
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
            measured_at = observed_at or datetime.combine(day, time.min, tzinfo=timezone.utc)
            body = await db.scalar(select(BodyMeasurement).where(
                BodyMeasurement.user_id == user_id, BodyMeasurement.measured_at == measured_at
            ))
            # Alpha.24-31 stored Sparky body values at midnight.  When an exact
            # measurement timestamp becomes available, reuse that legacy row
            # instead of creating a duplicate and repair its timestamp.
            if not body and observed_at and measured_at.time() != time.min:
                day_start = datetime.combine(day, time.min, tzinfo=observed_at.tzinfo or timezone.utc)
                day_end = day_start + timedelta(days=1)
                candidates = (await db.scalars(select(BodyMeasurement).where(
                    BodyMeasurement.user_id == user_id,
                    BodyMeasurement.measured_at >= day_start,
                    BodyMeasurement.measured_at < day_end,
                ))).all()
                item_id = str(_first(item, "id") or "")
                for candidate in candidates:
                    source_payload = (candidate.raw or {}).get("sparkyfitness") if isinstance(candidate.raw, dict) else None
                    source_id = str(_first(source_payload, "id") or "") if isinstance(source_payload, dict) else ""
                    if item_id and source_id == item_id:
                        body = candidate
                        body.measured_at = measured_at
                        break
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
        await _upsert_source_record(
            db, user_id, domain="sleep", external_id=str(_first(item, "id") or day),
            record_date=day, observed_at=start_at or end_at, payload=item,
        )
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
            observed_at = _measurement_observed_at(item)
            day = (observed_at.date() if observed_at else None) or _as_date(_first(item, "entry_date", "date"))
            value = _num(item.get("value"))
            if not day or value is None:
                continue
            await _upsert_source_record(
                db, user_id, domain=f"custom_{kind}", external_id=str(_first(item, "id") or f"{category_id}:{day}"),
                record_date=day, observed_at=observed_at, payload=item,
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


async def _merge_active_calories_metric(
    db: AsyncSession, user_id: uuid.UUID, item: dict[str, Any], day: date | None
) -> bool:
    """Keep HealthKit Move-ring energy as daily health, never as a workout."""
    if day is None:
        return False
    value = _num(_nested_first(
        item, "active_calories", "activeCalories", "calories_burned", "caloriesBurned",
        "calories", "value", "totalEnergyBurned",
    ))
    if value is None:
        return False
    row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user_id, DailyHealth.date == day))
    if not row:
        row = DailyHealth(user_id=user_id, date=day, raw={})
        db.add(row)
    prior_sources = _metric_sources(row.raw)
    row.raw = _source_tag(row.raw, item)
    if row.active_calories is None:
        row.active_calories = value
        row.raw = _tag_metric_source(row.raw, "active_calories")
        return True
    if prior_sources.get("active_calories") == "sparkyfitness":
        changed = float(row.active_calories) != float(value)
        row.active_calories = value
        row.raw = _tag_metric_source(row.raw, "active_calories")
        return changed
    return False


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
    daily_metrics_filtered = 0
    daily_metrics_materialized = 0
    detail_requests = 0
    enriched_sessions = 0
    legacy_cleanup = await _remove_legacy_daily_metric_activities(db, user_id)
    while page <= 5000:
        payload = await client.request("/v2/exercise-entries/history", params={"page": page, "pageSize": 100})
        items = _list_payload(payload)
        if not items:
            break
        pages += 1
        oldest: date | None = None
        reached_older = False
        for index, item in enumerate(items):
            if _is_daily_metric_entry(item):
                day = _session_date(item)
                if day and (oldest is None or day < oldest):
                    oldest = day
                if start is not None and day and day < start:
                    reached_older = True
                    continue
                external_id = _session_id(item, index)
                if await _upsert_source_record(
                    db, user_id, domain="daily_metric_active_calories", external_id=external_id,
                    record_date=day, observed_at=_measurement_observed_at(item), payload=item,
                ):
                    changed += 1
                if await _merge_active_calories_metric(db, user_id, item, day):
                    daily_metrics_materialized += 1
                daily_metrics_filtered += 1
                continue
            original_item = item
            item, detail_count = await _enrich_activity_item(client, item)
            detail_requests += detail_count
            if item is not original_item:
                enriched_sessions += 1
            day = _session_date(item)
            if day and (oldest is None or day < oldest):
                oldest = day
            if start is not None and day and day < start:
                reached_older = True
                continue
            seen += 1
            external_id = _session_id(item, index)
            if await _upsert_source_record(
                db, user_id, domain="exercise_session", external_id=external_id, record_date=day,
                observed_at=_session_started_at(item), payload=item,
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
                "enriched": enriched_sessions, "detail_requests": detail_requests,
                "daily_metrics_filtered": daily_metrics_filtered,
                "daily_metrics_materialized": daily_metrics_materialized,
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
        "activities_enriched": enriched_sessions, "detail_requests": detail_requests,
        "daily_metrics_filtered": daily_metrics_filtered,
        "daily_metrics_materialized": daily_metrics_materialized,
        "legacy_daily_metric_activities_removed": legacy_cleanup["activities_removed"],
        "legacy_daily_metric_source_records_removed": legacy_cleanup["source_records_removed"],
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

