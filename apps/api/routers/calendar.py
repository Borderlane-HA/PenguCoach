"""Calendar page (alpha.85): year heatmap, streaks, month view with planned sessions,
moving/editing/cancelling sessions, and an iCalendar feed for phone and Outlook calendars."""
from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import uuid
import datetime as dt
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.companion import guard_exported, plan_owned, validate_overrides
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.calendar_view import active_week_streaks, ics_calendar, step_goal_streaks
from pengucoach.coach.companion import activity_day, compare_sessions, scheduled_sessions, sport_family
from pengucoach.common.dates import day_start, user_today, user_zone
from pengucoach.db.models import Activity, AiRun, DailyHealth, PlanSchedule, RaceEvent, User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.health.steps import goal_config, target_on
from pengucoach.security.crypto import SecretBox
from pengucoach.training_plan.structured import TrainingPlanDocument

router = APIRouter(prefix="/calendar", tags=["calendar"])
SPORT_ICON = {"running": "🏃", "cycling": "🚴", "swimming": "🏊", "walking": "🚶", "hiking": "🥾", "strength": "🏋️",
              "mobility": "🧘", "yoga": "🧘", "pilates": "🤸", "hiit": "⚡", "cardio": "❤️", "triathlon": "🏅"}


def _minutes(activity) -> float:
    seconds = activity.duration_seconds or activity.moving_seconds or 0
    return round(seconds / 60, 1) if seconds and seconds > 0 else 0.0


async def _activities(db, user, start: date, end: date):
    return list((await db.scalars(select(Activity).where(
        Activity.user_id == user.id, Activity.started_at >= day_start(start, user), Activity.started_at < day_start(end + timedelta(days=1), user)
    ).order_by(Activity.started_at))).all())


async def _schedules(db, user):
    rows = (await db.execute(select(PlanSchedule, AiRun).join(AiRun, AiRun.id == PlanSchedule.plan_run_id).where(
        PlanSchedule.user_id == user.id, AiRun.user_id == user.id, AiRun.task_type == "training_plan"))).all()
    return [(schedule, run) for schedule, run in rows if (run.metadata_json or {}).get("structured_plan")]


@router.get("/overview")
async def overview(year: int | None = Query(default=None, ge=2000, le=2100), weekly_minimum: int = Query(default=2, ge=1, le=7),
                   user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    """Per-day minutes, sessions, steps and floors of a year plus streaks."""
    today = user_today(user)
    year = year or today.year
    first, last = date(year, 1, 1), date(year, 12, 31)
    # Streaks look back further than the shown year so a run across New Year is not cut.
    since = min(first, today - timedelta(days=730))
    activities = await _activities(db, user, since, max(last, today))
    days: dict[str, dict] = {}
    session_days = []
    for a in activities:
        day = activity_day(a, user)
        if not day:
            continue
        session_days.append(day)
        if first <= day <= last:
            item = days.setdefault(day.isoformat(), {"minutes": 0.0, "sessions": 0, "sports": []})
            item["minutes"] = round(item["minutes"] + _minutes(a), 1)
            item["sessions"] += 1
            family = sport_family(a.sport_type)
            if family not in item["sports"]:
                item["sports"].append(family)
    health = (await db.execute(select(DailyHealth.date, DailyHealth.steps, DailyHealth.floors_ascended).where(
        DailyHealth.user_id == user.id, DailyHealth.date >= since, DailyHealth.date <= max(last, today)))).all()
    config = goal_config(await db.get(UserPreference, user.id))
    steps = {row.date: row.steps for row in health if row.steps is not None and row.date <= today}
    for row in health:
        if first <= row.date <= last and (row.steps is not None or row.floors_ascended is not None):
            item = days.setdefault(row.date.isoformat(), {"minutes": 0.0, "sessions": 0, "sports": []})
            if row.steps is not None:
                item["steps"] = row.steps
                item["step_goal"] = target_on(config, row.date)
            if row.floors_ascended is not None:
                item["floors"] = round(row.floors_ascended)
    races = list((await db.scalars(select(RaceEvent).where(RaceEvent.user_id == user.id, RaceEvent.date >= first, RaceEvent.date <= last))).all())
    for race in races:
        days.setdefault(race.date.isoformat(), {"minutes": 0.0, "sessions": 0, "sports": []})["race"] = race.name
    in_year = [d for d in session_days if first <= d <= last]
    months: dict[int, float] = {}
    for key, item in days.items():
        months[int(key[5:7])] = months.get(int(key[5:7]), 0) + item.get("minutes", 0)
    best_month = max(months.items(), key=lambda x: x[1]) if months and max(months.values()) > 0 else None
    return {
        "year": year, "today": today.isoformat(), "days": days,
        "totals": {"training_days": len(set(in_year)), "sessions": len(in_year),
                   "minutes": round(sum(item.get("minutes", 0) for item in days.values())),
                   "best_month": {"month": best_month[0], "minutes": round(best_month[1])} if best_month else None},
        "streaks": {"active_weeks": active_week_streaks(session_days, today, weekly_minimum),
                    "step_goal": {**step_goal_streaks(steps, lambda d: target_on(config, d), today),
                                  "target": target_on(config, today), "configured": config["configured"]}},
    }


@router.get("/month")
async def month(start: date, end: date, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    """Activities, planned sessions (with plan and revision for editing) and races in a range."""
    if end < start or (end - start).days > 62:
        raise HTTPException(422, "CALENDAR_RANGE_INVALID")
    today = user_today(user)
    activities = await _activities(db, user, start, end)
    zone = user_zone(user)
    items = [{"id": str(a.id), "name": a.name, "sport": sport_family(a.sport_type), "date": activity_day(a, user).isoformat(),
              "time": a.started_at.astimezone(zone).strftime("%H:%M") if a.started_at else None, "minutes": _minutes(a),
              "distance_km": round(a.distance_m / 1000, 2) if a.distance_m else None} for a in activities]
    sessions = []
    for schedule, run in await _schedules(db, user):
        plan = TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"])
        rows = scheduled_sessions(run, schedule, include_skipped=True)
        visible = [s for s in rows if start.isoformat() <= s["date"] <= end.isoformat()]
        if not visible:
            continue
        states = {c["id"]: c for c in compare_sessions([s for s in visible if not s.get("skipped")], activities, user)}
        for s in visible:
            state = states.get(s["id"], {})
            sessions.append({"plan_id": str(run.id), "plan_title": plan.title, "revision": schedule.revision,
                             "plan_start": schedule.start_date.isoformat(), "plan_weeks": plan.weeks,
                             "id": s["id"], "date": s["date"], "name": s["name"], "sport": s["sport"],
                             "duration_min": s["duration_min"], "start_time": s.get("start_time"), "notes": s.get("notes", ""),
                             "optional": s.get("optional", False), "skipped": bool(s.get("skipped")),
                             "has_steps": bool(s.get("steps")), "status": "skipped" if s.get("skipped") else state.get("status", "planned"),
                             "activity_id": state.get("activity_id"), "editable": s["date"] >= today.isoformat()})
    races = [race_brief(r) for r in (await db.scalars(select(RaceEvent).where(RaceEvent.user_id == user.id, RaceEvent.date >= start, RaceEvent.date <= end))).all()]
    return {"start": start.isoformat(), "end": end.isoformat(), "today": today.isoformat(), "activities": items, "sessions": sessions, "races": races}


def race_brief(race: RaceEvent) -> dict:
    return {"id": str(race.id), "name": race.name, "date": race.date.isoformat(), "sport": race.sport,
            "distance_km": race.distance_km, "target_seconds": race.target_seconds, "priority": race.priority}


class SessionChange(BaseModel):
    revision: int = Field(ge=0)
    date: dt.date | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    duration_min: int | None = Field(default=None, ge=5, le=480)
    start_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$|^$")
    notes: str | None = Field(default=None, max_length=1500)
    skipped: bool | None = None

    @field_validator("name", "notes")
    @classmethod
    def strip(cls, value):
        return value.strip() if isinstance(value, str) else value


async def apply_session_change(db, user, run_id: uuid.UUID, session_id: str, change: SessionChange) -> dict:
    """Move (swapping with a session of the same plan on the target day), edit or cancel one session."""
    run = await plan_owned(db, user, run_id)
    row = await db.scalar(select(PlanSchedule).where(PlanSchedule.plan_run_id == run_id, PlanSchedule.user_id == user.id).with_for_update())
    if not row:
        raise HTTPException(409, "PLAN_NOT_SCHEDULED")
    if row.revision != change.revision:
        raise HTTPException(409, "SCHEDULE_CHANGED_RELOAD")
    plan = TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"])
    current = {s.id: copy.deepcopy((row.overrides or {}).get(s.id) or s.model_dump()) for s in plan.sessions}
    if session_id not in current:
        raise HTTPException(404, "SESSION_NOT_FOUND")
    session = current[session_id]
    today = user_today(user)
    old_date = row.start_date + timedelta(weeks=session["week"] - 1, days=session["day"] - 1)
    if old_date < today and change.date is not None:
        raise HTTPException(409, "PAST_SESSION_LOCKED")
    overrides = copy.deepcopy(row.overrides or {})
    swapped = None
    if change.date is not None and change.date != old_date:
        if change.date < today:
            raise HTTPException(422, "CANNOT_MOVE_INTO_PAST")
        offset = (change.date - row.start_date).days
        week, day = offset // 7 + 1, offset % 7 + 1
        if offset < 0 or week > plan.weeks:
            raise HTTPException(422, "DATE_OUTSIDE_PLAN")
        other = next((sid for sid, s in current.items() if sid != session_id and s["week"] == week and s["day"] == day), None)
        if other:
            # One session per plan and day (Garmin export rule): the two swap places.
            moved = {**current[other], "week": session["week"], "day": session["day"]}
            overrides[other] = moved
            swapped = other
        session = {**session, "week": week, "day": day}
    for field in ("name", "duration_min", "notes", "skipped"):
        value = getattr(change, field)
        if value is not None:
            session[field] = value
    if change.start_time is not None:
        session["start_time"] = change.start_time or None
    overrides[session_id] = session
    overrides = validate_overrides(run, overrides)
    await guard_exported(db, user, run, row, row.start_date, overrides)
    row.overrides, row.revision = overrides, row.revision + 1
    await db.commit()
    return {"revision": row.revision, "swapped_with": swapped}


@router.patch("/plans/{run_id}/sessions/{session_id}")
async def change_session(run_id: uuid.UUID, session_id: str, change: SessionChange, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await apply_session_change(db, user, run_id, session_id, change)


# --- iCalendar feed ------------------------------------------------------------

def _feed_config(pref) -> dict:
    data = (pref.dashboard_config or {}).get("calendar_feed") if pref else None
    return data if isinstance(data, dict) else {}


class FeedIn(BaseModel):
    include_activities: bool = False
    rotate: bool = False


@router.get("/feed")
async def feed_settings(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    cfg = _feed_config(await db.get(UserPreference, user.id))
    if not cfg.get("token"):
        return {"enabled": False, "include_activities": bool(cfg.get("include_activities"))}
    token = SecretBox().decrypt(cfg["token"])
    return {"enabled": True, "path": f"/api/v1/calendar/feed/{user.id}/{token}.ics", "include_activities": bool(cfg.get("include_activities")),
            "created_at": cfg.get("created_at")}


@router.post("/feed")
async def enable_feed(payload: FeedIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await db.get(UserPreference, user.id)
    if not pref:
        pref = UserPreference(user_id=user.id, dashboard_config={})
        db.add(pref)
    cfg = dict(_feed_config(pref))
    if payload.rotate or not cfg.get("token"):
        token = secrets.token_urlsafe(24)
        cfg.update(token=SecretBox().encrypt(token), hash=hashlib.sha256(token.encode()).hexdigest(), created_at=datetime.now(timezone.utc).isoformat())
    cfg["include_activities"] = payload.include_activities
    pref.dashboard_config = {**(pref.dashboard_config or {}), "calendar_feed": cfg}
    await db.commit()
    return await feed_settings(user, db)


@router.delete("/feed")
async def disable_feed(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await db.get(UserPreference, user.id)
    if pref:
        config = dict(pref.dashboard_config or {})
        config.pop("calendar_feed", None)
        pref.dashboard_config = config
        await db.commit()
    return {"enabled": False}


def _steps_text(steps: list[dict], de: bool) -> list[str]:
    names = {"warmup": "Warm-up", "work": "Hauptteil" if de else "Main", "interval": "Intervall" if de else "Interval",
             "recovery": "Erholung" if de else "Recovery", "cooldown": "Cool-down", "rest": "Pause" if de else "Rest"}
    def one(step):
        if step.get("type") == "repeat":
            return f"{step.get('repeat')}× (" + " / ".join(one(x) for x in step.get("steps") or []) + ")"
        part = [names.get(step.get("type"), step.get("type") or "")]
        if step.get("duration_seconds"):
            seconds = step["duration_seconds"]
            part.append(f"{seconds} s" if seconds < 120 else f"{round(seconds / 60)} min")
        elif step.get("distance_meters"):
            meters = step["distance_meters"]
            part.append(f"{meters / 1000:.1f} km" if meters >= 1000 else f"{int(round(meters))} m")
        target = step.get("target") or {}
        if target.get("type") == "heart_rate_zone":
            part.append(f"{'HF' if de else 'HR'} Z{target.get('zone')}")
        elif target.get("type") == "power_zone":
            part.append(f"Power Z{target.get('zone')}")
        return " · ".join(p for p in part if p)
    return [f"• {one(s)}" for s in steps]


async def calendar_events(db, user, *, include_activities: bool) -> list[dict]:
    today = user_today(user)
    zone = user_zone(user)
    de = (user.locale or "de").startswith("de")
    events = []
    for schedule, run in await _schedules(db, user):
        plan = TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"])
        for s in scheduled_sessions(run, schedule):
            day = date.fromisoformat(s["date"])
            if day < today - timedelta(days=30) or day > today + timedelta(days=400):
                continue
            lines = [f"{plan.title}", f"{s['duration_min']} min"] + _steps_text(s.get("steps") or [], de)
            if s.get("notes"):
                lines += ["", s["notes"]]
            event = {"uid": f"session:{run.id}:{s['id']}", "title": f"{SPORT_ICON.get(s['sport'], '●')} {s['name']} · {s['duration_min']} min",
                     "description": "\n".join(lines), "category": "Training"}
            if s.get("start_time"):
                hour, minute = map(int, s["start_time"].split(":"))
                event.update(start=datetime.combine(day, time(hour, minute), tzinfo=zone), minutes=s["duration_min"])
            else:
                event.update(date=day, transparent=True)
            events.append(event)
    for race in (await db.scalars(select(RaceEvent).where(RaceEvent.user_id == user.id, RaceEvent.date >= today - timedelta(days=30)))).all():
        detail = [f"{race.distance_km:g} km" if race.distance_km else "", ]
        if race.target_seconds:
            h, rest = divmod(race.target_seconds, 3600)
            detail.append(("Ziel " if de else "Target ") + (f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"))
        events.append({"uid": f"race:{race.id}", "title": f"🏁 {race.name}", "date": race.date, "category": "Wettkampf" if de else "Race",
                       "description": "\n".join(x for x in detail + [race.notes or ""] if x)})
    if include_activities:
        for a in await _activities(db, user, today - timedelta(days=60), today):
            if not a.started_at:
                continue
            distance = f" · {a.distance_m / 1000:.1f} km" if a.distance_m else ""
            events.append({"uid": f"activity:{a.id}", "title": f"✓ {SPORT_ICON.get(sport_family(a.sport_type), '●')} {a.name or a.sport_type}{distance}",
                           "start": a.started_at if a.started_at.tzinfo else a.started_at.replace(tzinfo=timezone.utc),
                           "minutes": max(5, round(_minutes(a))), "category": "Aktivität" if de else "Activity"})
    return events


def _ics_response(body: str, *, download: bool) -> Response:
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="pengucoach.ics"'
    return Response(content=body, media_type="text/calendar; charset=utf-8", headers=headers)


@router.get("/export.ics")
async def export_ics(include_activities: bool = False, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    events = await calendar_events(db, user, include_activities=include_activities)
    return _ics_response(ics_calendar(events, name="PenguCoach"), download=True)


@router.get("/feed/{user_id}/{token}.ics")
async def public_feed(user_id: uuid.UUID, token: str, db: AsyncSession = Depends(get_db)):
    """Subscription for iPhone, Android (Google) and Outlook calendars. The secret link is the only key."""
    user = await db.get(User, user_id)
    pref = await db.get(UserPreference, user_id) if user else None
    cfg = _feed_config(pref)
    expected = cfg.get("hash") or ""
    if not user or user.status != "active" or not expected or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected):
        raise HTTPException(404, "NOT_FOUND")
    events = await calendar_events(db, user, include_activities=bool(cfg.get("include_activities")))
    return _ics_response(ics_calendar(events, name="PenguCoach"), download=False)
