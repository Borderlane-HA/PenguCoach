from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


RUN_KEYS = ("running", "trail_running", "treadmill_running", "track_running", "walking", "hiking")
SWIM_KEYS = ("swimming", "lap_swimming", "open_water_swimming")
BIKE_KEYS = ("cycling", "road_biking", "mountain_biking", "gravel_cycling", "e_bike_fitness", "indoor_cycling")
STRENGTH_KEYS = ("strength_training", "cardio_training", "fitness_equipment", "hiit")


def sport_family(sport_type: str | None) -> str:
    value = (sport_type or "").lower()
    if any(key in value for key in SWIM_KEYS):
        return "swim"
    if any(key in value for key in RUN_KEYS):
        return "run"
    if any(key in value for key in BIKE_KEYS):
        return "bike"
    if any(key in value for key in STRENGTH_KEYS):
        return "strength"
    return "other"


def _numeric(df: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in df.columns:
            series = pd.to_numeric(df[name], errors="coerce")
            if series.notna().any():
                return series.astype(float)
    return pd.Series(np.nan, index=df.index, dtype=float)


def _valid(series: pd.Series, minimum: float | None = None, maximum: float | None = None) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if minimum is not None:
        out = out.where(out >= minimum)
    if maximum is not None:
        out = out.where(out <= maximum)
    return out


def _mean(series: pd.Series) -> float | None:
    values = series.dropna()
    return float(values.mean()) if len(values) else None


def _min(series: pd.Series) -> float | None:
    values = series.dropna()
    return float(values.min()) if len(values) else None


def _max(series: pd.Series) -> float | None:
    values = series.dropna()
    return float(values.max()) if len(values) else None


def _percentile(series: pd.Series, q: float) -> float | None:
    values = series.dropna()
    return float(values.quantile(q)) if len(values) else None


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None and np.isfinite(value) else None


def _timestamps(df: pd.DataFrame) -> pd.Series:
    if "timestamp" not in df.columns:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    return pd.to_datetime(df["timestamp"], errors="coerce", utc=True)


def _elapsed_seconds(df: pd.DataFrame) -> pd.Series:
    ts = _timestamps(df)
    valid = ts.dropna()
    if len(valid):
        first = valid.iloc[0]
        return (ts - first).dt.total_seconds()
    return pd.Series(np.arange(len(df), dtype=float), index=df.index)


def _altitude(df: pd.DataFrame) -> pd.Series:
    return _numeric(df, "enhanced_altitude", "altitude")


def _speed(df: pd.DataFrame) -> pd.Series:
    return _numeric(df, "enhanced_speed", "speed")


def _grade(distance: pd.Series, altitude: pd.Series) -> pd.Series:
    # FIT altitude can be noisy. A short rolling median before calculating grade
    # gives a much more useful training view than point-to-point spikes.
    if distance.notna().sum() < 3 or altitude.notna().sum() < 3:
        return pd.Series(np.nan, index=distance.index, dtype=float)
    smooth_alt = altitude.interpolate(limit_direction="both").rolling(7, center=True, min_periods=1).median()
    smooth_dist = distance.interpolate(limit_direction="both")
    dd = smooth_dist.diff()
    da = smooth_alt.diff()
    grade = (da / dd.where(dd.abs() >= 2.0)) * 100.0
    grade = grade.replace([np.inf, -np.inf], np.nan).clip(-35, 35)
    return grade.rolling(9, center=True, min_periods=1).median()


def _elevation_gain_loss(altitude: pd.Series) -> tuple[float | None, float | None]:
    values = altitude.dropna()
    if len(values) < 2:
        return None, None
    smooth = altitude.interpolate(limit_direction="both").rolling(7, center=True, min_periods=1).median()
    delta = smooth.diff()
    # Ignore tiny barometric/GPS noise while retaining meaningful climbing.
    delta = delta.where(delta.abs() >= 0.25, 0.0)
    gain = float(delta.clip(lower=0).sum())
    loss = float((-delta.clip(upper=0)).sum())
    return gain, loss


def _normalized_power(power: pd.Series) -> float | None:
    values = _valid(power, 0)
    if values.notna().sum() < 30:
        return None
    # FIT records are normally ~1 Hz. The 30-s rolling fourth-power method is
    # the conventional deterministic approximation used here.
    rolling = values.interpolate(limit_direction="both").rolling(30, min_periods=15).mean().dropna()
    if len(rolling) == 0:
        return None
    return float((rolling.pow(4).mean()) ** 0.25)


def enrich_series_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    distance = _numeric(out, "distance")
    speed = _speed(out)
    altitude = _altitude(out)
    out["elapsed_s"] = _elapsed_seconds(out)
    out["distance_km"] = distance / 1000.0
    out["speed_kmh"] = speed * 3.6
    out["pace_s_per_km"] = np.where(speed > 0.2, 1000.0 / speed, np.nan)
    out["altitude_m"] = altitude
    out["grade_pct"] = _grade(distance, altitude)
    return out


def _channel(values: pd.Series, *, minimum: float | None = None, maximum: float | None = None, digits: int = 1) -> dict[str, float | None]:
    clean = _valid(values, minimum, maximum)
    return {
        "min": _round(_min(clean), digits),
        "avg": _round(_mean(clean), digits),
        "max": _round(_max(clean), digits),
    }


def build_activity_stats(df: pd.DataFrame, sport_type: str | None = None) -> dict[str, Any]:
    if df.empty:
        return {"sport_family": sport_family(sport_type), "records": 0, "channels": {}}

    enriched = enrich_series_frame(df)
    hr = _numeric(enriched, "heart_rate")
    speed = _speed(enriched)
    power = _numeric(enriched, "power")
    cadence = _numeric(enriched, "cadence")
    altitude = _altitude(enriched)
    temperature = _numeric(enriched, "temperature")
    distance = _numeric(enriched, "distance")
    grade = _numeric(enriched, "grade_pct")
    elapsed = _numeric(enriched, "elapsed_s")

    gain, loss = _elevation_gain_loss(altitude)
    speed_kmh = speed * 3.6
    pace = pd.Series(np.where(speed > 0.2, 1000.0 / speed, np.nan), index=df.index, dtype=float)

    coverage: dict[str, float] = {}
    for name, series in {
        "heart_rate": hr,
        "speed": speed,
        "power": power,
        "cadence": cadence,
        "altitude": altitude,
        "temperature": temperature,
        "gps": _numeric(enriched, "position_lat"),
    }.items():
        coverage[name] = round(float(series.notna().sum()) / len(df) * 100.0, 1) if len(df) else 0.0

    duration = _max(elapsed)
    max_distance = _max(distance)
    return {
        "sport_family": sport_family(sport_type),
        "records": len(df),
        "duration_seconds": _round(duration, 0),
        "distance_m": _round(max_distance, 1),
        "heart_rate": _channel(hr, minimum=30, maximum=250, digits=0),
        "speed_kmh": {
            "avg": _round(_mean(_valid(speed_kmh, 0.1)), 1),
            "max": _round(_max(_valid(speed_kmh, 0.1)), 1),
            "p99": _round(_percentile(_valid(speed_kmh, 0.1), 0.99), 1),
        },
        "pace_s_per_km": {
            "avg": _round(_mean(_valid(pace, 30, 7200)), 1),
            "best": _round(_min(_valid(pace, 30, 7200)), 1),
        },
        "power_w": {
            "avg": _round(_mean(_valid(power, 0)), 0),
            "max": _round(_max(_valid(power, 0)), 0),
            "normalized": _round(_normalized_power(power), 0),
            "source": "fit" if power.notna().any() else None,
        },
        "cadence": _channel(cadence, minimum=0, maximum=300, digits=0),
        "elevation": {
            "min_m": _round(_min(altitude), 1),
            "max_m": _round(_max(altitude), 1),
            "gain_m": _round(gain, 0),
            "loss_m": _round(loss, 0),
            "steepest_climb_pct": _round(_percentile(_valid(grade.where(grade > 0), 0, 35), 0.99), 1),
            "steepest_descent_pct": _round(_percentile(_valid(grade.where(grade < 0), -35, 0), 0.01), 1),
        },
        "temperature_c": _channel(temperature, minimum=-80, maximum=80, digits=1),
        "coverage": coverage,
    }


def _split_step(sport_type: str | None) -> float:
    family = sport_family(sport_type)
    return 100.0 if family == "swim" else 1000.0


def build_distance_splits(df: pd.DataFrame, sport_type: str | None = None, max_splits: int = 250) -> list[dict[str, Any]]:
    if df.empty:
        return []
    enriched = enrich_series_frame(df)
    distance = _numeric(enriched, "distance")
    if distance.notna().sum() < 2:
        return []
    total = _max(distance) or 0.0
    if total <= 0:
        return []
    step = _split_step(sport_type)
    split_count = min(max_splits, max(1, int(np.ceil(total / step))))
    rows: list[dict[str, Any]] = []
    for idx in range(split_count):
        start = idx * step
        end = min(total, (idx + 1) * step)
        mask = (distance >= start) & (distance <= end)
        part = enriched.loc[mask]
        if len(part) < 2:
            continue
        part_distance = _numeric(part, "distance")
        elapsed = _numeric(part, "elapsed_s")
        speed = _speed(part)
        hr = _numeric(part, "heart_rate")
        power = _numeric(part, "power")
        cadence = _numeric(part, "cadence")
        altitude = _altitude(part)
        grade = _numeric(part, "grade_pct")
        gain, loss = _elevation_gain_loss(altitude)
        elapsed_s = (_max(elapsed) or 0) - (_min(elapsed) or 0)
        dist_m = (_max(part_distance) or end) - (_min(part_distance) or start)
        rows.append({
            "index": idx + 1,
            "label": f"{idx + 1}" if step >= 1000 else f"{idx + 1} × 100 m",
            "start_m": _round(start, 1),
            "end_m": _round(end, 1),
            "distance_m": _round(dist_m, 1),
            "elapsed_s": _round(elapsed_s, 1),
            "pace_s_per_km": _round(elapsed_s / (dist_m / 1000.0), 1) if dist_m > 1 and elapsed_s > 0 else None,
            "avg_speed_kmh": _round(_mean(_valid(speed * 3.6, 0.1)), 1),
            "avg_hr": _round(_mean(_valid(hr, 30, 250)), 0),
            "max_hr": _round(_max(_valid(hr, 30, 250)), 0),
            "avg_power": _round(_mean(_valid(power, 0)), 0),
            "max_power": _round(_max(_valid(power, 0)), 0),
            "avg_cadence": _round(_mean(_valid(cadence, 0, 300)), 0),
            "ascent_m": _round(gain, 0),
            "descent_m": _round(loss, 0),
            "avg_grade_pct": _round(_mean(_valid(grade, -35, 35)), 1),
        })
    return rows


def serialize_series(df: pd.DataFrame, limit: int = 5000) -> list[dict[str, Any]]:
    if df.empty:
        return []
    enriched = enrich_series_frame(df)
    wanted = [
        "timestamp", "elapsed_s", "distance", "distance_km", "heart_rate",
        "enhanced_speed", "speed", "speed_kmh", "pace_s_per_km", "power",
        "cadence", "enhanced_altitude", "altitude", "altitude_m", "grade_pct",
        "position_lat", "position_long", "temperature", "respiration_rate",
        "vertical_oscillation", "stance_time", "vertical_ratio", "step_length",
    ]
    columns = [c for c in wanted if c in enriched.columns]
    out = enriched[columns].copy()
    if len(out) > limit:
        indices = np.linspace(0, len(out) - 1, limit).astype(int)
        out = out.iloc[indices]
    if "timestamp" in out.columns:
        ts = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
        out["timestamp"] = ts.map(lambda v: v.isoformat() if pd.notna(v) else None)
    out = out.replace({np.nan: None, pd.NaT: None})
    return out.to_dict(orient="records")


GARMIN_EXTRA_FIELDS: dict[str, tuple[str, ...]] = {
    "elapsed_duration_s": ("elapsedDuration",),
    "max_speed_mps": ("maxSpeed",),
    "elevation_loss_m": ("elevationLoss",),
    "min_elevation_m": ("minElevation",),
    "max_elevation_m": ("maxElevation",),
    "max_power_w": ("maxPower",),
    "normalized_power_w": ("normPower", "normalizedPower"),
    "max_cadence": ("maxBikingCadenceInRevPerMinute", "maxRunningCadenceInStepsPerMinute"),
    "avg_stride_length_cm": ("avgStrideLength",),
    "avg_vertical_oscillation_cm": ("avgVerticalOscillation",),
    "avg_vertical_ratio_pct": ("avgVerticalRatio",),
    "avg_ground_contact_time_ms": ("avgGroundContactTime",),
    "avg_ground_contact_balance_pct": ("avgGroundContactBalance",),
    "avg_swolf": ("avgSwolf",),
    "avg_strokes": ("avgStrokeCadence", "averageSwimCadence"),
    "pool_length_m": ("poolLength",),
    "moderate_intensity_minutes": ("moderateIntensityMinutes",),
    "vigorous_intensity_minutes": ("vigorousIntensityMinutes",),
}


def selected_garmin_extras(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    result: dict[str, Any] = {}
    for output_name, keys in GARMIN_EXTRA_FIELDS.items():
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)):
                result[output_name] = value
                break
    return result
