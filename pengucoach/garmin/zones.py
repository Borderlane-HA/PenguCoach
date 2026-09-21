from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import uuid

import pandas as pd
from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import SourceRecord, User
from pengucoach.garmin.sync.service import _hash_payload

HR_ZONE_DOMAIN = "training_zones_hr"
POWER_ZONE_DOMAIN = "training_zones_power"
ZONE_REFRESH_HOURS = 24


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _sport_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("sportTypeKey") or value.get("typeKey") or value.get("key") or value.get("name")
    text = str(value or "DEFAULT").strip().upper().replace("-", "_").replace(" ", "_")
    return text or "DEFAULT"


def _iter_dicts(payload: Any):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_dicts(item)


def _zone_ranges_from_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        zone = int(_num(item.get("zoneNumber") or item.get("zone") or item.get("number")) or index)
        low = _num(
            item.get("zoneLowBoundary")
            or item.get("lowBoundary")
            or item.get("lowerLimit")
            or item.get("low")
            or item.get("min")
        )
        high = _num(
            item.get("zoneHighBoundary")
            or item.get("highBoundary")
            or item.get("higherLimit")
            or item.get("high")
            or item.get("max")
        )
        if low is not None or high is not None:
            out.append({"zone": zone, "low": low, "high": high})
    return out


def _ranges_from_floors(item: dict[str, Any], *, max_value: float | None = None) -> list[dict[str, Any]]:
    floors = [_num(item.get(f"zone{i}Floor")) for i in range(1, 6)]
    if not any(value is not None for value in floors):
        return []
    out: list[dict[str, Any]] = []
    for idx, low in enumerate(floors):
        if low is None:
            continue
        next_low = next((x for x in floors[idx + 1 :] if x is not None), None)
        high = (next_low - 1) if next_low is not None else max_value
        out.append({"zone": idx + 1, "low": low, "high": high})
    return out


def normalize_heart_rate_zones(payload: Any) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    profiles: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        max_hr = _num(item.get("maxHeartRateUsed") or item.get("maxHeartRate"))
        ranges = _ranges_from_floors(item, max_value=max_hr)
        if not ranges:
            ranges = _zone_ranges_from_list(item.get("zones") or item.get("heartRateZones"))
        if not ranges:
            continue
        profiles.append({
            "sport": _sport_name(item.get("sport") or item.get("sportType") or item.get("sportTypeKey")),
            "training_method": item.get("trainingMethod"),
            "max_hr_bpm": int(max_hr) if max_hr is not None else None,
            "resting_hr_bpm": int(_num(item.get("restingHeartRateUsed")) or 0) or None,
            "lactate_threshold_hr_bpm": int(_num(item.get("lactateThresholdHeartRateUsed")) or 0) or None,
            "zones": [
                {"zone": int(z["zone"]), "low_bpm": int(z["low"]) if z.get("low") is not None else None,
                 "high_bpm": int(z["high"]) if z.get("high") is not None else None}
                for z in ranges
            ],
        })
    return profiles


def normalize_power_zones(payload: Any) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[int, float | None, float | None], ...]]] = set()
    for item in _iter_dicts(payload):
        sport_raw = item.get("sport") or item.get("sportType") or item.get("sportTypeKey") or item.get("sportKey")
        ftp = _num(item.get("functionalThresholdPower") or item.get("ftp") or item.get("thresholdPower"))
        ranges = _zone_ranges_from_list(item.get("zones") or item.get("powerZones") or item.get("zoneRanges"))
        if not ranges:
            ranges = _ranges_from_floors(item)
        if not ranges:
            # Some payloads carry flat low/high keys instead of a zones array.
            flat: list[dict[str, Any]] = []
            for zone in range(1, 11):
                low = _num(item.get(f"zone{zone}LowBoundary") or item.get(f"zone{zone}Low") or item.get(f"zone{zone}Min"))
                high = _num(item.get(f"zone{zone}HighBoundary") or item.get(f"zone{zone}High") or item.get(f"zone{zone}Max"))
                if low is not None or high is not None:
                    flat.append({"zone": zone, "low": low, "high": high})
            ranges = flat
        if not ranges:
            continue
        sport = _sport_name(sport_raw)
        key = (sport, tuple((int(z["zone"]), z.get("low"), z.get("high")) for z in ranges))
        if key in seen:
            continue
        seen.add(key)
        profiles.append({
            "sport": sport,
            "ftp_w": int(ftp) if ftp is not None else None,
            "zones": [
                {"zone": int(z["zone"]), "low_w": int(z["low"]) if z.get("low") is not None else None,
                 "high_w": int(z["high"]) if z.get("high") is not None else None}
                for z in ranges
            ],
        })
    return profiles


async def _latest_record(db: AsyncSession, user_id: uuid.UUID, domain: str) -> SourceRecord | None:
    return await db.scalar(
        select(SourceRecord)
        .where(SourceRecord.user_id == user_id, SourceRecord.domain == domain)
        .order_by(SourceRecord.fetched_at.desc())
        .limit(1)
    )


async def _store_changed(db: AsyncSession, user: User, domain: str, payload: Any) -> bool:
    if payload in (None, {}, []):
        return False
    digest = _hash_payload(payload)
    latest = await _latest_record(db, user.id, domain)
    if latest and latest.content_hash == digest:
        return False
    db.add(SourceRecord(
        user_id=user.id,
        source="garmin",
        domain=domain,
        external_id="current",
        record_date=date.today(),
        content_hash=digest,
        payload=payload,
    ))
    await db.flush()
    return True


async def sync_training_zones(
    db: AsyncSession,
    user: User,
    gateway,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Refresh Garmin HR/power zone profiles without making zone failures fatal."""
    newest_hr = await _latest_record(db, user.id, HR_ZONE_DOMAIN)
    newest_power = await _latest_record(db, user.id, POWER_ZONE_DOMAIN)
    recent_rows = [row for row in (newest_hr, newest_power) if row and row.fetched_at]
    if not force and len(recent_rows) == 2:
        fetched = min(row.fetched_at for row in recent_rows)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if fetched >= datetime.now(timezone.utc) - timedelta(hours=ZONE_REFRESH_HOURS):
            return await training_zone_snapshot(db, user.id)

    errors: dict[str, str] = {}
    hr_payload: Any = None
    power_payload: Any = None
    try:
        hr_payload = await asyncio.to_thread(gateway.get_heart_rate_zones)
        await _store_changed(db, user, HR_ZONE_DOMAIN, hr_payload)
    except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError):
        raise
    except Exception as exc:
        errors["heart_rate"] = type(exc).__name__

    try:
        power_payload = await asyncio.to_thread(gateway.get_power_zones)
        await _store_changed(db, user, POWER_ZONE_DOMAIN, power_payload)
    except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError):
        raise
    except Exception as exc:
        errors["power"] = type(exc).__name__

    await db.flush()
    snapshot = await training_zone_snapshot(db, user.id)
    snapshot["errors"] = errors
    return snapshot


async def training_zone_snapshot(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    hr_row = await _latest_record(db, user_id, HR_ZONE_DOMAIN)
    power_row = await _latest_record(db, user_id, POWER_ZONE_DOMAIN)
    hr_profiles = normalize_heart_rate_zones(hr_row.payload) if hr_row else []
    power_profiles = normalize_power_zones(power_row.payload) if power_row else []
    timestamps = [row.fetched_at for row in (hr_row, power_row) if row and row.fetched_at]
    synced_at = max(timestamps) if timestamps else None
    return {
        "source": "garmin",
        "synced": bool(hr_profiles or power_profiles),
        "synced_at": synced_at,
        "heart_rate": {"profiles": hr_profiles, "profile_count": len(hr_profiles)},
        "power": {"profiles": power_profiles, "profile_count": len(power_profiles)},
    }


def sport_family(sport_type: str | None) -> str:
    value = str(sport_type or "").lower()
    if any(key in value for key in ("cycl", "bike", "biking", "road_biking", "mountain_biking")):
        return "CYCLING"
    if "run" in value:
        return "RUNNING"
    if "swim" in value:
        return "SWIMMING"
    return "DEFAULT"


def select_zone_profile(profiles: list[dict[str, Any]], sport_type: str | None) -> dict[str, Any] | None:
    family = sport_family(sport_type)
    by_sport = {_sport_name(row.get("sport")): row for row in profiles if isinstance(row, dict)}
    return by_sport.get(family) or by_sport.get("DEFAULT") or (profiles[0] if profiles else None)


def _time_distribution(series: pd.Series, timestamps: pd.Series | None, zones: list[dict[str, Any]], low_key: str, high_key: str) -> list[dict[str, Any]]:
    values = pd.to_numeric(series, errors="coerce")
    if values.empty or values.notna().sum() == 0 or not zones:
        return []
    if timestamps is not None and not timestamps.empty:
        ts = pd.to_datetime(timestamps, errors="coerce", utc=True)
        delta = (ts.shift(-1) - ts).dt.total_seconds()
        positive = delta[(delta > 0) & (delta <= 30)]
        fallback = float(positive.median()) if len(positive) else 1.0
        seconds = delta.where((delta > 0) & (delta <= 30), fallback).fillna(fallback)
    else:
        seconds = pd.Series(1.0, index=values.index)
    out: list[dict[str, Any]] = []
    for zone in zones:
        low = _num(zone.get(low_key))
        high = _num(zone.get(high_key))
        if low is None and high is None:
            continue
        mask = values.notna()
        if low is not None:
            mask &= values >= low
        if high is not None:
            mask &= values <= high
        total = float(seconds[mask].sum())
        out.append({
            "zone": int(zone.get("zone") or len(out) + 1),
            "seconds": int(round(total)),
            low_key: int(low) if low is not None else None,
            high_key: int(high) if high is not None else None,
        })
    return out


def activity_zone_time(parquet_path: str | None, sport_type: str | None, snapshot: dict[str, Any]) -> dict[str, Any]:
    if not parquet_path or not Path(parquet_path).exists():
        return {"source": "pengucoach_fit", "heart_rate": [], "power": []}
    try:
        df = pd.read_parquet(parquet_path)
    except Exception:
        return {"source": "pengucoach_fit", "heart_rate": [], "power": []}
    timestamp = df["timestamp"] if "timestamp" in df.columns else None
    hr_profile = select_zone_profile(snapshot.get("heart_rate", {}).get("profiles", []), sport_type)
    power_profile = select_zone_profile(snapshot.get("power", {}).get("profiles", []), sport_type)
    hr = _time_distribution(df["heart_rate"], timestamp, hr_profile.get("zones", []), "low_bpm", "high_bpm") if hr_profile and "heart_rate" in df.columns else []
    power = _time_distribution(df["power"], timestamp, power_profile.get("zones", []), "low_w", "high_w") if power_profile and "power" in df.columns else []
    return {
        "source": "pengucoach_fit",
        "zone_boundaries_source": "garmin",
        "heart_rate_profile": hr_profile,
        "power_profile": power_profile,
        "heart_rate": hr,
        "power": power,
    }
