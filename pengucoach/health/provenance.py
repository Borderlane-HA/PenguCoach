from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

BODY_FIELDS = (
    "weight_kg", "height_cm", "bmi", "body_fat_percent",
    "body_water_percent", "muscle_mass_kg", "bone_mass_kg",
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def source(raw: dict | None) -> str:
    data = raw or {}
    explicit = data.get("source")
    if explicit:
        return "manual" if explicit == "manual_body" else str(explicit)
    values = set((data.get("_metric_sources") or {}).values())
    if values:
        return "+".join(sorted(str(v) for v in values if v))
    namespaces = {"sparkyfitness", "withings", "withings_activity", "withings_measurements"}
    found = {"sparkyfitness"} if "sparkyfitness" in data else set()
    if any(k.startswith("withings") for k in data):
        found.add("withings")  # Historical measurements retain their actual provenance.
    if any(not k.startswith("_") and k not in namespaces for k in data):
        found.add("garmin")
    return "+".join(sorted(found)) if found else "unknown"


def metric_source(raw: dict | None, field: str, default: str | None = None) -> str:
    return (raw or {}).get("_metric_sources", {}).get(field) or default or source(raw)


def body_snapshot(rows: list, *, as_of: datetime | None = None) -> dict[str, Any] | None:
    """Select each metric by measurement time, never by provider or import order."""
    cutoff = utc(as_of or datetime.now(timezone.utc))
    def measured(row, field):
        stamp = (row.raw or {}).get("_metric_times", {}).get(field)
        if stamp:
            try:
                return utc(datetime.fromisoformat(stamp))
            except (ValueError, TypeError):
                pass
        value = utc(row.measured_at)
        # Alpha.28-37 used an artificial 23:59:59 for manual date-only entries.
        if (row.raw or {}).get("source") == "manual_body" and (value.hour, value.minute, value.second) == (23, 59, 59):
            value = value.replace(hour=0, minute=0, second=0)
        return value
    eligible = [row for row in rows if row.measured_at]
    result: dict[str, Any] = {"sources": {}, "measured_at_by_metric": {}}
    # Stable tie-break only for truly simultaneous measurements.
    priority = {"manual": 3, "garmin": 2, "sparkyfitness": 1}
    for field in BODY_FIELDS:
        candidates = [r for r in eligible if getattr(r, field, None) is not None and measured(r, field) <= cutoff]
        if not candidates:
            continue
        row = max(candidates, key=lambda r: (measured(r, field), priority.get(metric_source(r.raw, field), 0)))
        result[field] = getattr(row, field)
        result["sources"][field] = metric_source(row.raw, field)
        result["measured_at_by_metric"][field] = measured(row, field)
    if not result["sources"]:
        return None
    if result.get("weight_kg") and result.get("height_cm"):
        result["bmi"] = round(result["weight_kg"] / (result["height_cm"] / 100) ** 2, 2)
        result["sources"]["bmi"] = "pengucoach"
        result["measured_at_by_metric"]["bmi"] = max(result["measured_at_by_metric"][k] for k in ("weight_kg", "height_cm"))
        result["bmi_inputs"] = {k: {"source": result["sources"][k], "measured_at": result["measured_at_by_metric"][k]} for k in ("weight_kg", "height_cm")}
    result["measured_at"] = max(result["measured_at_by_metric"].values())
    return result


def merge_metric(row, field: str, value: Any, provider: str, observed_at: datetime | None = None) -> bool:
    """Merge a non-null value. Dated observations win; undated overlaps use a stable source tie-break.

    Same-source corrections refresh values. An older timestamp never replaces
    a newer observation. Sync time is deliberately not a measurement timestamp.
    """
    if value is None:
        return False
    if isinstance(value, (int, float)):
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            return False
        if field in {"stress_avg", "body_battery_high", "body_battery_low", "training_readiness", "body_fat_percent", "body_water_percent", "spo2_avg", "avg_spo2", "min_spo2"} and value > 100:
            return False
        if field in {"steps", "resting_hr", "min_hr", "max_hr", "hydration_ml", "hydration_goal_ml", "body_battery_high", "body_battery_low", "intensity_moderate", "intensity_vigorous", "duration_seconds", "deep_seconds", "light_seconds", "rem_seconds", "awake_seconds"}:
            value = int(round(value))
    raw = dict(row.raw or {})
    sources = dict(raw.get("_metric_sources") or {})
    times = dict(raw.get("_metric_times") or {})
    old_source = metric_source(raw, field)
    previous = times.get(field)
    old_time = None
    if previous:
        try:
            old_time = utc(datetime.fromisoformat(previous))
        except (ValueError, TypeError):
            pass
    stamp = utc(observed_at) if observed_at else None
    current = getattr(row, field, None)
    if current is not None:
        if old_time and (stamp is None or stamp < old_time):
            return False
        if old_source != provider and (stamp is None or stamp == old_time):
            priority = {"manual": 3, "garmin": 2, "sparkyfitness": 1}
            if priority.get(provider, 0) < priority.get(old_source, 0):
                return False
    changed = current != value or old_source != provider
    setattr(row, field, value)
    sources[field] = provider
    if stamp:
        times[field] = stamp.isoformat()
    raw.update(_metric_sources=sources, _metric_times=times)
    row.raw = raw
    return changed
