from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, AiRun, CoachProfile, GarminWorkoutExport, PlanSchedule, User, UserPreference
from pengucoach.training_plan.structured import TrainingPlanDocument
from pengucoach.weather.service import fetch_forecast, weather_config

OUTDOOR_SPORTS = {"running", "cycling", "walking", "hiking"}


def sport_family(value: str | None) -> str:
    text = str(value or "").casefold()
    if any(x in text for x in ("run", "jog", "treadmill")):
        return "running"
    if any(x in text for x in ("bike", "cycling", "cycle", "biking")):
        return "cycling"
    if "swim" in text:
        return "swimming"
    if any(x in text for x in ("strength", "weight", "gym")):
        return "strength"
    if any(x in text for x in ("walk", "hike", "hiking")):
        return "walking" if "walk" in text else "hiking"
    if any(x in text for x in ("yoga", "mobility", "pilates")):
        return "mobility"
    return text or "other"


def _ratio_status(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio < 0.7:
        return "lower"
    if ratio <= 1.3:
        return "stable"
    if ratio <= 1.5:
        return "elevated"
    return "high"


def _trend(status: str) -> str:
    return {
        "lower": "falling",
        "stable": "stable",
        "elevated": "rising",
        "high": "strongly_rising",
    }.get(status, "unknown")


async def training_load_summary(db: AsyncSession, user: User, *, today: date | None = None) -> dict[str, Any]:
    """Deterministic 7/28-day load summary.

    Garmin training load is preferred when enough recent activities contain it.
    Otherwise the trend falls back to training minutes, which is deliberately
    labelled so the UI never presents a synthetic score as Garmin load.
    """
    today = today or user_today(user)
    since = today - timedelta(days=27)
    rows = list((await db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id, Activity.started_at >= day_start(since, user))
        .order_by(Activity.started_at)
    )).all())

    def in_days(activity: Activity, days: int) -> bool:
        if not activity.started_at:
            return False
        stamp = activity.started_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        local_day = stamp.astimezone(ZoneInfo(user.timezone)).date()
        return local_day >= today - timedelta(days=days - 1)

    recent7 = [a for a in rows if in_days(a, 7)]
    load_rows = [a for a in rows if a.training_load is not None]
    load7 = [a for a in recent7 if a.training_load is not None]
    load_coverage = (len(load_rows) / len(rows)) if rows else 0.0

    minutes28 = sum(max(0, a.duration_seconds or 0) for a in rows) / 60
    minutes7 = sum(max(0, a.duration_seconds or 0) for a in recent7) / 60
    load28_total = sum(float(a.training_load or 0) for a in load_rows)
    load7_total = sum(float(a.training_load or 0) for a in load7)

    use_garmin_load = bool(load_rows) and load_coverage >= 0.5
    acute = load7_total if use_garmin_load else minutes7
    chronic = (load28_total / 4) if use_garmin_load else (minutes28 / 4)
    ratio = round(acute / chronic, 2) if chronic > 0 else None
    status = _ratio_status(ratio)

    sport_minutes: dict[str, float] = defaultdict(float)
    for activity in recent7:
        sport_minutes[sport_family(activity.sport_type)] += max(0, activity.duration_seconds or 0) / 60
    total_sport_minutes = sum(sport_minutes.values())
    sport_mix = [
        {"sport": sport, "minutes": round(minutes), "percent": round(minutes / total_sport_minutes * 100) if total_sport_minutes else 0}
        for sport, minutes in sorted(sport_minutes.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "period_end": today.isoformat(),
        "basis": "garmin_training_load" if use_garmin_load else "training_minutes",
        "acute_7d": round(acute, 1),
        "chronic_28d_weekly": round(chronic, 1),
        "ratio": ratio,
        "status": status,
        "trend": _trend(status),
        "minutes_7d": round(minutes7),
        "minutes_28d": round(minutes28),
        "average_weekly_minutes_28d": round(minutes28 / 4),
        "sessions_7d": len(recent7),
        "sessions_28d": len(rows),
        "load_coverage": round(load_coverage, 2),
        "sport_mix": sport_mix,
        "note": (
            "Uses Garmin training_load when at least half of the 28-day activities provide it; otherwise the trend uses training minutes. "
            "This is a planning trend, not a medical readiness score."
        ),
    }


def weather_assessment(row: dict[str, Any] | None, sport: str | None) -> dict[str, Any] | None:
    if not row or sport_family(sport) not in OUTDOOR_SPORTS:
        return None
    reasons: list[str] = []
    severity = "good"
    precip = row.get("precipitation_probability_max")
    rain = row.get("precipitation_sum")
    wind = row.get("wind_speed_10m_max")
    gust = row.get("wind_gusts_10m_max")
    high = row.get("temperature_2m_max")
    low = row.get("temperature_2m_min")
    uv = row.get("uv_index_max")

    def add(reason: str, level: str = "warning"):
        nonlocal severity
        reasons.append(reason)
        order = {"good": 0, "notice": 1, "warning": 2, "severe": 3}
        if order[level] > order[severity]:
            severity = level

    if precip is not None and float(precip) >= 70:
        add("rain_probability")
    if rain is not None and float(rain) >= 8:
        add("heavy_rain", "severe")
    if wind is not None and float(wind) >= 35:
        add("strong_wind", "warning")
    if gust is not None and float(gust) >= 55:
        add("strong_gusts", "severe")
    if high is not None and float(high) >= 30:
        add("heat", "warning")
    if high is not None and float(high) >= 35:
        add("extreme_heat", "severe")
    if low is not None and float(low) <= 0:
        add("freezing", "warning")
    if uv is not None and float(uv) >= 7:
        add("high_uv", "notice")

    return {
        "date": row.get("date"),
        "severity": severity,
        "reasons": reasons,
        "indoor_recommended": severity in {"warning", "severe"},
        "temperature_max_c": high,
        "temperature_min_c": low,
        "precipitation_probability": precip,
        "precipitation_mm": rain,
        "wind_kmh": wind,
        "gust_kmh": gust,
        "uv_index": uv,
        "weather_code": row.get("weather_code"),
    }


def _is_hard_session(session: dict[str, Any]) -> bool:
    text = f"{session.get('name', '')} {session.get('notes', '')}".casefold()
    if any(term in text for term in ("interval", "tempo", "threshold", "schwelle", "vo2", "hiit", "race", "wettkampf")):
        return True
    for step in session.get("steps") or []:
        target = step.get("target") or {}
        if target.get("type") in {"heart_rate_zone", "power_zone"} and int(target.get("zone") or 0) >= 4:
            return True
    return False


def plan_conflicts(
    sessions: list[dict[str, Any]],
    profile: dict[str, Any],
    other_exports: list[GarminWorkoutExport] | None = None,
    other_plan_sessions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect only deterministic conflicts. No automatic plan mutation happens here."""
    conflicts: list[dict[str, Any]] = []
    allowed_days = set(int(x) for x in (profile.get("training_days") or []) if str(x).isdigit())
    typical_minutes = int(profile.get("session_minutes") or 0)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        by_date[str(session["date"])].append(session)
        day = date.fromisoformat(str(session["date"]))
        if allowed_days and day.isoweekday() not in allowed_days:
            conflicts.append({
                "type": "outside_training_days", "severity": "warning", "session_id": session["id"],
                "date": session["date"], "proposed_action": "postpone",
            })
        if typical_minutes and int(session.get("duration_min") or 0) > max(typical_minutes + 30, round(typical_minutes * 1.5)):
            conflicts.append({
                "type": "longer_than_typical", "severity": "notice", "session_id": session["id"],
                "date": session["date"], "typical_minutes": typical_minutes, "planned_minutes": session.get("duration_min"),
            })

    for day, rows in by_date.items():
        total = sum(int(x.get("duration_min") or 0) for x in rows)
        if len(rows) > 1 and total > max(90, typical_minutes * 2 if typical_minutes else 90):
            conflicts.append({
                "type": "double_session_load", "severity": "notice", "date": day,
                "session_ids": [x["id"] for x in rows], "total_minutes": total,
            })

    ordered = sorted(sessions, key=lambda x: (x["date"], x["id"]))
    for left, right in zip(ordered, ordered[1:]):
        d1, d2 = date.fromisoformat(left["date"]), date.fromisoformat(right["date"])
        if (d2 - d1).days == 1 and _is_hard_session(left) and _is_hard_session(right):
            conflicts.append({
                "type": "hard_back_to_back", "severity": "warning", "session_id": right["id"],
                "related_session_id": left["id"], "date": right["date"], "proposed_action": "reduce",
            })

    other_index: dict[tuple[str, str], dict[str, Any]] = {}
    for other in other_plan_sessions or []:
        day = str(other.get("date") or "")
        other_run_id = str(other.get("plan_run_id") or "")
        if not day or not other_run_id:
            continue
        for session in by_date.get(day, []):
            key = (session["id"], other_run_id)
            existing = other_index.get(key)
            if existing is not None:
                existing["other_session_count"] = int(existing.get("other_session_count") or 1) + 1
                continue
            conflict = {
                "type": "other_pengucoach_plan_same_day",
                "severity": "warning",
                "session_id": session["id"],
                "date": day,
                "proposed_action": "postpone",
                "other_plan_run_id": other_run_id,
                "other_session_id": other.get("id"),
                "other_session_name": other.get("name"),
                "other_session_count": 1,
                "garmin_exported": False,
            }
            conflicts.append(conflict)
            other_index[key] = conflict

    if other_exports:
        for export in other_exports:
            day = export.scheduled_date.isoformat()
            other_run_id = str(export.plan_run_id)
            for session in by_date.get(day, []):
                existing = other_index.get((session["id"], other_run_id))
                if existing is not None:
                    existing["garmin_exported"] = True
                    continue
                conflicts.append({
                    "type": "other_garmin_plan_same_day", "severity": "warning", "session_id": session["id"],
                    "date": day, "proposed_action": "postpone", "other_plan_run_id": other_run_id,
                })
    return conflicts


def _sessions_for_schedule(run: AiRun, schedule: PlanSchedule) -> list[dict[str, Any]]:
    """Render a saved PenguCoach plan schedule without importing companion (avoids a cycle)."""
    try:
        plan = TrainingPlanDocument.model_validate((run.metadata_json or {}).get("structured_plan"))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for session in plan.sessions:
        base = dict((schedule.overrides or {}).get(session.id) or session.model_dump())
        try:
            scheduled = schedule.start_date + timedelta(weeks=int(base["week"]) - 1, days=int(base["day"]) - 1)
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({**base, "date": scheduled.isoformat(), "plan_run_id": str(run.id)})
    return rows


async def plan_intelligence(
    db: AsyncSession,
    user: User,
    run_id,
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    profile_row = await db.get(CoachProfile, user.id)
    profile = dict(profile_row.data or {}) if profile_row else {}
    dates = [date.fromisoformat(str(s["date"])) for s in sessions]
    start = min(dates) if dates else user_today(user)
    end = max(dates) if dates else start
    exports = list((await db.scalars(
        select(GarminWorkoutExport).where(
            GarminWorkoutExport.user_id == user.id,
            GarminWorkoutExport.plan_run_id != run_id,
            GarminWorkoutExport.status == "exported",
            GarminWorkoutExport.scheduled_date >= start,
            GarminWorkoutExport.scheduled_date <= end,
        )
    )).all())
    # Other saved PenguCoach schedules are conflicts even when they have not been
    # exported to Garmin. Garmin export data enriches the same conflict instead
    # of creating a duplicate warning.
    other_plan_sessions: list[dict[str, Any]] = []
    other_rows = (await db.execute(
        select(PlanSchedule, AiRun)
        .join(AiRun, AiRun.id == PlanSchedule.plan_run_id)
        .where(PlanSchedule.user_id == user.id, PlanSchedule.plan_run_id != run_id)
    )).all()
    for other_schedule, other_run in other_rows:
        for other in _sessions_for_schedule(other_run, other_schedule):
            if start.isoformat() <= str(other.get("date")) <= end.isoformat():
                other_plan_sessions.append(other)

    conflicts = plan_conflicts(sessions, profile, exports, other_plan_sessions)

    weather_by_date: dict[str, dict[str, Any]] = {}
    weather_error: str | None = None
    pref = await db.get(UserPreference, user.id)
    cfg = weather_config(pref)
    if cfg.get("enabled") and cfg.get("latitude") is not None and cfg.get("longitude") is not None:
        try:
            forecast = await fetch_forecast(float(cfg["latitude"]), float(cfg["longitude"]), str(cfg.get("timezone") or "auto"), 16)
            weather_by_date = {str(x.get("date")): x for x in forecast.get("daily") or [] if x.get("date")}
        except Exception as exc:  # weather must never break the training calendar
            weather_error = type(exc).__name__

    annotations: dict[str, dict[str, Any]] = {}
    for session in sessions:
        assessment = weather_assessment(weather_by_date.get(str(session["date"])), session.get("sport"))
        annotations[session["id"]] = {
            "date": session["date"],
            "outdoor": sport_family(session.get("sport")) in OUTDOOR_SPORTS,
            "weather": assessment,
            "conflicts": [c for c in conflicts if c.get("session_id") == session["id"] or session["id"] in c.get("session_ids", [])],
        }

    return {
        "load": await training_load_summary(db, user),
        "sessions": annotations,
        "conflicts": conflicts,
        "weather": {
            "enabled": bool(cfg.get("enabled")),
            "location": cfg.get("location_name") or "",
            "available": bool(weather_by_date),
            "error": weather_error,
            "forecast_days": len(weather_by_date),
        },
    }
