from __future__ import annotations

import hashlib
import io
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import Activity, ActivityMetric, FitFile, User
from pengucoach.fit.activity_detail import build_activity_stats

SUPPORTED_EXTENSIONS = {".fit", ".gpx", ".tcx", ".zip"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _first_descendant(element: ET.Element, *names: str) -> str | None:
    wanted = {name.lower() for name in names}
    for child in element.iter():
        if _local(child.tag) in wanted:
            value = _text(child)
            if value is not None:
                return value
    return None


def _container_value(element: ET.Element, container: str) -> str | None:
    for child in element.iter():
        if _local(child.tag) == container.lower():
            direct = _text(child)
            if direct is not None:
                return direct
            nested = _first_descendant(child, "value")
            if nested is not None:
                return nested
    return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def _with_derived_distance_speed(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    distance = 0.0
    previous: tuple[float, float, datetime] | None = None
    for item in records:
        lat = _number(item.get("position_lat"))
        lon = _number(item.get("position_long"))
        stamp = _parse_dt(item.get("timestamp"))
        explicit_distance = _number(item.get("distance"))
        if explicit_distance is not None:
            distance = explicit_distance
        elif lat is not None and lon is not None and previous is not None:
            distance += _haversine_m(previous[0], previous[1], lat, lon)
        item["distance"] = distance
        if _number(item.get("speed")) is None and previous is not None and lat is not None and lon is not None and stamp is not None:
            seconds = (stamp - previous[2]).total_seconds()
            if 0 < seconds <= 300:
                item["speed"] = _haversine_m(previous[0], previous[1], lat, lon) / seconds
        if lat is not None and lon is not None and stamp is not None:
            previous = (lat, lon, stamp)
    return records


def parse_gpx_bytes(raw: bytes) -> tuple[pd.DataFrame, dict[str, Any], str | None, str | None]:
    root = ET.fromstring(raw)
    track = next((x for x in root.iter() if _local(x.tag) == "trk"), root)
    name = _first_descendant(track, "name")
    raw_type = (_first_descendant(track, "type") or "").lower()
    if any(x in raw_type for x in ("bike", "cycling", "bicycle")):
        sport = "cycling"
    elif any(x in raw_type for x in ("run", "running")):
        sport = "running"
    elif "swim" in raw_type:
        sport = "swimming"
    elif any(x in raw_type for x in ("walk", "hike", "hiking")):
        sport = "walking" if "walk" in raw_type else "hiking"
    else:
        sport = raw_type.replace(" ", "_") or "other"

    records: list[dict[str, Any]] = []
    for point in (x for x in root.iter() if _local(x.tag) == "trkpt"):
        lat = _number(point.attrib.get("lat")); lon = _number(point.attrib.get("lon"))
        item: dict[str, Any] = {"position_lat": lat, "position_long": lon}
        for child in point:
            tag = _local(child.tag)
            value = _text(child)
            if tag == "ele": item["altitude"] = _number(value)
            elif tag == "time": item["timestamp"] = value
        for child in point.iter():
            tag = _local(child.tag)
            value = _text(child)
            if value is None:
                continue
            if tag in {"hr", "heartrate", "heartratebpm"}: item["heart_rate"] = _number(value)
            elif tag in {"cad", "cadence"}: item["cadence"] = _number(value)
            elif tag in {"power", "watts"}: item["power"] = _number(value)
            elif tag in {"atemp", "temperature"}: item["temperature"] = _number(value)
            elif tag == "speed": item["speed"] = _number(value)
        records.append(item)
    records = _with_derived_distance_speed(records)
    df = pd.DataFrame.from_records(records)
    session: dict[str, Any] = {"source_format": "gpx"}
    if records:
        session["start_time"] = records[0].get("timestamp")
        session["total_distance"] = records[-1].get("distance")
    return df, session, name, sport


def parse_tcx_bytes(raw: bytes) -> tuple[pd.DataFrame, dict[str, Any], str | None, str | None]:
    root = ET.fromstring(raw)
    activity = next((x for x in root.iter() if _local(x.tag) == "activity"), root)
    raw_sport = (activity.attrib.get("Sport") or activity.attrib.get("sport") or "Other").lower()
    sport = "running" if "run" in raw_sport else "cycling" if any(x in raw_sport for x in ("bike", "biking", "cycling")) else "swimming" if "swim" in raw_sport else "other"
    activity_id = _first_descendant(activity, "id")
    laps: list[dict[str, Any]] = []
    for lap in (x for x in activity if _local(x.tag) == "lap"):
        laps.append({
            "total_timer_time": _number(_first_descendant(lap, "totaltimeseconds")),
            "total_distance": _number(_first_descendant(lap, "distancemeters")),
            "total_calories": _number(_first_descendant(lap, "calories")),
            "avg_heart_rate": _number(_container_value(lap, "averageheartratebpm")),
            "max_heart_rate": _number(_container_value(lap, "maximumheartratebpm")),
        })

    records: list[dict[str, Any]] = []
    for point in (x for x in activity.iter() if _local(x.tag) == "trackpoint"):
        item: dict[str, Any] = {}
        item["timestamp"] = _first_descendant(point, "time")
        item["altitude"] = _number(_first_descendant(point, "altitudemeters"))
        item["distance"] = _number(_first_descendant(point, "distancemeters"))
        item["heart_rate"] = _number(_container_value(point, "heartratebpm"))
        item["cadence"] = _number(_first_descendant(point, "cadence"))
        position = next((x for x in point.iter() if _local(x.tag) == "position"), None)
        if position is not None:
            item["position_lat"] = _number(_first_descendant(position, "latitudedegrees"))
            item["position_long"] = _number(_first_descendant(position, "longitudedegrees"))
        for child in point.iter():
            tag = _local(child.tag)
            value = _text(child)
            if value is None:
                continue
            if tag == "speed": item["speed"] = _number(value)
            elif tag in {"watts", "power"}: item["power"] = _number(value)
            elif tag in {"runcadence", "cadence"} and item.get("cadence") is None: item["cadence"] = _number(value)
        records.append(item)
    records = _with_derived_distance_speed(records)
    df = pd.DataFrame.from_records(records)
    session: dict[str, Any] = {"source_format": "tcx", "start_time": activity_id, "_laps": laps}
    if laps:
        session["total_timer_time"] = sum(x.get("total_timer_time") or 0 for x in laps) or None
        session["total_distance"] = sum(x.get("total_distance") or 0 for x in laps) or None
        session["total_calories"] = sum(x.get("total_calories") or 0 for x in laps) or None
    elif records:
        session["total_distance"] = records[-1].get("distance")
    return df, session, None, sport


def _fit_bytes(raw: bytes) -> bytes:
    bio = io.BytesIO(raw)
    if zipfile.is_zipfile(bio):
        with zipfile.ZipFile(bio) as archive:
            entries = [info for info in archive.infolist() if info.filename.lower().endswith(".fit") and not info.is_dir()]
            if not entries or entries[0].file_size > MAX_UPLOAD_BYTES:
                raise ValueError("INVALID_ACTIVITY_FILE")
            return archive.read(entries[0])
    return raw


def _first_number(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(mapping.get(key))
        if value is not None:
            return value
    return None


def _mean_numeric(df: pd.DataFrame, *names: str) -> float | None:
    for name in names:
        if name in df.columns:
            values = pd.to_numeric(df[name], errors="coerce").dropna()
            if len(values):
                return float(values.mean())
    return None


def _max_numeric(df: pd.DataFrame, *names: str) -> float | None:
    for name in names:
        if name in df.columns:
            values = pd.to_numeric(df[name], errors="coerce").dropna()
            if len(values):
                return float(values.max())
    return None


def _duration_from_df(df: pd.DataFrame) -> int | None:
    if "timestamp" not in df.columns:
        return None
    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dropna()
    if len(ts) < 2:
        return None
    return max(0, int((ts.iloc[-1] - ts.iloc[0]).total_seconds()))


def _sport_from_fit(session: dict[str, Any]) -> str:
    sport = str(session.get("sport") or session.get("sub_sport") or "other").lower().replace(" ", "_")
    aliases = {"biking": "cycling", "bike": "cycling", "run": "running", "swim": "swimming"}
    return aliases.get(sport, sport)


def _safe_filename(filename: str) -> str:
    base = Path(filename).name[:180]
    return "".join(c for c in base if c.isalnum() or c in "-_. ") or "activity"


async def import_manual_activity(
    db: AsyncSession,
    user: User,
    filename: str,
    raw: bytes,
    *,
    name_override: str | None = None,
    sport_override: str | None = None,
) -> Activity:
    if not raw:
        raise ValueError("EMPTY_UPLOAD")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("UPLOAD_TOO_LARGE")

    safe_filename = _safe_filename(filename)
    extension = Path(safe_filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("UNSUPPORTED_ACTIVITY_FILE")

    canonical = _fit_bytes(raw) if extension in {".fit", ".zip"} else raw
    digest = hashlib.sha256(canonical).hexdigest()
    duplicate = await db.scalar(select(FitFile).where(FitFile.user_id == user.id, FitFile.sha256 == digest))
    if duplicate:
        raise ValueError(f"DUPLICATE_UPLOAD:{duplicate.activity_id}")

    activity_uuid = __import__("uuid").uuid4()
    manual_id = -max(1, int(digest[:15], 16))
    while await db.scalar(select(Activity.id).where(Activity.user_id == user.id, Activity.garmin_activity_id == manual_id)):
        manual_id -= 1

    import_format = "fit" if extension in {".fit", ".zip"} else extension.lstrip(".")
    temp_dir = settings.fit_dir / str(user.id) / "manual-tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{activity_uuid}.{import_format}"
    temp_path.write_bytes(canonical)
    try:
        if import_format == "fit":
            from pengucoach.fit.service import _parse_fit
            df, session = _parse_fit(temp_path)
            inferred_name = None
            inferred_sport = _sport_from_fit(session)
            parser_name = "fitdecode"
        elif import_format == "gpx":
            df, session, inferred_name, inferred_sport = parse_gpx_bytes(canonical)
            parser_name = "gpx"
        else:
            df, session, inferred_name, inferred_sport = parse_tcx_bytes(canonical)
            parser_name = "tcx"
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise ValueError("INVALID_ACTIVITY_FILE") from exc

    started_at = _parse_dt(session.get("start_time") or session.get("timestamp"))
    if started_at is None and "timestamp" in df.columns:
        timestamps = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dropna()
        if len(timestamps):
            started_at = timestamps.iloc[0].to_pydatetime()
    started_at = started_at or datetime.now(timezone.utc)
    year = started_at.year

    target_dir = settings.fit_dir / str(user.id) / str(year)
    parquet_dir = settings.parquet_dir / str(user.id) / str(year)
    target_dir.mkdir(parents=True, exist_ok=True); parquet_dir.mkdir(parents=True, exist_ok=True)
    stored_ext = ".fit" if import_format == "fit" else f".{import_format}"
    original_path = target_dir / f"manual-{activity_uuid}{stored_ext}"
    temp_path.replace(original_path)

    parquet_path: Path | None = None
    if not df.empty:
        parquet_path = parquet_dir / f"manual-{activity_uuid}.parquet"
        df.to_parquet(parquet_path, index=False)

    from pengucoach.fit.service import _analytics
    analytics = _analytics(df)
    stats = build_activity_stats(df, sport_type=sport_override or inferred_sport)
    heart = stats.get("heart_rate") or {}
    speed = stats.get("speed_kmh") or {}
    power = stats.get("power_w") or {}
    cadence = stats.get("cadence") or {}
    elevation = stats.get("elevation") or {}

    sport = (sport_override or inferred_sport or "other").strip().lower().replace(" ", "_")
    display_name = (name_override or inferred_name or Path(safe_filename).stem or "Imported activity").strip()[:255]
    duration = _first_number(session, "total_timer_time", "total_elapsed_time", "duration")
    if duration is None:
        duration = _duration_from_df(df)
    distance = _first_number(session, "total_distance", "distance")
    if distance is None:
        distance = _max_numeric(df, "distance")
    avg_speed = _first_number(session, "enhanced_avg_speed", "avg_speed", "average_speed")
    if avg_speed is None and _number(speed.get("avg")) is not None:
        avg_speed = _number(speed.get("avg")) / 3.6

    activity = Activity(
        id=activity_uuid,
        user_id=user.id,
        garmin_activity_id=manual_id,
        name=display_name,
        sport_type=sport,
        subsport_type=str(session.get("sub_sport") or "") or None,
        started_at=started_at,
        duration_seconds=int(duration) if duration is not None else None,
        moving_seconds=int(_first_number(session, "total_timer_time") or duration) if duration is not None else None,
        distance_m=distance,
        calories=_first_number(session, "total_calories", "calories"),
        avg_hr=int(_first_number(session, "avg_heart_rate") or _number(heart.get("avg"))) if (_first_number(session, "avg_heart_rate") is not None or _number(heart.get("avg")) is not None) else None,
        max_hr=int(_first_number(session, "max_heart_rate") or _number(heart.get("max"))) if (_first_number(session, "max_heart_rate") is not None or _number(heart.get("max")) is not None) else None,
        avg_speed=avg_speed,
        avg_power=_first_number(session, "avg_power", "average_power") or _number(power.get("avg")),
        avg_cadence=_first_number(session, "avg_cadence", "average_cadence") or _number(cadence.get("avg")),
        vo2max=_first_number(session, "vo2_max", "vo2max", "vo2_maximum"),
        elevation_gain=_first_number(session, "total_ascent", "elevation_gain") or _number(elevation.get("gain_m")),
        fit_status="parsed",
        raw={
            "source": "manual_upload",
            "filename": safe_filename,
            "format": import_format,
            "imported_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(activity)
    await db.flush()

    fit_row = FitFile(
        user_id=user.id,
        activity_id=activity.id,
        original_path=str(original_path),
        parquet_path=str(parquet_path) if parquet_path else None,
        file_size=len(canonical),
        sha256=digest,
        parsed_at=datetime.now(timezone.utc),
        parser_name=parser_name,
        parser_version="1",
        status="parsed",
        data_quality=analytics["quality"],
    )
    db.add(fit_row)
    metrics = analytics["metrics"]
    db.add(ActivityMetric(
        user_id=user.id,
        activity_id=activity.id,
        analytics_version="1.0",
        hr_drift=metrics.get("hr_drift"),
        pace_drift=metrics.get("pace_drift"),
        power_drift=metrics.get("power_drift"),
        aerobic_decoupling=metrics.get("aerobic_decoupling"),
        pace_consistency=metrics.get("pace_consistency"),
        cadence_drift=metrics.get("cadence_drift"),
        data_quality_score=analytics["quality"].get("overall"),
        details={"session": session, "quality": analytics["quality"], "source": "manual_upload", "format": import_format},
    ))
    await db.commit()
    await db.refresh(activity)
    return activity
