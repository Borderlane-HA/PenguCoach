"""SparkyFitness 1.8 workout telemetry, separate from ExerciseSession_raw_data.

Source contract: genericHealthRoutes.ts and ExerciseEntryGpsPoints.zod.ts at
CodeWithCJ/SparkyFitness v1.8.0. Never synthesize samples from summary values.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from urllib.parse import quote

import pandas as pd

from pengucoach.sparkyfitness.client import SparkyFitnessError

KEY = "_workout_telemetry"
MAX_POINTS = 100_000


async def enrich_telemetry(client, item: dict, previous: dict | None = None, *, refresh=True):
    old = (previous or {}).get(KEY)
    if not refresh and isinstance(old, dict) and old.get("version") == 1 and all(
        x in {"available", "empty"} for x in old.get("status", {}).values()
    ) and len(old.get("status", {})) == 3:
        return {**item, KEY: old}, 0
    identifier = item.get("id") or item.get("exercise_entry_id")
    if not identifier:
        return item, 0
    data = {**(old if isinstance(old, dict) else {}), "version": 1, "status": {}}
    disabled = getattr(client, "_pengucoach_telemetry_disabled", {})
    requests = 0
    for kind, endpoint in (("gps", "workout-gps"), ("laps", "workout-laps"), ("hr_zones", "workout-hr-zones")):
        if kind in disabled:
            data["status"][kind] = disabled[kind]
            continue
        try:
            requests += 1
            response = await client.request(f"/generic-health/{endpoint}/{quote(str(identifier), safe='')}")
            value = response.get("data") if isinstance(response, dict) else response
            if kind == "gps":
                points = value.get("points") if isinstance(value, dict) else value
                value = [p for p in (points or []) if isinstance(p, dict)][:MAX_POINTS] if isinstance(points, list) else []
            else:
                value = [p for p in value if isinstance(p, dict)][:1000] if isinstance(value, list) else []
            data[kind] = value
            data["status"][kind] = "available" if value else "empty"
        except SparkyFitnessError as exc:
            state = "permission_denied" if exc.status_code in {401, 403} else "unsupported" if exc.status_code in {404, 405} else "unavailable"
            data["status"][kind] = state
            if state != "unavailable":
                disabled[kind] = state
    client._pengucoach_telemetry_disabled = disabled
    return {**item, KEY: data}, requests


def telemetry(raw: dict | None) -> dict:
    value = ((raw or {}).get("sparkyfitness") or {}).get(KEY)
    return value if isinstance(value, dict) else {}


def number(value, minimum=None, maximum=None):
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)) or str(value).strip() == "":
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and (minimum is None or value >= minimum) and (maximum is None or value <= maximum) else None
    except ValueError:
        return None


def frame(raw: dict | None) -> pd.DataFrame:
    fields = {
        "heart_rate": (("hr", "heart_rate_bpm"), 1, 300),
        "speed": (("speed", "speed_mps"), 0, 100),
        "altitude": (("alt", "altitude_meters"), -500, 10000),
        "distance": (("dist", "distance_meters"), 0, None),
        "power": (("power", "power_watts"), 0, 5000),
        "cadence": (("cad", "cadence"), 0, 300),
        "temperature": (("temp", "temperature_celsius"), -80, 80),
        "respiration_rate": (("resp", "respiration_rate_brpm"), 1, 150),
        "stance_time": (("gct", "ground_contact_time_ms"), 0, 3000),
        "vertical_oscillation": (("vo", "vertical_oscillation_mm"), 0, 1000),
        "step_length": (("stride", "stride_length_cm"), 0, 1000),
    }
    records = []
    for point in telemetry(raw).get("gps", [])[:MAX_POINTS]:
        if not isinstance(point, dict):
            continue
        stamp = point.get("t", point.get("timestamp"))
        try:
            stamp = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                continue  # No invented timezone or time axis.
            stamp = stamp.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        row = {"timestamp": stamp}
        lat = number(point.get("lat", point.get("latitude")), -90, 90)
        lon = number(point.get("lon", point.get("longitude")), -180, 180)
        if lat is not None and lon is not None:
            row.update(position_lat=lat, position_long=lon)
        for output, (aliases, minimum, maximum) in fields.items():
            value = next((v for k in aliases if (v := number(point.get(k), minimum, maximum)) is not None), None)
            if value is not None:
                row[output] = value
        if len(row) > 1:
            records.append(row)
    if not records:
        return pd.DataFrame()
    out = pd.DataFrame(records).sort_values("timestamp", kind="stable").drop_duplicates("timestamp", keep="first").reset_index(drop=True)
    # SparkyFitness stores Douglas-Peucker simplified tracks: on straight roads
    # fixes can be minutes apart. Splitting on time alone dropped those stretches
    # from the map, so only impossible jumps start a new segment.
    from pengucoach.fit.track import add_distance_speed, segment_ids
    out["track_segment"] = segment_ids(out)
    # Phone and Health Connect tracks often have positions but no cumulative
    # distance; without it there are no splits and no distance axis.
    return add_distance_speed(out, smooth=False)


def laps(raw):
    fields = {"total_distance": "distance_meters", "total_elapsed_time": "duration_seconds",
        "total_timer_time": "moving_time_seconds", "avg_heart_rate": "avg_heart_rate", "max_heart_rate": "max_heart_rate",
        "avg_speed": "avg_speed_mps", "avg_power": "avg_power_watts", "avg_cadence": "avg_cadence",
        "total_ascent": "elevation_gain_meters", "total_descent": "elevation_loss_meters",
        "avg_respiration_rate": "avg_respiration_brpm"}
    values = [r for r in telemetry(raw).get("laps", []) if isinstance(r, dict)]
    result = []
    for row in sorted(values, key=lambda r: number(r.get("lap_index")) or 0):
        result.append({out: number(row.get(key)) for out, key in fields.items()})
    return result


def zones(raw):
    # Curate the numeric provider values; never infer zone thresholds.
    fields = {"zone_number": "zone_index", "min_bpm": "zone_lower_bpm", "max_bpm": "zone_upper_bpm", "duration_seconds": "seconds_in_zone"}
    return [{k: number(row.get(v)) for k, v in fields.items()} for row in telemetry(raw).get("hr_zones", []) if isinstance(row, dict)]
