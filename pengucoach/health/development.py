from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, ActivityMetric, BodyMeasurement, DailyHealth, HrvDaily, User
from pengucoach.health.provenance import source


RUN_WORDS = ("run", "jog", "lauf")
BIKE_WORDS = ("cycl", "bike", "biking", "rad")


def sport_family(value: str | None) -> str:
    text = str(value or "").casefold()
    if any(word in text for word in RUN_WORDS):
        return "running"
    if any(word in text for word in BIKE_WORDS):
        return "cycling"
    if any(word in text for word in ("strength", "weight", "gym", "kraft")):
        return "strength"
    if any(word in text for word in ("mobility", "yoga", "stretch", "pilates")):
        return "mobility"
    if "swim" in text or "schwimm" in text:
        return "swimming"
    if "walk" in text or "hike" in text or "wander" in text:
        return "walking"
    return "other"


def _local_day(value: datetime | None, user: User) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(user.timezone)).date()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _mean(values: Iterable[float | int | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _pct_change(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old == 0:
        return None
    return (new / old - 1.0) * 100.0


def _trend(change: float | None, *, threshold: float = 2.0, inverse: bool = False) -> str:
    if change is None:
        return "unknown"
    effective = -change if inverse else change
    if effective > threshold:
        return "rising"
    if effective < -threshold:
        return "falling"
    return "stable"


def _confidence(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.62:
        return "medium"
    return "low"


def _first_second(values: list[tuple[date, float]]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    values = sorted(values, key=lambda x: x[0])
    # A third-vs-third comparison is less jumpy than first/last single values.
    n = max(1, len(values) // 3)
    return _mean(v for _, v in values[:n]), _mean(v for _, v in values[-n:])


def _bucket_mode(span_days: int | None) -> str:
    if span_days is None or span_days > 240:
        return "month"
    if span_days > 45:
        return "week"
    return "day"


def _bucket_start(day: date, mode: str) -> date:
    if mode == "month":
        return day.replace(day=1)
    if mode == "week":
        return day - timedelta(days=day.weekday())
    return day


def _bucket_label(day: date, mode: str) -> str:
    if mode == "month":
        return day.strftime("%Y-%m")
    if mode == "week":
        return f"KW {day.isocalendar().week:02d}"
    return day.isoformat()


def imported_vo2_history(activities: list[Activity], health: list[DailyHealth], user: User) -> dict[str, list[dict[str, Any]]]:
    """Merge provider VO2 estimates without confusing them with PenguCoach estimates.

    Daily VO2 (for example Apple Health/SparkyFitness in the future) is treated as
    running/general cardio fitness. Activity summaries retain the sport-specific
    Garmin value. When both exist on the same day, the activity-specific value wins.
    """
    running_by_day: dict[date, dict[str, Any]] = {}
    cycling: list[dict[str, Any]] = []
    for row in health:
        if row.vo2max_running is None:
            continue
        running_by_day[row.date] = {
            "date": row.date.isoformat(),
            "value": round(float(row.vo2max_running), 2),
            "source": source(row.raw),
            "measurement_kind": "imported",
        }
    for activity in activities:
        if activity.vo2max is None or activity.started_at is None:
            continue
        day = _local_day(activity.started_at, user)
        if day is None:
            continue
        family = sport_family(activity.sport_type)
        point = {
            "date": day.isoformat(),
            "value": round(float(activity.vo2max), 2),
            "activity_id": str(activity.id),
            "source": source(activity.raw),
            "measurement_kind": "imported",
        }
        if family == "running":
            running_by_day[day] = point
        elif family == "cycling":
            cycling.append(point)
    running = [running_by_day[key] for key in sorted(running_by_day)]
    cycling.sort(key=lambda item: item["date"])
    return {"running": running, "cycling": cycling}


def _resting_hr_for_day(day: date, health_by_day: dict[date, DailyHealth]) -> tuple[float | None, int]:
    vals: list[float] = []
    for delta in range(0, 28):
        row = health_by_day.get(day - timedelta(days=delta))
        if row and row.resting_hr is not None and 30 <= row.resting_hr <= 120:
            vals.append(float(row.resting_hr))
    return (float(median(vals)), len(vals)) if vals else (None, 0)


def _weight_for_day(day: date, bodies: list[BodyMeasurement], user: User) -> tuple[float | None, int | None]:
    best: tuple[date, float] | None = None
    for row in bodies:
        if row.weight_kg is None or row.measured_at is None:
            continue
        measured = _local_day(row.measured_at, user)
        if measured is None or measured > day:
            continue
        if best is None or measured > best[0]:
            best = (measured, float(row.weight_kg))
    if best is None:
        return None, None
    return best[1], (day - best[0]).days


def _observed_max_hr(activities: list[Activity], health: list[DailyHealth]) -> float | None:
    vals = [float(a.max_hr) for a in activities if a.max_hr is not None and 100 <= a.max_hr <= 240]
    vals.extend(float(row.max_hr) for row in health if row.max_hr is not None and 100 <= row.max_hr <= 240)
    return max(vals) if vals else None


def _zone_hr(snapshot: dict[str, Any], sport: str | None) -> tuple[float | None, float | None]:
    profiles = [row for row in snapshot.get("heart_rate", {}).get("profiles", []) if isinstance(row, dict)]
    if not profiles:
        return None, None
    family = {"running": "RUNNING", "cycling": "CYCLING", "swimming": "SWIMMING"}.get(sport_family(sport), "DEFAULT")
    by_sport = {str(row.get("sport") or "DEFAULT").strip().upper().replace("-", "_").replace(" ", "_"): row for row in profiles}
    profile = by_sport.get(family) or by_sport.get("DEFAULT") or profiles[0]
    return _finite(profile.get("max_hr_bpm")), _finite(profile.get("resting_hr_bpm"))


def _vo2_from_hrr(exercise_vo2: float, avg_hr: float, max_hr: float, resting_hr: float) -> tuple[float | None, float | None]:
    reserve = max_hr - resting_hr
    if reserve <= 20:
        return None, None
    fraction = (avg_hr - resting_hr) / reserve
    # Very light sessions amplify noise; near-maximal averages are rarely steady-state.
    if not 0.55 <= fraction <= 0.92:
        return None, fraction
    # %HR reserve tracks %VO2 reserve more closely than raw %VO2max.
    estimate = 3.5 + (exercise_vo2 - 3.5) / fraction
    if not 14 <= estimate <= 90:
        return None, fraction
    return estimate, fraction


def estimate_vo2_history(
    activities: list[Activity],
    health: list[DailyHealth],
    bodies: list[BodyMeasurement],
    metrics: dict[Any, ActivityMetric],
    zones: dict[str, Any],
    user: User,
) -> dict[str, list[dict[str, Any]]]:
    """Conservative, clearly-labelled fallback estimates.

    Running: ACSM running oxygen-cost equation on relatively flat workouts,
    extrapolated through HR reserve -> VO2 reserve.
    Cycling: ACSM leg-cycle workload equation requires measured average power and
    body mass; speed-only cycling is intentionally rejected because wind/terrain
    dominate outdoor speed.
    """
    health_by_day = {row.date: row for row in health}
    observed_max = _observed_max_hr(activities, health)
    result: dict[str, list[dict[str, Any]]] = {"running": [], "cycling": []}

    for activity in activities:
        day = _local_day(activity.started_at, user)
        family = sport_family(activity.sport_type)
        if day is None or family not in result or activity.avg_hr is None:
            continue
        duration_min = float(activity.duration_seconds or 0) / 60.0
        if not 20 <= duration_min <= 150:
            continue
        avg_hr = float(activity.avg_hr)
        zone_max, zone_rest = _zone_hr(zones, activity.sport_type)
        resting_hr, rhr_days = _resting_hr_for_day(day, health_by_day)
        if zone_rest is not None:
            resting_hr = zone_rest
        max_hr = zone_max or observed_max
        if resting_hr is None or max_hr is None or not (30 <= resting_hr < avg_hr < max_hr <= 240):
            continue
        if max_hr - avg_hr < 10:
            continue
        metric = metrics.get(activity.id)
        data_quality = float(metric.data_quality_score) if metric and metric.data_quality_score is not None else None
        score = 0.40
        if zone_max is not None:
            score += 0.16
        if zone_rest is not None or rhr_days >= 7:
            score += 0.10
        if data_quality is not None and data_quality >= 80:
            score += 0.10

        method: str
        exercise_vo2: float | None = None
        indoor_cycle = False
        inputs: dict[str, Any] = {
            "avg_hr_bpm": round(avg_hr),
            "resting_hr_bpm": round(resting_hr),
            "max_hr_bpm": round(max_hr),
            "duration_min": round(duration_min, 1),
            "max_hr_source": "garmin_zones" if zone_max is not None else "observed_history",
        }

        if family == "running":
            speed = _finite(activity.avg_speed)
            if speed is None or not 2.2 <= speed <= 7.0:
                continue
            distance_km = float(activity.distance_m or 0) / 1000.0
            ascent_per_km = (float(activity.elevation_gain or 0) / distance_km) if distance_km > 1 else None
            # Total ascent cannot tell us net grade. Reject clearly hilly sessions
            # instead of pretending total ascent is a constant uphill slope.
            if ascent_per_km is not None and ascent_per_km > 25:
                continue
            speed_m_min = speed * 60.0
            exercise_vo2 = 0.2 * speed_m_min + 3.5
            method = "acsm_running_hrr"
            inputs.update({"speed_kmh": round(speed * 3.6, 2), "ascent_m_per_km": round(ascent_per_km, 1) if ascent_per_km is not None else None})
            if ascent_per_km is not None and ascent_per_km <= 10:
                score += 0.10
            elif ascent_per_km is None:
                score -= 0.04
        else:
            power = _finite(activity.avg_power)
            weight, weight_age_days = _weight_for_day(day, bodies, user)
            if power is None or weight is None or not 50 <= power <= 600 or not 30 <= weight <= 250:
                continue
            exercise_vo2 = 7.0 + 10.8 * power / weight
            method = "acsm_cycle_power_hrr"
            inputs.update({"avg_power_w": round(power), "weight_kg": round(weight, 1), "weight_age_days": weight_age_days})
            score += 0.08 if weight_age_days is not None and weight_age_days <= 30 else 0.02
            text = f"{activity.sport_type or ''} {activity.subsport_type or ''}".casefold()
            indoor_cycle = any(word in text for word in ("indoor", "trainer", "virtual"))
            if indoor_cycle:
                score += 0.08
            else:
                # Outdoor power is still useful, but the ACSM equation was made
                # for cycle ergometry, so input confidence stays below "high".
                score -= 0.03

        estimate, hrr_fraction = _vo2_from_hrr(exercise_vo2, avg_hr, max_hr, resting_hr) if exercise_vo2 is not None else (None, None)
        if estimate is None or hrr_fraction is None:
            continue
        if 0.65 <= hrr_fraction <= 0.88:
            score += 0.08
        if duration_min >= 30:
            score += 0.04
        confidence_cap = 0.92 if family == "running" else (0.86 if indoor_cycle else 0.74)
        score = max(0.0, min(score, confidence_cap))
        if score < 0.52:
            continue
        result[family].append({
            "date": day.isoformat(),
            "value": round(estimate, 1),
            "activity_id": str(activity.id),
            "source": "pengucoach_estimate",
            "measurement_kind": "estimated",
            "confidence": _confidence(score),
            "confidence_score": round(score, 2),
            "method": method,
            "hrr_fraction": round(hrr_fraction, 3),
            "inputs": inputs,
        })

    for rows in result.values():
        rows.sort(key=lambda item: item["date"])
    return result


def vo2_display_payload(imported: dict[str, list[dict[str, Any]]], estimated: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Choose provider values first; expose estimates only when provider VO2 is absent."""
    display: dict[str, list[dict[str, Any]]] = {}
    latest: dict[str, float | None] = {}
    latest_meta: dict[str, dict[str, Any] | None] = {}
    for sport in ("running", "cycling"):
        if imported.get(sport):
            display[sport] = imported[sport]
            latest[sport] = imported[sport][-1]["value"]
            latest_meta[sport] = imported[sport][-1]
        else:
            display[sport] = estimated.get(sport, [])
            summary = estimate_summary(estimated.get(sport, []))
            latest[sport] = summary["value"] if summary else None
            latest_meta[sport] = summary
    return {
        **display,
        "imported": imported,
        "estimated": estimated,
        "latest": latest,
        "latest_meta": latest_meta,
        "source": "provider_or_pengucoach_estimate",
        "estimates_are_measurements": False,
    }


def estimate_summary(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not points:
        return None
    latest_day = date.fromisoformat(points[-1]["date"])
    recent = [p for p in points if (latest_day - date.fromisoformat(p["date"])).days <= 42]
    recent = recent[-5:] or points[-5:]
    values = [float(p["value"]) for p in recent]
    score = _mean(float(p.get("confidence_score") or 0) for p in recent) or 0
    return {
        "value": round(float(median(values)), 1),
        "date": recent[-1]["date"],
        "source": "pengucoach_estimate",
        "measurement_kind": "estimated",
        "confidence": _confidence(score),
        "sample_count": len(recent),
    }


def _efficiency_series(activities: list[Activity], user: User, family: str, mode: str) -> dict[str, Any]:
    eligible: list[tuple[date, Activity]] = []
    for activity in activities:
        if sport_family(activity.sport_type) != family or activity.avg_hr is None:
            continue
        day = _local_day(activity.started_at, user)
        if day is None or not (90 <= activity.avg_hr <= 200) or (activity.duration_seconds or 0) < 20 * 60:
            continue
        if family == "running":
            if activity.avg_speed is None or activity.avg_speed <= 0:
                continue
            distance_km = float(activity.distance_m or 0) / 1000.0
            ascent_per_km = (float(activity.elevation_gain or 0) / distance_km) if distance_km > 1 else None
            if ascent_per_km is not None and ascent_per_km > 35:
                continue
        if family == "cycling" and activity.avg_power is None:
            continue
        eligible.append((day, activity))
    if len(eligible) < 3:
        return {"available": False, "sport": family, "points": []}
    ref = float(median([float(a.avg_hr) for _, a in eligible]))
    band = 7.0
    comparable = [(day, a) for day, a in eligible if abs(float(a.avg_hr) - ref) <= band]
    if len(comparable) < 3:
        # Widen once; still preferable to mathematically 'correcting' pace by HR.
        band = 10.0
        comparable = [(day, a) for day, a in eligible if abs(float(a.avg_hr) - ref) <= band]
    if len(comparable) < 3:
        return {"available": False, "sport": family, "points": [], "reference_hr": round(ref)}

    bucket: dict[date, list[Activity]] = defaultdict(list)
    for day, activity in comparable:
        bucket[_bucket_start(day, mode)].append(activity)
    points: list[dict[str, Any]] = []
    for key in sorted(bucket):
        rows = bucket[key]
        avg_hr = _mean(a.avg_hr for a in rows)
        if family == "running":
            speeds = [float(a.avg_speed) for a in rows if a.avg_speed and a.avg_speed > 0]
            speed = _mean(speeds)
            if speed is None:
                continue
            value = (1000.0 / speed) / 60.0  # min/km
            metric = "pace_min_km"
        else:
            value = _mean(a.avg_power for a in rows)
            if value is None:
                continue
            metric = "power_w"
        points.append({"date": key.isoformat(), "label": _bucket_label(key, mode), "value": round(value, 3), "avg_hr": round(avg_hr or ref, 1), "sessions": len(rows)})
    pairs = [(date.fromisoformat(p["date"]), float(p["value"])) for p in points]
    first, second = _first_second(pairs)
    change = _pct_change(first, second)
    if family == "running" and change is not None:
        # Lower pace (min/km) is better; expose positive % as improvement.
        improvement = -change
    else:
        improvement = change
    return {
        "available": len(points) >= 2,
        "sport": family,
        "metric": metric if points else ("pace_min_km" if family == "running" else "power_w"),
        "reference_hr": round(ref),
        "hr_band": [round(ref - band), round(ref + band)],
        "points": points,
        "change_percent": round(improvement, 1) if improvement is not None else None,
        "trend": _trend(improvement, threshold=2.0),
        "note": "Uses only sessions with comparable average heart rate; running also rejects clearly hilly summaries. It does not mathematically normalize pace or power to heart rate.",
    }


def _volume_series(activities: list[Activity], user: User, mode: str) -> list[dict[str, Any]]:
    buckets: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for activity in activities:
        day = _local_day(activity.started_at, user)
        if day is None:
            continue
        key = _bucket_start(day, mode)
        family = sport_family(activity.sport_type)
        buckets[key][family] += max(0, float(activity.duration_seconds or 0)) / 60.0
    rows: list[dict[str, Any]] = []
    for key in sorted(buckets):
        parts = buckets[key]
        item: dict[str, Any] = {"date": key.isoformat(), "label": _bucket_label(key, mode)}
        total = 0.0
        for family in ("running", "cycling", "strength", "mobility", "swimming", "walking", "other"):
            value = round(parts.get(family, 0.0), 1)
            item[family] = value
            total += value
        item["total_minutes"] = round(total, 1)
        rows.append(item)
    return rows


def _load_recovery_series(activities: list[Activity], health: list[DailyHealth], hrvs: list[HrvDaily], user: User, mode: str) -> tuple[list[dict[str, Any]], str]:
    activity_buckets: dict[date, list[Activity]] = defaultdict(list)
    for activity in activities:
        day = _local_day(activity.started_at, user)
        if day:
            activity_buckets[_bucket_start(day, mode)].append(activity)
    health_buckets: dict[date, list[DailyHealth]] = defaultdict(list)
    for row in health:
        health_buckets[_bucket_start(row.date, mode)].append(row)
    hrv_buckets: dict[date, list[HrvDaily]] = defaultdict(list)
    for row in hrvs:
        hrv_buckets[_bucket_start(row.date, mode)].append(row)
    load_coverage = (
        sum(1 for a in activities if a.training_load is not None) / len(activities)
        if activities else 0.0
    )
    basis = "garmin_training_load" if load_coverage >= 0.5 and any(a.training_load is not None for a in activities) else "training_minutes"
    keys = sorted(set(activity_buckets) | set(health_buckets) | set(hrv_buckets))
    result: list[dict[str, Any]] = []
    for key in keys:
        acts = activity_buckets.get(key, [])
        if basis == "garmin_training_load":
            load = sum(float(a.training_load or 0) for a in acts)
        else:
            load = sum(float(a.duration_seconds or 0) for a in acts) / 60.0
        hrv = _mean(row.overnight_average for row in hrv_buckets.get(key, []))
        rhr = _mean(row.resting_hr for row in health_buckets.get(key, []))
        result.append({
            "date": key.isoformat(), "label": _bucket_label(key, mode), "load": round(load, 1),
            "hrv": round(hrv, 1) if hrv is not None else None,
            "resting_hr": round(rhr, 1) if rhr is not None else None,
        })
    return result, basis


def _changes(
    activities: list[Activity], health: list[DailyHealth], hrvs: list[HrvDaily],
    imported: dict[str, list[dict[str, Any]]], estimates: dict[str, list[dict[str, Any]]],
    efficiency: dict[str, Any], user: User,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    vo2_rows = imported.get("running", []) or imported.get("cycling", [])
    measurement_kind = "imported"
    if len(vo2_rows) < 2:
        estimated_candidates = [rows for rows in (estimates.get("running", []), estimates.get("cycling", [])) if len(rows) >= 3]
        vo2_rows = max(estimated_candidates, key=len, default=[])
        measurement_kind = "estimated"
    if len(vo2_rows) >= 2:
        pairs = [(date.fromisoformat(p["date"]), float(p["value"])) for p in vo2_rows]
        first, second = _first_second(pairs)
        delta = (second - first) if first is not None and second is not None else None
        if delta is not None:
            result.append({"key": "vo2", "label": "VO2max", "delta": round(delta, 1), "unit": "ml/kg/min", "trend": _trend(delta, threshold=0.5), "positive_when": "up", "measurement_kind": measurement_kind})
    best_eff = next((efficiency[k] for k in ("running", "cycling") if efficiency.get(k, {}).get("available")), None)
    if best_eff and best_eff.get("change_percent") is not None:
        result.append({"key": "efficiency", "label": "Efficiency", "delta": best_eff["change_percent"], "unit": "%", "trend": _trend(best_eff["change_percent"]), "positive_when": "up", "sport": best_eff["sport"]})
    rhr_pairs = [(row.date, float(row.resting_hr)) for row in health if row.resting_hr is not None]
    first, second = _first_second(rhr_pairs)
    if first is not None and second is not None:
        delta = second - first
        result.append({"key": "resting_hr", "label": "Resting HR", "delta": round(delta, 1), "unit": "bpm", "trend": _trend(delta, threshold=1.0, inverse=True), "positive_when": "down"})
    hrv_pairs = [(row.date, float(row.overnight_average)) for row in hrvs if row.overnight_average is not None]
    first, second = _first_second(hrv_pairs)
    if first is not None and second is not None:
        change = _pct_change(first, second)
        if change is not None:
            result.append({"key": "hrv", "label": "HRV", "delta": round(change, 1), "unit": "%", "trend": _trend(change), "positive_when": "up"})
    # Selected-period weekly volume change; only when there is enough history to compare.
    days = sorted({_local_day(a.started_at, user) for a in activities if _local_day(a.started_at, user)})
    if len(days) >= 14:
        midpoint = days[len(days) // 2]
        first_minutes = sum((a.duration_seconds or 0) for a in activities if (_local_day(a.started_at, user) or midpoint) < midpoint) / 60.0
        second_minutes = sum((a.duration_seconds or 0) for a in activities if (_local_day(a.started_at, user) or midpoint) >= midpoint) / 60.0
        change = _pct_change(first_minutes, second_minutes)
        if change is not None:
            result.append({"key": "volume", "label": "Training volume", "delta": round(change, 1), "unit": "%", "trend": "rising" if change > 5 else "falling" if change < -5 else "stable", "positive_when": "neutral"})
    return result


def _status_from_changes(changes: list[dict[str, Any]], keys: set[str]) -> str:
    relevant = [row for row in changes if row.get("key") in keys]
    score = sum(1 if row.get("trend") == "rising" else -1 if row.get("trend") == "falling" else 0 for row in relevant)
    if score > 0:
        return "rising"
    if score < 0:
        return "falling"
    return "stable" if relevant else "unknown"


async def training_development(
    db: AsyncSession,
    user: User,
    *,
    days: int = 30,
    all_data: bool = False,
) -> dict[str, Any]:
    today = user_today(user)
    start = None if all_data else today - timedelta(days=max(1, days) - 1)
    activity_stmt = select(Activity).where(Activity.user_id == user.id, Activity.started_at.is_not(None))
    health_stmt = select(DailyHealth).where(DailyHealth.user_id == user.id)
    hrv_stmt = select(HrvDaily).where(HrvDaily.user_id == user.id)
    body_stmt = select(BodyMeasurement).where(BodyMeasurement.user_id == user.id)
    if start is not None:
        # Keep preceding health/body context for resting-HR and weight fallbacks.
        activity_stmt = activity_stmt.where(Activity.started_at >= day_start(start, user))
        health_stmt = health_stmt.where(DailyHealth.date >= start - timedelta(days=28))
        hrv_stmt = hrv_stmt.where(HrvDaily.date >= start)
    activities = list((await db.scalars(activity_stmt.order_by(Activity.started_at))).all())
    health_all = list((await db.scalars(health_stmt.order_by(DailyHealth.date))).all())
    hrvs = list((await db.scalars(hrv_stmt.order_by(HrvDaily.date))).all())
    bodies = list((await db.scalars(body_stmt.order_by(BodyMeasurement.measured_at))).all())
    health = [row for row in health_all if start is None or row.date >= start]

    metric_map: dict[Any, ActivityMetric] = {}
    ids = [a.id for a in activities]
    if ids:
        metric_rows = list((await db.scalars(select(ActivityMetric).where(ActivityMetric.activity_id.in_(ids)))).all())
        metric_map = {row.activity_id: row for row in metric_rows}
    from pengucoach.garmin.zones import training_zone_snapshot
    zones = await training_zone_snapshot(db, user.id)
    imported = imported_vo2_history(activities, health, user)
    estimates = estimate_vo2_history(activities, health_all, bodies, metric_map, zones, user)
    mode = _bucket_mode(None if all_data else days)
    efficiency = {
        "running": _efficiency_series(activities, user, "running", mode),
        "cycling": _efficiency_series(activities, user, "cycling", mode),
    }
    volume = _volume_series(activities, user, mode)
    load_recovery, load_basis = _load_recovery_series(activities, health, hrvs, user, mode)
    changes = _changes(activities, health, hrvs, imported, estimates, efficiency, user)

    # Recovery status uses HRV up and resting HR down as positive signals.
    recovery_relevant: list[int] = []
    for row in changes:
        if row["key"] == "hrv":
            recovery_relevant.append(1 if row["trend"] == "rising" else -1 if row["trend"] == "falling" else 0)
        elif row["key"] == "resting_hr":
            recovery_relevant.append(1 if row["trend"] == "rising" else -1 if row["trend"] == "falling" else 0)
    recovery_status = "rising" if sum(recovery_relevant) > 0 else "falling" if sum(recovery_relevant) < 0 else "stable" if recovery_relevant else "unknown"

    sport_minutes: dict[str, float] = defaultdict(float)
    for activity in activities:
        sport_minutes[sport_family(activity.sport_type)] += max(0, float(activity.duration_seconds or 0)) / 60.0
    total_minutes = sum(sport_minutes.values())
    sport_mix = [
        {"sport": sport, "minutes": round(minutes), "percent": round(minutes / total_minutes * 100) if total_minutes else 0}
        for sport, minutes in sorted(sport_minutes.items(), key=lambda item: (-item[1], item[0]))
        if minutes > 0
    ]

    load_pairs = [(date.fromisoformat(row["date"]), float(row["load"])) for row in load_recovery if row.get("load") is not None]
    load_first, load_second = _first_second(load_pairs)
    load_change = _pct_change(load_first, load_second)
    load_status = "rising" if load_change is not None and load_change > 8 else "falling" if load_change is not None and load_change < -8 else "stable" if load_change is not None else "unknown"
    running_est = estimate_summary(estimates["running"])
    cycling_est = estimate_summary(estimates["cycling"])
    display_vo2 = vo2_display_payload(imported, estimates)
    return {
        "period": {"days": None if all_data else days, "all": all_data, "from": start.isoformat() if start else None, "to": today.isoformat(), "aggregation": mode},
        "summary": {
            "fitness": _status_from_changes(changes, {"vo2", "efficiency", "resting_hr"}),
            "recovery": recovery_status,
            "efficiency": next((efficiency[k] for k in ("running", "cycling") if efficiency[k].get("available")), {"available": False}),
            "load": {"status": load_status, "change_percent": round(load_change, 1) if load_change is not None else None, "basis": load_basis},
            "sessions": len(activities),
            "minutes": round(total_minutes),
        },
        "vo2": {
            "imported": imported,
            "estimated": estimates,
            "estimate_latest": {"running": running_est, "cycling": cycling_est},
        },
        "vo2_display": display_vo2,
        "efficiency": efficiency,
        "volume": volume,
        "sport_mix": sport_mix,
        "load_recovery": load_recovery,
        "load_basis": load_basis,
        "changes": changes,
        "methodology": {
            "vo2_estimates_are_clinical_measurements": False,
            "running": "ACSM running oxygen-cost equation on relatively flat activities + HR reserve to VO2 reserve extrapolation.",
            "cycling": "ACSM cycle workload equation requires measured power + body mass + HR reserve; speed-only cycling is never used.",
            "guardrails": [
                "Imported provider VO2 values always take precedence.",
                "Estimates are labelled and never written back as provider measurements.",
                "Hilly running sessions and low-intensity/near-maximal average-HR sessions are rejected.",
                "Cycling estimates require power and body mass.",
            ],
        },
    }


async def development_summary_for_coach(db: AsyncSession, user: User, days: int = 90) -> dict[str, Any]:
    """Small evidence payload for the AI coach; no chart arrays or invented score."""
    result = await training_development(db, user, days=days, all_data=False)
    return {
        "period_days": days,
        "fitness_trend": result["summary"]["fitness"],
        "recovery_trend": result["summary"]["recovery"],
        "efficiency": result["summary"]["efficiency"],
        "changes": result["changes"][:6],
        "vo2_estimate_latest": result["vo2"]["estimate_latest"],
        "note": "VO2 fallback values are PenguCoach estimates, not direct measurements; provider measurements take precedence.",
    }
