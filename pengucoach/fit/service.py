from __future__ import annotations

import asyncio
import hashlib
import io
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitdecode
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import Activity, ActivityMetric, FitFile, GarminConnection, User
from pengucoach.garmin.gateway.factory import gateway_from_connection, serialize_refreshed_token
from pengucoach.fit.activity_detail import build_activity_stats, build_distance_splits, serialize_series


def _safe_name(value: str) -> str:
    return "".join(c for c in value if c.isalnum() or c in "-_")[:100]


def _extract_fit(raw: bytes) -> bytes:
    bio = io.BytesIO(raw)
    if zipfile.is_zipfile(bio):
        with zipfile.ZipFile(bio) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".fit")]
            if not names:
                raise ValueError("Garmin original download contains no FIT file")
            return archive.read(names[0])
    return raw


def _semicircles_to_degrees(value: Any) -> Any:
    if isinstance(value, (int, float)) and abs(value) > 180:
        return float(value) * (180.0 / 2**31)
    return value


def _parse_fit(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    records: list[dict[str, Any]] = []
    session: dict[str, Any] = {}
    laps: list[dict[str, Any]] = []
    sets: list[dict[str, Any]] = []
    lengths: list[dict[str, Any]] = []
    with fitdecode.FitReader(str(path)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.records.FitDataMessage):
                continue
            values: dict[str, Any] = {}
            for field in frame.fields:
                value = field.value
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif field.name in {"position_lat", "position_long"}:
                    value = _semicircles_to_degrees(value)
                if isinstance(value, (str, int, float, bool)) or value is None:
                    values[field.name] = value
            if frame.name == "record":
                records.append(values)
            elif frame.name == "session":
                session.update(values)
            elif frame.name == "lap":
                laps.append(values)
            elif frame.name == "set":
                sets.append(values)
            elif frame.name == "length":
                lengths.append(values)
    if laps:
        session["_laps"] = laps
    if sets:
        session["_sets"] = sets
    if lengths:
        session["_lengths"] = lengths
    df = pd.DataFrame.from_records(records)
    return df, session


def _to_numeric(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[name], errors="coerce")


def _pct_change(first: float | None, second: float | None) -> float | None:
    if first is None or second is None or not first:
        return None
    return (second / first - 1.0) * 100.0


def _mean(series: pd.Series) -> float | None:
    series = series.dropna()
    return float(series.mean()) if len(series) else None


def _analytics(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"quality": {"overall": 0.0}, "metrics": {}}
    hr = _to_numeric(df, "heart_rate")
    speed = _to_numeric(df, "enhanced_speed")
    if speed.empty or speed.dropna().empty:
        speed = _to_numeric(df, "speed")
    power = _to_numeric(df, "power")
    cadence = _to_numeric(df, "cadence")
    distance = _to_numeric(df, "distance")
    n = len(df)
    split_idx = n // 2
    if len(distance.dropna()) >= max(10, n // 3):
        max_distance = distance.max()
        split_idx_candidates = np.where(distance.to_numpy(dtype=float, na_value=np.nan) >= max_distance / 2)[0]
        if len(split_idx_candidates):
            split_idx = int(split_idx_candidates[0])
    split_idx = max(1, min(n - 1, split_idx)) if n > 1 else 1

    def halves(series: pd.Series) -> tuple[float | None, float | None]:
        if series.empty:
            return None, None
        return _mean(series.iloc[:split_idx]), _mean(series.iloc[split_idx:])

    hr1, hr2 = halves(hr); sp1, sp2 = halves(speed); pw1, pw2 = halves(power); ca1, ca2 = halves(cadence)
    hr_drift = _pct_change(hr1, hr2)
    pace1 = 1000.0 / sp1 if sp1 and sp1 > 0 else None
    pace2 = 1000.0 / sp2 if sp2 and sp2 > 0 else None
    pace_drift = _pct_change(pace1, pace2)
    power_drift = _pct_change(pw1, pw2)
    cadence_drift = _pct_change(ca1, ca2)
    # Speed-to-HR efficiency; positive decoupling means second-half efficiency fell.
    aerobic_decoupling = None
    if sp1 and sp2 and hr1 and hr2:
        eff1, eff2 = sp1 / hr1, sp2 / hr2
        aerobic_decoupling = (eff1 / eff2 - 1.0) * 100.0 if eff2 else None
    pace_consistency = None
    valid_speed = speed[(speed > 0) & speed.notna()]
    if len(valid_speed) >= 10:
        pace = 1000.0 / valid_speed
        cv = float(pace.std(ddof=0) / pace.mean()) if pace.mean() else 1.0
        pace_consistency = max(0.0, min(100.0, 100.0 - cv * 100.0))
    coverages = {}
    for label, series in {"heart_rate": hr, "speed": speed, "power": power, "cadence": cadence}.items():
        coverages[label] = round(float(series.notna().sum()) / n * 100.0, 1) if n and not series.empty else 0.0
    lat = _to_numeric(df, "position_lat"); lon = _to_numeric(df, "position_long")
    gps_cov = min(float(lat.notna().sum()), float(lon.notna().sum())) / n * 100 if n and not lat.empty and not lon.empty else 0.0
    coverages["gps"] = round(gps_cov, 1)
    available = [v for k, v in coverages.items() if k in {"heart_rate", "speed", "gps"} and v > 0]
    quality_score = round(sum(available) / len(available), 1) if available else 0.0
    return {
        "quality": {"overall": quality_score, "coverage": coverages, "records": n},
        "metrics": {
            "hr_drift": hr_drift, "pace_drift": pace_drift, "power_drift": power_drift,
            "aerobic_decoupling": aerobic_decoupling, "pace_consistency": pace_consistency,
            "cadence_drift": cadence_drift,
        },
    }


async def download_and_analyze_fit(db: AsyncSession, user: User, activity: Activity, connection: GarminConnection, analyze: bool = True) -> dict[str, Any]:
    gateway, raw_client = await gateway_from_connection(connection)
    raw = await asyncio.to_thread(gateway.download_activity_fit, activity.garmin_activity_id)
    fit_bytes = _extract_fit(raw)
    year = activity.started_at.year if activity.started_at else datetime.now().year
    fit_dir = settings.fit_dir / str(user.id) / str(year)
    parquet_dir = settings.parquet_dir / str(user.id) / str(year)
    fit_dir.mkdir(parents=True, exist_ok=True); parquet_dir.mkdir(parents=True, exist_ok=True)
    fit_path = fit_dir / f"{_safe_name(str(activity.garmin_activity_id))}.fit"
    fit_path.write_bytes(fit_bytes)
    digest = hashlib.sha256(fit_bytes).hexdigest()
    row = await db.scalar(select(FitFile).where(FitFile.activity_id == activity.id))
    if not row:
        row = FitFile(user_id=user.id, activity_id=activity.id, original_path=str(fit_path), file_size=len(fit_bytes), sha256=digest)
        db.add(row)
    else:
        row.original_path = str(fit_path); row.file_size = len(fit_bytes); row.sha256 = digest
    row.status = "downloaded"
    activity.fit_status = "downloaded"
    result: dict[str, Any] = {"activity_id": str(activity.id), "fit": str(fit_path), "status": "downloaded"}
    if analyze:
        df, session = await asyncio.to_thread(_parse_fit, fit_path)
        parquet_path = parquet_dir / f"{activity.garmin_activity_id}.parquet"
        if not df.empty:
            await asyncio.to_thread(df.to_parquet, parquet_path, index=False)
            row.parquet_path = str(parquet_path)
        analysis = await asyncio.to_thread(_analytics, df)
        row.parsed_at = datetime.now(timezone.utc); row.parser_name = "fitdecode"; row.parser_version = getattr(fitdecode, "__version__", "unknown")
        row.status = "parsed"; row.data_quality = analysis["quality"]
        metric = await db.scalar(select(ActivityMetric).where(ActivityMetric.activity_id == activity.id))
        if not metric:
            metric = ActivityMetric(user_id=user.id, activity_id=activity.id); db.add(metric)
        metrics = analysis["metrics"]
        metric.hr_drift = metrics.get("hr_drift"); metric.pace_drift = metrics.get("pace_drift")
        metric.power_drift = metrics.get("power_drift"); metric.aerobic_decoupling = metrics.get("aerobic_decoupling")
        metric.pace_consistency = metrics.get("pace_consistency"); metric.cadence_drift = metrics.get("cadence_drift")
        metric.data_quality_score = analysis["quality"].get("overall"); metric.details = {"session": session, "quality": analysis["quality"]}
        activity.fit_status = "parsed"
        result = {"activity_id": str(activity.id), "fit": str(fit_path), "parquet": str(parquet_path) if not df.empty else None, **analysis}
    connection.token_ciphertext = serialize_refreshed_token(raw_client)
    await db.commit()
    return result


def load_activity_series(fit_file: FitFile, limit: int = 5000) -> list[dict[str, Any]]:
    if not fit_file.parquet_path or not Path(fit_file.parquet_path).exists():
        return []
    df = pd.read_parquet(fit_file.parquet_path)
    return serialize_series(df, limit=limit)


def load_activity_detail(fit_file: FitFile, sport_type: str | None = None) -> dict[str, Any]:
    if not fit_file.parquet_path or not Path(fit_file.parquet_path).exists():
        return {"stats": None, "splits": []}
    df = pd.read_parquet(fit_file.parquet_path)
    return {
        "stats": build_activity_stats(df, sport_type=sport_type),
        "splits": build_distance_splits(df, sport_type=sport_type),
    }
