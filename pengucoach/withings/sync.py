from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import BodyMeasurement, DailyHealth, SleepSession, SourceRecord, WithingsConnection
from pengucoach.security.crypto import SecretBox
from pengucoach.withings.client import WithingsApiClient, WithingsError, WithingsOAuthClient


BODY_FIELDS = (
    "weight_kg", "height_cm", "bmi", "body_fat_percent",
    "body_water_percent", "muscle_mass_kg", "bone_mass_kg",
)
DAILY_FIELDS = (
    "steps", "distance_m", "active_calories", "resting_calories", "resting_hr", "min_hr", "max_hr",
    "stress_avg", "body_battery_high", "body_battery_low", "hydration_ml", "hydration_goal_ml",
    "intensity_moderate", "intensity_vigorous", "respiration_avg", "spo2_avg", "training_readiness",
    "vo2max_running",
)
SLEEP_FIELDS = (
    "start_at", "end_at", "duration_seconds", "sleep_score", "deep_seconds", "light_seconds", "rem_seconds",
    "awake_seconds", "avg_respiration", "avg_spo2", "min_spo2",
)

# Withings measure type IDs used by the Public Health Data API.
TYPE_WEIGHT = 1
TYPE_HEIGHT = 4
TYPE_FAT_FREE_MASS = 5
TYPE_FAT_RATIO = 6
TYPE_FAT_MASS = 8
TYPE_DIASTOLIC_BP = 9
TYPE_SYSTOLIC_BP = 10
TYPE_PULSE = 11
TYPE_SPO2 = 54
TYPE_MUSCLE_MASS = 76
TYPE_HYDRATION_MASS = 77
TYPE_BONE_MASS = 88
TYPE_PWV = 91
TYPE_VASCULAR_AGE = 155
TYPE_VISCERAL_FAT = 170
TYPE_BMR = 226


def _json_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _metric_sources(raw: dict[str, Any] | None) -> dict[str, str]:
    values = (raw or {}).get("_metric_sources") if isinstance(raw, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def _tag_metric_source(raw: dict[str, Any] | None, field: str, source: str = "withings") -> dict[str, Any]:
    data = dict(raw or {})
    sources = _metric_sources(data)
    sources[field] = source
    data["_metric_sources"] = sources
    return data


def _source_tag(raw: dict[str, Any] | None, key: str, payload: Any) -> dict[str, Any]:
    data = dict(raw or {})
    data[key] = payload
    return data


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    value_f = _num(value)
    return None if value_f is None else int(round(value_f))


def _epoch_dt(value: Any) -> datetime | None:
    number = _num(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        dt = _epoch_dt(value)
        return dt.date() if dt else None
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def measurement_value(measure: dict[str, Any]) -> float | None:
    """Decode Withings' integer value × 10^unit representation."""
    value = _num(measure.get("value"))
    unit = _int(measure.get("unit"))
    if value is None or unit is None:
        return None
    return value * (10 ** unit)


def _chunks(start: date, end: date, days: int) -> Iterable[tuple[date, date]]:
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=days - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


async def _upsert_source_record(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    domain: str,
    external_id: str,
    record_date: date | None,
    observed_at: datetime | None,
    payload: Any,
) -> bool:
    row = await db.scalar(select(SourceRecord).where(
        SourceRecord.user_id == user_id,
        SourceRecord.source == "withings",
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
        source="withings",
        domain=domain,
        external_id=external_id,
        record_date=record_date,
        observed_at=observed_at,
        content_hash=digest,
        schema_version=1,
        payload=payload,
    ))
    return True


async def _ensure_access_token(db: AsyncSession, conn: WithingsConnection) -> str:
    secret_box = SecretBox()
    access = secret_box.decrypt(conn.access_token_ciphertext) if conn.access_token_ciphertext else ""
    now = datetime.now(timezone.utc)
    if access and conn.token_expires_at and conn.token_expires_at > now + timedelta(minutes=5):
        return access
    if not conn.refresh_token_ciphertext:
        raise WithingsError("WITHINGS_REAUTH_REQUIRED")
    oauth = WithingsOAuthClient(
        conn.client_id,
        secret_box.decrypt(conn.client_secret_ciphertext),
        conn.redirect_uri,
    )
    tokens = await oauth.refresh(secret_box.decrypt(conn.refresh_token_ciphertext))
    conn.withings_user_id = tokens.userid
    conn.access_token_ciphertext = secret_box.encrypt(tokens.access_token)
    # Withings rotates refresh tokens. Always persist the newly returned one.
    conn.refresh_token_ciphertext = secret_box.encrypt(tokens.refresh_token)
    conn.token_expires_at = now + timedelta(seconds=tokens.expires_in)
    conn.scope = tokens.scope
    conn.status = "connected"
    conn.last_error_code = None
    await db.flush()
    return tokens.access_token


async def _fetch_measure_groups(
    client: WithingsApiClient,
    start: date,
    end: date,
    *,
    lastupdate: int | None = None,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    offset: int | None = None
    for _ in range(1000):
        data: dict[str, Any] = {"category": 1}
        if lastupdate is not None:
            data["lastupdate"] = int(lastupdate)
        else:
            data["startdate"] = int(datetime.combine(start, time.min, tzinfo=timezone.utc).timestamp())
            data["enddate"] = int(datetime.combine(end, time.max, tzinfo=timezone.utc).timestamp())
        if offset is not None:
            data["offset"] = offset
        body = await client.request("measure", action="getmeas", data=data)
        batch = body.get("measuregrps") or []
        groups.extend(item for item in batch if isinstance(item, dict))
        if not body.get("more"):
            break
        next_offset = body.get("offset")
        if next_offset is None or next_offset == offset:
            break
        offset = int(next_offset)
    return groups


async def _merge_measure_groups(db: AsyncSession, user_id: uuid.UUID, groups: Iterable[dict[str, Any]]) -> dict[str, int]:
    stats = {"measurements": 0, "body_rows": 0, "blood_pressure_records": 0, "other_records": 0}
    for group in groups:
        observed_at = _epoch_dt(group.get("date"))
        day = observed_at.date() if observed_at else None
        external_id = str(group.get("grpid") or group.get("id") or _json_hash(group)[:24])
        await _upsert_source_record(
            db, user_id, domain="measurement", external_id=external_id,
            record_date=day, observed_at=observed_at, payload=group,
        )
        stats["measurements"] += 1
        values: dict[int, float] = {}
        for measure in group.get("measures") or []:
            if not isinstance(measure, dict):
                continue
            type_id = _int(measure.get("type"))
            decoded = measurement_value(measure)
            if type_id is not None and decoded is not None:
                values[type_id] = decoded

        if TYPE_SYSTOLIC_BP in values or TYPE_DIASTOLIC_BP in values:
            stats["blood_pressure_records"] += 1

        body_values: dict[str, float | None] = {
            "weight_kg": values.get(TYPE_WEIGHT),
            "body_fat_percent": values.get(TYPE_FAT_RATIO),
            "muscle_mass_kg": values.get(TYPE_MUSCLE_MASS),
            "bone_mass_kg": values.get(TYPE_BONE_MASS),
            "body_water_percent": None,
            "height_cm": (values.get(TYPE_HEIGHT) * 100.0) if values.get(TYPE_HEIGHT) is not None else None,
            "bmi": None,
        }
        water_kg = values.get(TYPE_HYDRATION_MASS)
        weight_kg = values.get(TYPE_WEIGHT)
        if water_kg is not None and weight_kg and weight_kg > 0:
            body_values["body_water_percent"] = round(100.0 * water_kg / weight_kg, 2)

        if not any(value is not None for value in body_values.values()):
            stats["other_records"] += 1
            continue
        measured_at = observed_at or datetime.combine(day or date.today(), time.min, tzinfo=timezone.utc)
        row = await db.scalar(select(BodyMeasurement).where(
            BodyMeasurement.user_id == user_id, BodyMeasurement.measured_at == measured_at
        ))
        if not row:
            row = BodyMeasurement(user_id=user_id, measured_at=measured_at, raw={})
            db.add(row)
        row.raw = _source_tag(row.raw, "withings", group)
        row.raw = _source_tag(row.raw, "withings_measurements", {str(k): v for k, v in values.items()})
        for field, value in body_values.items():
            if value is None:
                continue
            setattr(row, field, value)
            row.raw = _tag_metric_source(row.raw, field)
        if row.weight_kg is not None and row.bmi is None:
            # Reuse the latest known height from any source. Height is profile-like
            # and is not normally included in a Withings scale measurement group.
            height_row = await db.scalar(select(BodyMeasurement).where(
                BodyMeasurement.user_id == user_id,
                BodyMeasurement.measured_at <= measured_at,
                BodyMeasurement.height_cm.is_not(None),
            ).order_by(BodyMeasurement.measured_at.desc()).limit(1))
            if height_row and height_row.height_cm:
                row.bmi = round(float(row.weight_kg) / ((float(height_row.height_cm) / 100.0) ** 2), 2)
                row.raw = _tag_metric_source(row.raw, "bmi")
        stats["body_rows"] += 1
    return stats


async def _fetch_activity(client: WithingsApiClient, start: date, end: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fields = "steps,distance,calories,totalcalories,elevation,soft,moderate,intense,active"
    for chunk_start, chunk_end in _chunks(start, end, 30):
        body = await client.request("v2/measure", action="getactivity", data={
            "startdateymd": chunk_start.isoformat(),
            "enddateymd": chunk_end.isoformat(),
            "data_fields": fields,
        })
        rows.extend(item for item in (body.get("activities") or []) if isinstance(item, dict))
    return rows


async def _merge_activity(db: AsyncSession, user_id: uuid.UUID, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for item in rows:
        day = _as_date(item.get("date"))
        if not day:
            continue
        await _upsert_source_record(
            db, user_id, domain="daily_activity", external_id=str(item.get("date") or day),
            record_date=day, observed_at=None, payload=item,
        )
        row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user_id, DailyHealth.date == day))
        if not row:
            row = DailyHealth(user_id=user_id, date=day, raw={})
            db.add(row)
        row.raw = _source_tag(row.raw, "withings_activity", item)
        active_cal = _num(item.get("calories"))
        total_cal = _num(item.get("totalcalories"))
        values: dict[str, Any] = {
            "steps": _int(item.get("steps")),
            "distance_m": _num(item.get("distance")),
            "active_calories": active_cal,
            "resting_calories": max(0.0, total_cal - active_cal) if total_cal is not None and active_cal is not None else None,
        }
        for field, value in values.items():
            if value is None:
                continue
            # Direct Withings data outranks duplicate/aggregated values from
            # Garmin or SparkyFitness for the same calendar day.
            setattr(row, field, value)
            row.raw = _tag_metric_source(row.raw, field)
        count += 1
    return count


async def _fetch_sleep(client: WithingsApiClient, start: date, end: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fields = "nb_wakeup,wakeupduration,durationtosleep,durationtowakeup,lightsleepduration,deepsleepduration,remsleepduration,sleep_score,hr_average,hr_min,hr_max,rr_average,rr_min,rr_max"
    for chunk_start, chunk_end in _chunks(start, end, 30):
        body = await client.request("v2/sleep", action="getsummary", data={
            "startdateymd": chunk_start.isoformat(),
            "enddateymd": chunk_end.isoformat(),
            "data_fields": fields,
        })
        series = body.get("series") or []
        rows.extend(item for item in series if isinstance(item, dict))
    return rows


async def _merge_sleep(db: AsyncSession, user_id: uuid.UUID, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for item in rows:
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        start_at = _epoch_dt(item.get("startdate"))
        end_at = _epoch_dt(item.get("enddate"))
        day = _as_date(item.get("date")) or (end_at.date() if end_at else None) or (start_at.date() if start_at else None)
        if not day:
            continue
        external_id = str(item.get("id") or item.get("startdate") or f"sleep:{day.isoformat()}")
        await _upsert_source_record(
            db, user_id, domain="sleep", external_id=external_id,
            record_date=day, observed_at=start_at, payload=item,
        )
        row = await db.scalar(select(SleepSession).where(SleepSession.user_id == user_id, SleepSession.date == day))
        if not row:
            row = SleepSession(user_id=user_id, date=day, raw={})
            db.add(row)
        row.raw = _source_tag(row.raw, "withings", item)
        deep = _int(data.get("deepsleepduration"))
        light = _int(data.get("lightsleepduration"))
        rem = _int(data.get("remsleepduration"))
        awake = _int(data.get("wakeupduration"))
        stages = [value for value in (deep, light, rem) if value is not None]
        duration = sum(stages) if stages else None
        values: dict[str, Any] = {
            "start_at": start_at,
            "end_at": end_at,
            "duration_seconds": duration,
            "sleep_score": _num(data.get("sleep_score")),
            "deep_seconds": deep,
            "light_seconds": light,
            "rem_seconds": rem,
            "awake_seconds": awake,
            "avg_respiration": _num(data.get("rr_average")),
        }
        for field, value in values.items():
            if value is None:
                continue
            setattr(row, field, value)
            row.raw = _tag_metric_source(row.raw, field)
        count += 1
    return count


async def delete_local_withings_data(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    counts = {"source_records": 0, "body_rows_deleted": 0, "body_rows_touched": 0, "health_rows_touched": 0, "sleep_rows_touched": 0}
    ids = (await db.scalars(select(SourceRecord.id).where(
        SourceRecord.user_id == user_id, SourceRecord.source == "withings"
    ))).all()
    counts["source_records"] = len(ids)
    await db.execute(delete(SourceRecord).where(SourceRecord.user_id == user_id, SourceRecord.source == "withings"))

    for row in (await db.scalars(select(BodyMeasurement).where(BodyMeasurement.user_id == user_id))).all():
        raw = dict(row.raw or {})
        sources = _metric_sources(raw)
        fields = {field for field, source in sources.items() if source == "withings" and field in BODY_FIELDS}
        if not fields and "withings" not in raw:
            continue
        counts["body_rows_touched"] += 1
        non_withings_sources = {source for field, source in sources.items() if field in BODY_FIELDS and source != "withings"}
        if not non_withings_sources and all((getattr(row, field) is None or field in fields) for field in BODY_FIELDS):
            await db.delete(row)
            counts["body_rows_deleted"] += 1
            continue
        for field in fields:
            setattr(row, field, None)
        raw.pop("withings", None)
        raw.pop("withings_measurements", None)
        raw["_metric_sources"] = {field: source for field, source in sources.items() if source != "withings"}
        row.raw = raw

    for model, fields, counter, raw_keys in (
        (DailyHealth, DAILY_FIELDS, "health_rows_touched", ("withings_activity",)),
        (SleepSession, SLEEP_FIELDS, "sleep_rows_touched", ("withings",)),
    ):
        for row in (await db.scalars(select(model).where(model.user_id == user_id))).all():
            raw = dict(row.raw or {})
            sources = _metric_sources(raw)
            withings_fields = {field for field, source in sources.items() if source == "withings" and field in fields}
            if not withings_fields and not any(key in raw for key in raw_keys):
                continue
            counts[counter] += 1
            for field in withings_fields:
                setattr(row, field, None)
            for key in raw_keys:
                raw.pop(key, None)
            remaining = {field: source for field, source in sources.items() if source != "withings"}
            if remaining:
                raw["_metric_sources"] = remaining
            else:
                raw.pop("_metric_sources", None)
            row.raw = raw

    conn = await db.scalar(select(WithingsConnection).where(WithingsConnection.user_id == user_id))
    if conn:
        conn.last_sync_summary = {}
        conn.sync_cursors = {}
        conn.last_successful_sync_at = None
    await db.commit()
    return counts


async def sync_withings(db: AsyncSession, user_id: uuid.UUID, *, progress=None, incremental: bool = False) -> dict[str, Any]:
    conn = await db.scalar(select(WithingsConnection).where(WithingsConnection.user_id == user_id))
    if not conn or conn.status != "connected":
        raise WithingsError("WITHINGS_NOT_CONNECTED")

    try:
        access_token = await _ensure_access_token(db, conn)
        client = WithingsApiClient(access_token)
        today = date.today()
        configured_days = max(0, int(conn.sync_days or 0))
        if incremental:
            start = today - timedelta(days=1)
        elif configured_days <= 0:
            start = date(2009, 1, 1)
        else:
            start = today - timedelta(days=configured_days - 1)
        end = today
        result: dict[str, Any] = {"from": start.isoformat(), "to": end.isoformat(), "incremental": incremental}
        cursors = dict(conn.sync_cursors or {})

        if conn.sync_body:
            if progress:
                progress({"phase": "measurements", "message": "Withings body & measurements"})
            groups: list[dict[str, Any]] = []
            if incremental and cursors.get("measure_modified"):
                groups = await _fetch_measure_groups(client, start, end, lastupdate=int(cursors["measure_modified"]))
            else:
                for chunk_start, chunk_end in _chunks(start, end, 366):
                    groups.extend(await _fetch_measure_groups(client, chunk_start, chunk_end))
            result["measurements"] = await _merge_measure_groups(db, user_id, groups)
            modified = [int(x.get("modified")) for x in groups if _int(x.get("modified")) is not None]
            if modified:
                cursors["measure_modified"] = max(modified)

        if conn.sync_daily_activity:
            if progress:
                progress({"phase": "daily_activity", "message": "Withings daily activity"})
            activity = await _fetch_activity(client, start, end)
            result["daily_activity"] = await _merge_activity(db, user_id, activity)

        if conn.sync_sleep:
            if progress:
                progress({"phase": "sleep", "message": "Withings sleep"})
            sleep = await _fetch_sleep(client, start, end)
            result["sleep"] = await _merge_sleep(db, user_id, sleep)

        now = datetime.now(timezone.utc)
        conn.status = "connected"
        conn.sync_cursors = cursors
        conn.last_successful_sync_at = now
        conn.last_sync_summary = result
        conn.last_error_code = None
        conn.last_error_at = None
        if conn.auto_sync_enabled:
            conn.next_sync_at = now + timedelta(minutes=max(15, int(conn.sync_interval_minutes or 60)))
        await db.commit()
        return result
    except Exception as exc:
        conn.status = "error" if isinstance(exc, WithingsError) and exc.code == "WITHINGS_REAUTH_REQUIRED" else conn.status
        conn.last_error_code = exc.code if isinstance(exc, WithingsError) else type(exc).__name__
        conn.last_error_at = datetime.now(timezone.utc)
        await db.commit()
        raise
