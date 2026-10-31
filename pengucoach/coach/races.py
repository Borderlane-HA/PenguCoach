"""Race mode (alpha.85): phases, countdown, prognosis and taper proposal.

Everything here is deterministic and explainable. The prognosis is an estimate
from the user's own recent recordings (Riegel's endurance formula), shown as a
range; the taper is a proposal the user confirms – nothing changes on its own.
"""
from __future__ import annotations

import copy
import math
from datetime import date, timedelta
from typing import Any

RACE_SPORTS = ("running", "cycling", "swimming", "triathlon", "hiking", "other")
PRIORITIES = ("A", "B", "C")
PRESETS = {
    "running": [(5.0, "5 km"), (10.0, "10 km"), (21.0975, "Halbmarathon"), (42.195, "Marathon")],
    "cycling": [(100.0, "100 km"), (160.0, "160 km"), (200.0, "200 km")],
}
RIEGEL = 1.06
PROGNOSIS_WINDOW_DAYS = 56


def taper_days(sport: str, distance_km: float | None) -> int:
    """Length of the taper: short races a week, a marathon two weeks, ultras three."""
    d = distance_km or 0
    if sport == "running":
        return 7 if d <= 10.5 else 10 if d <= 21.5 else 14 if d <= 43 else 21
    if sport == "cycling":
        return 7 if d <= 100 else 10 if d <= 180 else 14
    if sport == "triathlon":
        return 10 if d <= 60 else 14
    if sport == "swimming":
        return 7
    return 7


def phase(race_date: date, today: date, sport: str, distance_km: float | None) -> dict[str, Any]:
    """Where the user is on the way to the race: base → build → peak → taper → race → done."""
    days = (race_date - today).days
    taper = taper_days(sport, distance_km)
    if days < -7:
        key = "past"
    elif days < 0:
        key = "done"
    elif days == 0:
        key = "race"
    elif days <= taper:
        key = "taper"
    elif days <= taper + 21:
        key = "peak"
    elif days <= taper + 21 + 42:
        key = "build"
    else:
        key = "base"
    starts = {"taper": race_date - timedelta(days=taper), "peak": race_date - timedelta(days=taper + 21),
              "build": race_date - timedelta(days=taper + 63)}
    return {"key": key, "days_to_race": days, "weeks_to_race": math.floor(days / 7) if days >= 0 else None,
            "taper_days": taper, "taper_start": starts["taper"].isoformat(), "peak_start": starts["peak"].isoformat(),
            "build_start": starts["build"].isoformat()}


def _family(sport: str | None) -> str:
    from pengucoach.coach.companion import sport_family
    return sport_family(sport)


def prognosis(race, activities, today: date, day_of=None) -> dict[str, Any] | None:
    """Estimated finish time from the fastest recent efforts, as a range.

    Only recordings of the same sport from the last eight weeks with at least
    30 % of the race distance count (a 1 km sprint says little about a marathon).
    Running uses Riegel's formula T2 = T1 × (D2/D1)^1.06; cycling keeps the
    speed of the fastest long rides, slightly reduced for longer distances.
    """
    distance = race.distance_km
    if not distance or distance <= 0 or race.sport not in {"running", "cycling"}:
        return None
    since = today - timedelta(days=PROGNOSIS_WINDOW_DAYS)
    day_of = day_of or (lambda a: a.started_at.date())
    estimates = []
    for a in activities:
        if _family(a.sport_type) != race.sport or not a.started_at or not since <= day_of(a) <= today:
            continue
        km = (a.distance_m or 0) / 1000
        seconds = a.moving_seconds or a.duration_seconds
        if km < max(1.0, distance * 0.3) or not seconds or seconds <= 0:
            continue
        speed = km / seconds  # km per second
        if race.sport == "running" and not 1.5 / 3600 <= speed <= 25 / 3600:
            continue
        if race.sport == "cycling" and not 8 / 3600 <= speed <= 60 / 3600:
            continue
        exponent = RIEGEL if race.sport == "running" else 1.03
        estimates.append((seconds * (distance / km) ** exponent, a))
    if not estimates:
        return None
    estimates.sort(key=lambda x: x[0])
    best = estimates[0][0]
    second = estimates[1][0] if len(estimates) > 1 else best * 1.04
    low, high = round(best * 0.99), round(max(second, best * 1.02))
    return {"low_seconds": low, "high_seconds": high, "basis_count": len(estimates),
            "basis_activity_id": str(estimates[0][1].id), "method": "riegel_1.06" if race.sport == "running" else "speed_1.03",
            "window_days": PROGNOSIS_WINDOW_DAYS,
            "target_reachable": None if not race.target_seconds else (low <= race.target_seconds)}


def result(race, activities, day_of=None) -> dict[str, Any] | None:
    """The race recording: same day and sport; the longest one if there are several."""
    day_of = day_of or (lambda a: a.started_at.date())
    wanted = race.sport if race.sport in {"running", "cycling", "swimming", "hiking"} else None
    same = [a for a in activities if a.started_at and day_of(a) == race.date and (wanted is None or _family(a.sport_type) == wanted)]
    if not same:
        return None
    a = max(same, key=lambda x: x.distance_m or 0)
    seconds = a.duration_seconds or a.moving_seconds
    return {"activity_id": str(a.id), "name": a.name, "seconds": seconds, "distance_km": round((a.distance_m or 0) / 1000, 2),
            "target_delta_seconds": (seconds - race.target_seconds) if seconds and race.target_seconds else None}


def _scale_steps(steps: list[dict], factor: float) -> list[dict]:
    """Less volume, same intensity: fewer repeats, shorter long steps; short intervals stay."""
    out = []
    for step in steps:
        item = copy.deepcopy(step)
        if item.get("type") == "repeat":
            item["repeat"] = max(1, round((item.get("repeat") or 1) * factor))
        elif item.get("duration_seconds") and item["duration_seconds"] >= 600 and item.get("type") in {"warmup", "work", "cooldown"}:
            item["duration_seconds"] = max(300, int(round(item["duration_seconds"] * factor / 60) * 60))
        elif item.get("distance_meters") and item["distance_meters"] >= 2000 and item.get("type") in {"warmup", "work", "cooldown"}:
            item["distance_meters"] = max(1000, int(round(item["distance_meters"] * factor / 100) * 100))
        out.append(item)
    return out


def taper_proposal(race, sessions: list[dict], today: date) -> list[dict]:
    """Changes for planned sessions inside the taper window.

    ``sessions`` are scheduled sessions (with ``date``). The last three days
    before the race keep 40 % of the volume, the rest of the window 60 %.
    The day before the race is capped at 30 minutes; a session on race day is
    proposed to be cancelled. Rest days and intensity stay as planned.
    """
    window = taper_days(race.sport, race.distance_km)
    start = race.date - timedelta(days=window)
    changes = []
    for s in sessions:
        day = date.fromisoformat(s["date"])
        if day < max(start, today) or day > race.date or s.get("skipped"):
            continue
        before = {k: s.get(k) for k in ("duration_min", "steps", "name")}
        if day == race.date:
            changes.append({"session_id": s["id"], "date": s["date"], "name": s["name"], "action": "skip",
                            "before_minutes": s["duration_min"], "after_minutes": 0, "reason": "race_day"})
            continue
        days_left = (race.date - day).days
        factor = 0.4 if days_left <= 3 else 0.6
        minutes = max(15, int(round(s["duration_min"] * factor / 5) * 5))
        if days_left == 1:
            minutes = min(minutes, 30)
        if minutes >= s["duration_min"]:
            continue
        after = {"duration_min": minutes, "steps": _scale_steps(s.get("steps") or [], factor) if s.get("steps") else []}
        changes.append({"session_id": s["id"], "date": s["date"], "name": before["name"], "action": "shorten",
                        "before_minutes": s["duration_min"], "after_minutes": minutes, "factor": factor,
                        "update": after, "reason": "last_days" if days_left <= 3 else "taper"})
    return changes


def plan_context(race, plan_start: date | None, weeks: int) -> dict[str, Any]:
    """What the plan generator needs to plan backwards from the race."""
    start = plan_start or date.today()
    info = phase(race.date, start, race.sport, race.distance_km)
    race_week = (race.date - start).days // 7 + 1
    def week_of(day: str) -> int:
        return max(1, (date.fromisoformat(day) - start).days // 7 + 1)
    return {"name": race.name, "date": race.date.isoformat(), "sport": race.sport, "distance_km": race.distance_km,
            "target_time_seconds": race.target_seconds, "priority": race.priority,
            "race_week_in_plan": race_week if 1 <= race_week <= weeks else None,
            "phases_by_week": {"build_from_week": week_of(info["build_start"]), "peak_from_week": week_of(info["peak_start"]),
                               "taper_from_week": week_of(info["taper_start"])},
            "taper_days": info["taper_days"],
            "instruction": ("Plan backwards from the race: base, build, peak, then taper over the last "
                            f"{info['taper_days']} days (reduce volume by about 40-60 %, keep some intensity, no new hard "
                            "stimuli). Put the race itself on its date as the key session of that week.")}
