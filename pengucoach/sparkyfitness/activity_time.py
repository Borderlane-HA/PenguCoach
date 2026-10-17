"""Recorded workout time, with explicit precision for date-only Sparky rows."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONTAINERS = (
    "exercise_entry_details", "exerciseEntryDetails", "telemetry", "raw_data", "rawData",
    "provider_activity_details", "providerActivityDetails", "activity_details", "activityDetails",
    "activity", "details", "entry", "data", "workout", "session", "detail_data", "detailData",
)
START_KEYS = ("startTime", "started_at", "start_time", "startAt", "start_at", "startDate", "entry_timestamp", "entryTimestamp", "timestamp", "logged_at", "loggedAt", "measured_at", "measuredAt")


def mapping(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            result = json.loads(value)
            return result if isinstance(result, dict) else None
        except ValueError:
            pass
    return None


def containers(item: dict) -> list[dict]:
    queue = [item[k] for k in ("exercise_entry_details", "exerciseEntryDetails") if isinstance(item.get(k), dict)] + [item]
    result, seen = [], set()
    while queue and len(result) < 128:
        row = queue.pop(0)
        if id(row) in seen:
            continue
        seen.add(id(row))
        result.append(row)
        for key in CONTAINERS:
            child = mapping(row.get(key))
            if child:
                queue.append(child)
            elif key in {"activity_details", "activityDetails", "provider_activity_details", "details"} and isinstance(row.get(key), list):
                queue.extend(value for value in row[key][:128] if isinstance(value, dict))
    return result


def _first(rows, *keys):
    return next((r[k] for r in rows for k in keys if r.get(k) not in (None, "")), None)


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _zone(value):
    try:
        return ZoneInfo(str(value))
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _localize(value: datetime, zone) -> datetime | None:
    if value.tzinfo:
        return value.astimezone(timezone.utc)
    if zone is None:
        return None
    first, second = value.replace(tzinfo=zone, fold=0), value.replace(tzinfo=zone, fold=1)
    a, b = first.astimezone(timezone.utc), second.astimezone(timezone.utc)
    if a.astimezone(zone).replace(tzinfo=None) != value:
        return None  # DST gap.
    if a != b and b.astimezone(zone).replace(tzinfo=None) == value:
        return None  # Repeated clock hour requires an explicit offset.
    return a


def _stamp(value, zone) -> datetime | None:
    if isinstance(value, datetime):
        return _localize(value, zone)
    if not isinstance(value, str) or not re.search(r"[T ]\d{2}:\d{2}", value):
        return None
    try:
        return _localize(datetime.fromisoformat(value.strip().replace("Z", "+00:00")), zone)
    except ValueError:
        return None


@dataclass(frozen=True)
class ActivityTime:
    timestamp: datetime | None
    local_date: date | None
    precision: str
    source: str
    zone: str

    def metadata(self) -> dict:
        return {"version": 1, "precision": self.precision, "source": self.source,
                "local_date": self.local_date.isoformat() if self.local_date else None, "timezone": self.zone}


def resolve_activity_time(item: dict, default_timezone: str = "UTC") -> ActivityTime:
    rows = containers(item)
    record_zone = _first(rows, "record_timezone", "recordTimezone", "timezone", "time_zone")
    zone_name = str(record_zone or default_timezone or "UTC")
    zone = _zone(zone_name)
    fallback_zone = _zone(default_timezone) or timezone.utc
    local_zone = zone or fallback_zone

    def exact(stamp, source):
        return ActivityTime(stamp, stamp.astimezone(local_zone).date(), "second", source, zone_name)

    # Original provider payload always wins over convenience/audit columns.
    for parent in rows:
        for name in ("raw_data", "rawData"):
            raw = mapping(parent.get(name))
            if raw:
                for key in START_KEYS:
                    stamp = _stamp(raw.get(key), zone)
                    if stamp:
                        return exact(stamp, f"{name}.{key}")

    explicit_day = _day(_first(rows, "entry_date", "entryDate", "date"))
    clock = _first(rows, "entry_time", "entryTime")
    if explicit_day and clock is not None:
        try:
            stamp = _localize(datetime.combine(explicit_day, time.fromisoformat(str(clock).replace("Z", "+00:00"))), zone)
        except ValueError:
            stamp = None
        if stamp:
            return exact(stamp, "entry_date+entry_time")
        # Do not replace an invalid/ambiguous local clock with fake midnight.
    else:
        for row in rows:
            for key in START_KEYS:
                stamp = _stamp(row.get(key), zone)
                if stamp is None:
                    continue
                if explicit_day and stamp.time() == time.min and stamp.date() == explicit_day:
                    continue  # Relational midnight placeholder, not a proven clock time.
                return exact(stamp, key)

    day = explicit_day or _day(_first(rows, *START_KEYS, "created_at", "createdAt"))
    # Activity.started_at supports legacy queries; precision prevents displaying
    # or automatically matching this local-day placeholder as a recorded time.
    placeholder = _localize(datetime.combine(day, time.min), local_zone) if day else None
    return ActivityTime(placeholder, day, "date", "entry_date" if explicit_day else "date_fallback", zone_name)


def stored_time_info(activity) -> dict:
    raw = getattr(activity, "raw", None) or {}
    if raw.get("source") != "sparkyfitness":
        return {"precision": "second"}
    info = raw.get("_sparkyfitness_time")
    return info if isinstance(info, dict) else resolve_activity_time(raw.get("sparkyfitness") or {}).metadata()
