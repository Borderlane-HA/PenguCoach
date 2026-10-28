"""Period recap ("Rückblick") for the activity journal.

Pure aggregation over plain rows so it can be tested without a database.
Missing values are skipped, never counted as zero distance or elevation.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Iterable

PERIODS = ("today", "week", "month", "year", "all")
_FAMILIES = (
    ("swim", r"swim|schwimm"), ("hike", r"hik|wander|mountaineer"), ("walk", r"walk|gehen"),
    ("run", r"run|lauf|jog|treadmill"), ("ride", r"cycl|bik|ride|rad"), ("strength", r"strength|weight|kraft|gym"),
)


def family(sport_type: Any) -> str:
    value = str(sport_type or "").lower()
    for name, pattern in _FAMILIES:
        if re.search(pattern, value):
            return name
    return "other"


def period_bounds(period: str, today: date) -> dict[str, date | None]:
    """Current period up to today and the previous period over the same elapsed span."""
    if period not in PERIODS:
        raise ValueError("RECAP_PERIOD_INVALID")
    if period == "all":
        return {"start": None, "end": today, "previous_start": None, "previous_end": None}
    if period == "today":
        start, previous_start = today, today - timedelta(days=1)
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        previous_start = start - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
        last = start - timedelta(days=1)
        previous_start = last.replace(day=1)
    else:
        start = today.replace(month=1, day=1)
        previous_start = start.replace(year=start.year - 1)
    elapsed = today - start
    previous_end = previous_start + elapsed
    if period == "month":
        # 31 March compares with the whole of February, not with early March.
        previous_end = min(previous_end, previous_start.replace(day=monthrange(previous_start.year, previous_start.month)[1]))
    if period == "year":
        previous_end = min(previous_end, previous_start.replace(month=12, day=31))
    return {"start": start, "end": today, "previous_start": previous_start, "previous_end": previous_end}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def totals(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    result = {"count": 0, "distance_m": 0.0, "duration_s": 0.0, "elevation_m": 0.0, "calories": 0.0,
              "with_distance": 0, "with_elevation": 0, "with_calories": 0}
    for row in rows:
        result["count"] += 1
        for key, source in (("distance_m", "distance_m"), ("elevation_m", "elevation_m"), ("calories", "calories")):
            value = _num(row.get(source))
            if value is not None and value > 0:
                result[key] += value
                result["with_" + key.split("_")[0]] += 1
        duration = _num(row.get("duration_s"))
        if duration is not None and duration > 0:
            result["duration_s"] += duration
    for key in ("distance_m", "duration_s", "elevation_m", "calories"):
        result[key] = round(result[key], 1)
    return result


def _streaks(days: set[date], today: date) -> dict[str, int]:
    longest = current = 0
    run, previous = 0, None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    # The current streak may end yesterday: today is not over yet.
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)
    return {"longest": longest, "current": current}


def _highlight(row: dict[str, Any], value: float, unit: str) -> dict[str, Any]:
    return {"id": str(row["id"]), "name": row.get("name") or row.get("sport_type") or "",
            "sport": family(row.get("sport_type")), "date": row["day"].isoformat(), "value": round(value, 2), "unit": unit}


def highlights(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    def best(key: str, unit: str, pick, candidates):
        scored = [(pick(row), row) for row in candidates]
        scored = [(value, row) for value, row in scored if value is not None and value > 0]
        if scored:
            value, row = max(scored, key=lambda item: item[0])
            result[key] = _highlight(row, value, unit)
    best("longest_distance", "m", lambda r: _num(r.get("distance_m")), rows)
    best("longest_duration", "s", lambda r: _num(r.get("duration_s")), rows)
    best("biggest_climb", "m", lambda r: _num(r.get("elevation_m")), rows)
    runs = [r for r in rows if family(r.get("sport_type")) == "run" and (_num(r.get("distance_m")) or 0) >= 3000]
    def speed(row):
        distance, duration = _num(row.get("distance_m")), _num(row.get("duration_s"))
        return distance / duration if distance and duration else None
    best("fastest_run", "m/s", speed, runs)
    if "fastest_run" in result:
        fastest = next(r for r in runs if str(r["id"]) == result["fastest_run"]["id"])
        result["fastest_run"]["pace_s_per_km"] = round(_num(fastest["duration_s"]) / _num(fastest["distance_m"]) * 1000, 1)
    rides = [r for r in rows if family(r.get("sport_type")) == "ride"]
    best("strongest_ride", "W", lambda r: _num(r.get("avg_power")), rides)
    return result


def series(rows: list[dict[str, Any]], period: str, start: date | None, today: date) -> dict[str, Any]:
    """Days for calendars (week, month, year), months for the full history."""
    if period == "all":
        if not rows:
            return {"granularity": "month", "items": []}
        first = min(r["day"] for r in rows).replace(day=1)
        buckets: dict[str, dict[str, float]] = {}
        cursor = first
        while cursor <= today:
            buckets[cursor.strftime("%Y-%m")] = {"count": 0, "distance_m": 0.0, "duration_s": 0.0}
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        key_of = lambda day: day.strftime("%Y-%m")  # noqa: E731
        granularity = "month"
    else:
        begin = start or today
        buckets = {(begin + timedelta(days=i)).isoformat(): {"count": 0, "distance_m": 0.0, "duration_s": 0.0}
                   for i in range((today - begin).days + 1)}
        key_of = lambda day: day.isoformat()  # noqa: E731
        granularity = "day"
    for row in rows:
        bucket = buckets.get(key_of(row["day"]))
        if bucket is None:
            continue
        bucket["count"] += 1
        bucket["distance_m"] += _num(row.get("distance_m")) or 0
        bucket["duration_s"] += _num(row.get("duration_s")) or 0
    return {"granularity": granularity,
            "items": [{"key": key, **{k: round(v, 1) for k, v in value.items()}} for key, value in buckets.items()]}


def change(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, float | None]:
    if not previous:
        return {}
    result = {}
    for key in ("count", "distance_m", "duration_s", "elevation_m", "calories"):
        before, now = previous.get(key) or 0, current.get(key) or 0
        result[key] = None if not before else round((now - before) / before * 100, 1)
    return result


def summarize(rows: list[dict[str, Any]], *, period: str, today: date, previous: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    bounds = period_bounds(period, today)
    sports: dict[str, dict[str, float]] = {}
    for row in rows:
        entry = sports.setdefault(family(row.get("sport_type")), {"count": 0, "distance_m": 0.0, "duration_s": 0.0})
        entry["count"] += 1
        entry["distance_m"] += max(0.0, _num(row.get("distance_m")) or 0)
        entry["duration_s"] += max(0.0, _num(row.get("duration_s")) or 0)
    days = {row["day"] for row in rows}
    current = totals(rows)
    before = totals(previous) if previous is not None else None
    return {
        "period": period,
        "start": bounds["start"].isoformat() if bounds["start"] else (min(days).isoformat() if days else None),
        "end": today.isoformat(),
        "totals": current,
        "active_days": len(days),
        "streaks": _streaks(days, today),
        "sports": [{"sport": key, **{k: round(v, 1) for k, v in value.items()}}
                   for key, value in sorted(sports.items(), key=lambda item: (-item[1]["duration_s"], item[0]))],
        "highlights": highlights(rows),
        "series": series(rows, period, bounds["start"], today),
        "previous": before,
        "change": change(current, before),
    }


def downsample(points: list[tuple[float, float]], limit: int = 140) -> list[list[float]]:
    """Evenly thinned route that always keeps start and finish."""
    clean = [(lat, lon) for lat, lon in points if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180 and (lat, lon) != (0.0, 0.0)]
    if len(clean) < 2:
        return []
    if len(clean) > limit:
        step = (len(clean) - 1) / (limit - 1)
        clean = [clean[round(i * step)] for i in range(limit)]
    return [[round(lat, 5), round(lon, 5)] for lat, lon in clean]
