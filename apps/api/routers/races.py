"""Race mode (alpha.85): competitions, countdown, prognosis and a taper the user confirms."""
from __future__ import annotations

import copy
import uuid
import datetime as dt
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.calendar import _schedules
from apps.api.routers.companion import guard_exported, plan_owned, validate_overrides
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach import races as logic
from pengucoach.coach.companion import activity_day, scheduled_sessions
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, PlanSchedule, RaceEvent, User
from pengucoach.db.session import get_db
from pengucoach.training_plan.structured import TrainingPlanDocument

router = APIRouter(prefix="/races", tags=["races"])


class RaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    date: dt.date
    sport: Literal["running", "cycling", "swimming", "triathlon", "hiking", "other"] = "running"
    distance_km: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    target_seconds: int | None = Field(default=None, gt=0, le=7 * 86400)
    priority: Literal["A", "B", "C"] = "A"
    notes: str = Field(default="", max_length=1500)

    @field_validator("name", "notes")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()


async def _owned(db, user, race_id) -> RaceEvent:
    race = await db.get(RaceEvent, race_id)
    if not race or race.user_id != user.id:
        raise HTTPException(404, "RACE_NOT_FOUND")
    return race


async def _recent_activities(db, user, race: RaceEvent | None = None):
    today = user_today(user)
    start = min(today - timedelta(days=logic.PROGNOSIS_WINDOW_DAYS + 1), (race.date if race else today))
    end = max(today, race.date if race else today) + timedelta(days=1)
    return list((await db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.started_at >= day_start(start, user),
                                                        Activity.started_at < day_start(end, user)))).all())


def _payload(race: RaceEvent, user, activities, today: date) -> dict:
    day_of = lambda a: activity_day(a, user)  # noqa: E731
    info = logic.phase(race.date, today, race.sport, race.distance_km)
    data = race.data or {}
    return {"id": str(race.id), "name": race.name, "date": race.date.isoformat(), "sport": race.sport,
            "distance_km": race.distance_km, "target_seconds": race.target_seconds, "priority": race.priority, "notes": race.notes,
            "phase": info, "prognosis": logic.prognosis(race, activities, today, day_of) if info["key"] not in {"done", "past"} else None,
            "result": logic.result(race, activities, day_of) if info["key"] in {"race", "done", "past"} else None,
            "taper_applied_at": data.get("taper_applied_at")}


@router.get("")
async def list_races(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    today = user_today(user)
    rows = list((await db.scalars(select(RaceEvent).where(RaceEvent.user_id == user.id, RaceEvent.date >= today - timedelta(days=365)).order_by(RaceEvent.date))).all())
    activities = await _recent_activities(db, user)
    past_ids = {r.id for r in rows if r.date < today}
    extra = list((await db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.started_at >= day_start(today - timedelta(days=366), user))))) if past_ids else []
    by_id = {a.id: a for a in activities + extra}
    return {"items": [_payload(r, user, list(by_id.values()), today) for r in rows], "presets": logic.PRESETS, "today": today.isoformat()}


@router.get("/next")
async def next_race(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    """The race Today shows: the main goal (A); without an A race the next B race. C races stay in the calendar.

    Shows the upcoming one, or one finished in the last week (with its result).
    """
    today = user_today(user)
    rows = list((await db.scalars(select(RaceEvent).where(RaceEvent.user_id == user.id, RaceEvent.date >= today - timedelta(days=7)).order_by(RaceEvent.date))).all())
    main = [r for r in rows if r.priority == "A"] or [r for r in rows if r.priority == "B"]
    rows = main
    upcoming = [r for r in rows if r.date >= today]
    race = upcoming[0] if upcoming else (rows[-1] if rows else None)
    if not race:
        return {"race": None}
    activities = await _recent_activities(db, user, race)
    result = _payload(race, user, activities, today)
    if result["phase"]["key"] in {"peak", "taper"} and not result["taper_applied_at"] and race.priority == "A":
        proposals = await _proposals(db, user, race, today)
        result["taper_changes"] = sum(len(p["changes"]) for p in proposals)
    return {"race": result}


@router.post("")
async def create_race(payload: RaceIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    race = RaceEvent(user_id=user.id, data={}, **payload.model_dump())
    db.add(race)
    await db.commit()
    return _payload(race, user, await _recent_activities(db, user, race), user_today(user))


@router.put("/{race_id}")
async def update_race(race_id: uuid.UUID, payload: RaceIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    race = await _owned(db, user, race_id)
    for key, value in payload.model_dump().items():
        setattr(race, key, value)
    await db.commit()
    return _payload(race, user, await _recent_activities(db, user, race), user_today(user))


@router.delete("/{race_id}")
async def delete_race(race_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    race = await _owned(db, user, race_id)
    await db.delete(race)
    await db.commit()
    return {"deleted": True}


async def _proposals(db, user, race: RaceEvent, today: date) -> list[dict]:
    result = []
    for schedule, run in await _schedules(db, user):
        sessions = scheduled_sessions(run, schedule)
        changes = logic.taper_proposal(race, sessions, today)
        if changes:
            plan = TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"])
            result.append({"plan_id": str(run.id), "plan_title": plan.title, "revision": schedule.revision, "changes": changes})
    return result


@router.get("/{race_id}/taper")
async def taper(race_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    race = await _owned(db, user, race_id)
    today = user_today(user)
    info = logic.phase(race.date, today, race.sport, race.distance_km)
    return {"race": {"id": str(race.id), "name": race.name, "date": race.date.isoformat()}, "phase": info,
            "plans": await _proposals(db, user, race, today), "applied_at": (race.data or {}).get("taper_applied_at")}


class TaperPlan(BaseModel):
    plan_id: uuid.UUID
    revision: int = Field(ge=0)
    session_ids: list[str] | None = Field(default=None, max_length=200)


class TaperApply(BaseModel):
    plans: list[TaperPlan] = Field(min_length=1, max_length=10)


@router.post("/{race_id}/taper")
async def apply_taper(race_id: uuid.UUID, payload: TaperApply, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    """Apply the confirmed proposal. Sessions already on the Garmin watch stay as they are and are reported."""
    race = await _owned(db, user, race_id)
    today = user_today(user)
    applied, locked = 0, []
    for item in payload.plans:
        run = await plan_owned(db, user, item.plan_id)
        row = await db.scalar(select(PlanSchedule).where(PlanSchedule.plan_run_id == item.plan_id, PlanSchedule.user_id == user.id).with_for_update())
        if not row:
            raise HTTPException(409, "PLAN_NOT_SCHEDULED")
        if row.revision != item.revision:
            raise HTTPException(409, "SCHEDULE_CHANGED_RELOAD")
        sessions = scheduled_sessions(run, row)
        changes = [c for c in logic.taper_proposal(race, sessions, today) if item.session_ids is None or c["session_id"] in item.session_ids]
        plan = TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"])
        base = {s.id: copy.deepcopy((row.overrides or {}).get(s.id) or s.model_dump()) for s in plan.sessions}
        overrides = copy.deepcopy(row.overrides or {})
        for change in changes:
            candidate = copy.deepcopy(overrides)
            session = dict(base[change["session_id"]])
            if change["action"] == "skip":
                session["skipped"] = True
            else:
                session.update(change["update"])
            candidate[change["session_id"]] = session
            try:
                checked = validate_overrides(run, candidate)
                await guard_exported(db, user, run, row, row.start_date, checked)
            except HTTPException as exc:
                if exc.detail == "EXPORTED_SESSION_LOCKED":
                    locked.append({"plan_id": str(run.id), "session_id": change["session_id"], "name": change["name"], "date": change["date"]})
                    continue
                raise
            overrides = checked
            applied += 1
        if overrides != (row.overrides or {}):
            row.overrides, row.revision = overrides, row.revision + 1
    race.data = {**(race.data or {}), "taper_applied_at": datetime.now(timezone.utc).isoformat(), "taper_applied_changes": applied}
    await db.commit()
    return {"applied": applied, "locked": locked}
