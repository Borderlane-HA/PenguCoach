from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import BodyMeasurement, DailyHealth, HrvDaily, SleepSession, SourceRecord, SparkyFitnessConnection
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
    for key in ("sessions", "items", "entries", "history", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _session_date(item: dict[str, Any]) -> date | None:
    return _as_date(_first(item, "entry_date", "date", "started_at", "start_time", "created_at"))


def _session_id(item: dict[str, Any], index: int) -> str:
    value = _first(item, "id", "session_id", "exercise_entry_id", "external_id")
    if value is not None:
        return str(value)
    return f"derived-{_json_hash(item)[:24]}-{index}"


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


async def _merge_checkins(db: AsyncSession, user_id: uuid.UUID, rows: Iterable[dict[str, Any]]) -> int:
    changed = 0
    for item in rows:
        day = _as_date(_first(item, "entry_date", "date"))
        if not day:
            continue
        await _upsert_source_record(db, user_id, domain="checkin", external_id=str(_first(item, "id") or day), record_date=day, payload=item)
        health = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user_id, DailyHealth.date == day))
        if not health:
            health = DailyHealth(user_id=user_id, date=day, raw={})
            db.add(health)
        steps = _int(item.get("steps"))
        if health.steps is None and steps is not None:
            health.steps = steps
            changed += 1
        health.raw = _source_tag(health.raw, item)

        weight = _num(_first(item, "weight", "weight_kg"))
        fat = _num(_first(item, "body_fat_percentage", "body_fat", "bodyFat"))
        if weight is not None or fat is not None:
            measured_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
            body = await db.scalar(select(BodyMeasurement).where(
                BodyMeasurement.user_id == user_id, BodyMeasurement.measured_at == measured_at
            ))
            if not body:
                body = BodyMeasurement(user_id=user_id, measured_at=measured_at, raw={})
                db.add(body)
            if body.weight_kg is None and weight is not None:
                body.weight_kg = weight
                changed += 1
            if body.body_fat_percent is None and fat is not None:
                body.body_fat_percent = fat
                changed += 1
            body.raw = _source_tag(body.raw, item)
    return changed


def _stage_seconds(item: dict[str, Any]) -> dict[str, int | None]:
    result: dict[str, int] = {"deep": 0, "light": 0, "rem": 0, "awake": 0}
    seen = False
    events = item.get("stage_events") or item.get("stageEvents") or []
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
        day = _as_date(_first(item, "entry_date", "date"))
        if not day:
            continue
        await _upsert_source_record(db, user_id, domain="sleep", external_id=str(_first(item, "id") or day), record_date=day, payload=item)
        row = await db.scalar(select(SleepSession).where(SleepSession.user_id == user_id, SleepSession.date == day))
        if not row:
            row = SleepSession(user_id=user_id, date=day, raw={})
            db.add(row)
        values = {
            "start_at": _as_dt(_first(item, "bedtime", "start_at", "start_time")),
            "end_at": _as_dt(_first(item, "wake_time", "end_at", "end_time")),
            "duration_seconds": _int(_first(item, "duration_in_seconds", "duration_seconds")),
            "sleep_score": _num(_first(item, "sleep_score", "score")),
        }
        stage = _stage_seconds(item)
        values.update({f"{key}_seconds": value for key, value in stage.items()})
        for field, value in values.items():
            if value is not None and getattr(row, field) is None:
                setattr(row, field, value)
                changed += 1
        row.raw = _source_tag(row.raw, item)
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
        try:
            payload = await client.request(f"/measurements/custom-measurements-range/{category_id}/{start.isoformat()}/{end.isoformat()}")
        except SparkyFitnessError:
            continue
        entries = _list_payload(payload)
        if not entries and isinstance(payload, list):
            entries = [x for x in payload if isinstance(x, dict)]
        for item in entries:
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
                if row.overnight_average is None:
                    row.overnight_average = value
                    hrv_count += 1
                row.raw = _source_tag(row.raw, item)
            else:
                row = await db.scalar(select(DailyHealth).where(DailyHealth.user_id == user_id, DailyHealth.date == day))
                if not row:
                    row = DailyHealth(user_id=user_id, date=day, raw={})
                    db.add(row)
                if row.resting_hr is None:
                    row.resting_hr = int(round(value))
                    rhr_count += 1
                row.raw = _source_tag(row.raw, item)
    return hrv_count, rhr_count


async def _sync_activities(
    db: AsyncSession,
    client: SparkyFitnessClient,
    user_id: uuid.UUID,
    start: date,
    *,
    progress=None,
) -> dict[str, int]:
    page = 1
    pages = 0
    seen = 0
    changed = 0
    while page <= 500:
        payload = await client.request("/v2/exercise-entries/history", params={"page": page, "pageSize": 100})
        items = _list_payload(payload)
        if not items:
            break
        pages += 1
        oldest: date | None = None
        for index, item in enumerate(items):
            day = _session_date(item)
            if day and (oldest is None or day < oldest):
                oldest = day
            if day and day < start:
                continue
            seen += 1
            if await _upsert_source_record(
                db, user_id, domain="exercise_session", external_id=_session_id(item, index), record_date=day, payload=item
            ):
                changed += 1
        if progress:
            progress({"phase": "activities", "pages": pages, "sessions": seen, "page": page})
        if oldest and oldest < start:
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
    return {"pages": pages, "sessions": seen, "changed": changed}


async def sync_sparkyfitness(db: AsyncSession, user_id: uuid.UUID, *, progress=None) -> dict[str, Any]:
    conn = await db.scalar(select(SparkyFitnessConnection).where(SparkyFitnessConnection.user_id == user_id))
    if not conn or conn.status != "connected":
        raise ValueError("SPARKYFITNESS_NOT_CONNECTED")
    client = SparkyFitnessClient(conn.base_url, SecretBox().decrypt(conn.api_key_ciphertext), timeout_seconds=45)
    days = max(1, min(int(conn.sync_days or 30), 366))
    end = date.today()
    start = end - timedelta(days=days - 1)
    capabilities = dict(conn.capabilities or {})
    summary: dict[str, Any] = {"days": days, "from": start.isoformat(), "to": end.isoformat()}
    try:
        if conn.sync_daily_health and capabilities.get("checkins"):
            if progress:
                progress({"phase": "daily_health", "message": "SparkyFitness daily health"})
            payload = await client.request(f"/measurements/check-in-measurements-range/{start.isoformat()}/{end.isoformat()}")
            rows = _list_payload(payload)
            if isinstance(payload, list):
                rows = [x for x in payload if isinstance(x, dict)]
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
            payload = await client.request("/sleep", params={"startDate": start.isoformat(), "endDate": end.isoformat()})
            rows = _list_payload(payload)
            if isinstance(payload, list):
                rows = [x for x in payload if isinstance(x, dict)]
            summary["sleep_entries"] = len(rows)
            summary["sleep_fields_filled"] = await _merge_sleep(db, user_id, rows)
        if conn.sync_activities and capabilities.get("activities"):
            summary["activities"] = await _sync_activities(db, client, user_id, start, progress=progress)
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
