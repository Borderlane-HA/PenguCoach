"""User-owned coach memory/history and local training calendar, independent of Garmin."""
import copy
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.companion import briefing, compare_sessions, scheduled_sessions, sport_family
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachCheckin, CoachMemory, CoachProfile, Conversation, GarminWorkoutExport, Message, PlanSchedule, User
from pengucoach.db.session import get_db
from pengucoach.training_plan.structured import TrainingPlanDocument

router = APIRouter(prefix="/coach", tags=["companion"])


class ProfileIn(BaseModel):
    enabled: bool = True
    goal: str = Field(default="", max_length=1000)
    target_date: date | None = None
    preferred_sports: str = Field(default="", max_length=300)
    training_days: list[int] = Field(default_factory=list, max_length=7)
    session_minutes: int = Field(default=45, ge=5, le=480)
    equipment: str = Field(default="", max_length=600)
    constraints: str = Field(default="", max_length=1000)
    milestones: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def valid_days(self):
        if any(d < 1 or d > 7 for d in self.training_days) or len(set(self.training_days)) != len(self.training_days):
            raise ValueError("Training days must be unique ISO weekdays")
        return self


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class CheckinIn(BaseModel):
    energy: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    minutes: int | None = Field(default=None, ge=0, le=480)
    discomfort: str = Field(default="", max_length=500)


class FeedbackIn(BaseModel):
    feeling: Literal["easy", "right", "hard"] = "right"
    exertion: int | None = Field(default=None, ge=1, le=10)
    comment: str = Field(default="", max_length=1000)


async def owned(db, model, identifier, user, error="NOT_FOUND"):
    row = await db.get(model, identifier)
    if not row or row.user_id != user.id:
        raise HTTPException(404, error)
    return row


@router.get("/profile")
async def profile(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(CoachProfile, user.id)
    return row.data if row else ProfileIn().model_dump(mode="json")


@router.put("/profile")
async def save_profile(payload: ProfileIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(CoachProfile, user.id)
    if not row:
        row = CoachProfile(user_id=user.id)
        db.add(row)
    row.data = payload.model_dump(mode="json")
    await db.commit()
    return row.data


@router.delete("/profile")
async def clear_profile(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(CoachProfile).where(CoachProfile.user_id == user.id))
    await db.execute(delete(CoachMemory).where(CoachMemory.user_id == user.id))
    await db.commit()
    return {"deleted": True}


def memory_payload(m):
    return {"id": str(m.id), "content": m.content, "updated_at": m.updated_at}


@router.get("/memories")
async def memories(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(CoachMemory).where(CoachMemory.user_id == user.id).order_by(CoachMemory.updated_at.desc()))).all()
    return [memory_payload(m) for m in rows]


@router.post("/memories")
async def save_memory(payload: MemoryIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, "MEMORY_EMPTY")
    rows = (await db.scalars(select(CoachMemory).where(CoachMemory.user_id == user.id))).all()
    if len(rows) >= 30:
        raise HTTPException(409, "MEMORY_LIMIT_30")
    if sum(len(m.content) for m in rows) + len(content) > 6000:
        raise HTTPException(409, "MEMORY_LIMIT_6000_CHARS")
    row = CoachMemory(user_id=user.id, content=content)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return memory_payload(row)


@router.put("/memories/{memory_id}")
async def edit_memory(memory_id: uuid.UUID, payload: MemoryIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await owned(db, CoachMemory, memory_id, user)
    if not payload.content.strip():
        raise HTTPException(422, "MEMORY_EMPTY")
    size = await db.scalar(select(func.sum(func.length(CoachMemory.content))).where(CoachMemory.user_id == user.id, CoachMemory.id != memory_id))
    if (size or 0) + len(payload.content.strip()) > 6000:
        raise HTTPException(409, "MEMORY_LIMIT_6000_CHARS")
    row.content = payload.content.strip()
    await db.commit()
    await db.refresh(row)
    return memory_payload(row)


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await owned(db, CoachMemory, memory_id, user)
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.get("/check-in")
async def get_checkin(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    today = user_today(user)
    row = await db.scalar(select(CoachCheckin).where(CoachCheckin.user_id == user.id, CoachCheckin.date == today))
    return {"date": today, **(row.data if row else CheckinIn().model_dump())}


@router.put("/check-in")
async def save_checkin(payload: CheckinIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    today = user_today(user)
    row = await db.scalar(select(CoachCheckin).where(CoachCheckin.user_id == user.id, CoachCheckin.date == today))
    if not row:
        row = CoachCheckin(user_id=user.id, date=today)
        db.add(row)
    row.data = payload.model_dump()
    await db.commit()
    return {"date": today, **row.data}


@router.delete("/check-in")
async def delete_checkin(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(CoachCheckin).where(CoachCheckin.user_id == user.id, CoachCheckin.date == user_today(user)))
    await db.commit()
    return {"deleted": True}


@router.get("/feedback/{activity_id}")
async def get_feedback(activity_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await owned(db, Activity, activity_id, user)
    row = await db.get(ActivityFeedback, activity_id)
    return row.data if row else {}


@router.put("/feedback/{activity_id}")
async def save_feedback(activity_id: uuid.UUID, payload: FeedbackIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await owned(db, Activity, activity_id, user)
    row = await db.get(ActivityFeedback, activity_id)
    if not row:
        row = ActivityFeedback(activity_id=activity_id, user_id=user.id)
        db.add(row)
    row.data = payload.model_dump()
    await db.commit()
    return row.data


@router.delete("/feedback/{activity_id}")
async def delete_feedback(activity_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await owned(db, Activity, activity_id, user)
    await db.execute(delete(ActivityFeedback).where(ActivityFeedback.activity_id == activity_id, ActivityFeedback.user_id == user.id))
    await db.commit()
    return {"deleted": True}


@router.get("/briefing")
async def get_briefing(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await briefing(db, user)


@router.get("/conversations")
async def conversations(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc(), Conversation.id).offset(offset).limit(limit))).all()
    return [{"id": str(r.id), "title": r.title, "updated_at": r.updated_at} for r in rows]


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, before: datetime | None = None, before_id: uuid.UUID | None = None, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await owned(db, Conversation, conversation_id, user, "CONVERSATION_NOT_FOUND")
    query = select(Message).where(Message.conversation_id == row.id)
    if before:
        query = query.where(or_(Message.created_at < before, and_(Message.created_at == before, Message.id < before_id))) if before_id else query.where(Message.created_at < before)
    messages = list((await db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(201))).all())
    has_more = len(messages) > 200
    messages = list(reversed(messages[:200]))
    return {"id": str(row.id), "title": row.title, "summary": row.summary, "has_more": has_more, "messages": [{"id": str(m.id), "role": m.role, "content": m.content, "created_at": m.created_at, "metadata": m.metadata_json} for m in messages]}


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: uuid.UUID, payload: MemoryIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await owned(db, Conversation, conversation_id, user)
    row.title = payload.content.strip()[:80] or "PenguCoach"
    await db.commit()
    return {"title": row.title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await owned(db, Conversation, conversation_id, user)
    await db.execute(delete(Message).where(Message.conversation_id == row.id))
    # Alpha.39 chat runs are linked to the conversation for complete deletion.
    runs = (await db.scalars(select(AiRun).where(AiRun.user_id == user.id, AiRun.task_type == "coach_chat"))).all()
    for run in runs:
        if (run.metadata_json or {}).get("conversation_id") == str(row.id):
            await db.delete(run)
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


class ScheduleIn(BaseModel):
    start_date: date
    overrides: dict = Field(default_factory=dict)
    revision: int = Field(default=0, ge=0)


async def plan_owned(db, user, run_id):
    run = await owned(db, AiRun, run_id, user, "TRAINING_PLAN_NOT_FOUND")
    if run.task_type != "training_plan" or not (run.metadata_json or {}).get("structured_plan"):
        raise HTTPException(409, "STRUCTURED_PLAN_REQUIRED")
    return run


def validate_overrides(run, overrides):
    original = TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"])
    if set(overrides) - {s.id for s in original.sessions}:
        raise HTTPException(422, "UNKNOWN_SESSION")
    try:
        document = original.model_dump()
        document["sessions"] = [overrides.get(s.id) or s.model_dump() for s in original.sessions]
        result = TrainingPlanDocument.model_validate(document)
        if [s.id for s in result.sessions] != [s.id for s in original.sessions]:
            raise ValueError("Session ids must stay unchanged")
        return {s.id: s.model_dump() for s in result.sessions if s.id in overrides}
    except ValueError as exc:
        raise HTTPException(422, "INVALID_SESSION_OVERRIDES") from exc


async def guard_exported(db, user, run, previous, start, overrides):
    exports = list((await db.scalars(select(GarminWorkoutExport).where(GarminWorkoutExport.user_id == user.id, GarminWorkoutExport.plan_run_id == run.id))).all())
    original = {s.id: s.model_dump() for s in TrainingPlanDocument.model_validate(run.metadata_json["structured_plan"]).sessions}
    for item in exports:
        if item.status == "exported" or item.workout_id or item.scheduled_workout_id:
            old = (previous.overrides or {}).get(item.session_id, original.get(item.session_id)) if previous else original.get(item.session_id)
            new = overrides.get(item.session_id, original.get(item.session_id))
            scheduled = start + timedelta(weeks=new["week"] - 1, days=new["day"] - 1) if new else None
            if old != new or (previous and previous.start_date != start) or (item.scheduled_date and item.scheduled_date != scheduled):
                raise HTTPException(409, "EXPORTED_SESSION_LOCKED")


@router.get("/plans/{run_id}/schedule")
async def get_schedule(run_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await plan_owned(db, user, run_id)
    row = await db.get(PlanSchedule, run_id)
    return {"start_date": row.start_date, "overrides": row.overrides, "revision": row.revision} if row else {"start_date": None, "overrides": {}, "revision": 0}


@router.put("/plans/{run_id}/schedule")
async def save_schedule(run_id: uuid.UUID, payload: ScheduleIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    run = await plan_owned(db, user, run_id)
    row = await db.scalar(select(PlanSchedule).where(PlanSchedule.plan_run_id == run_id).with_for_update())
    if (row.revision if row else 0) != payload.revision:
        raise HTTPException(409, "SCHEDULE_CHANGED_RELOAD")
    if payload.start_date.weekday() != 0:
        raise HTTPException(422, "START_DATE_MUST_BE_MONDAY")
    overrides = validate_overrides(run, payload.overrides)
    await guard_exported(db, user, run, row, payload.start_date, overrides)
    if not row:
        row = PlanSchedule(plan_run_id=run_id, user_id=user.id, revision=0)
        db.add(row)
    row.start_date, row.overrides, row.revision = payload.start_date, overrides, row.revision + 1
    await db.commit()
    return {"start_date": row.start_date, "overrides": row.overrides, "revision": row.revision}


@router.get("/plans/{run_id}/comparison")
async def comparison(run_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    run = await plan_owned(db, user, run_id)
    schedule = await db.get(PlanSchedule, run_id)
    if not schedule:
        return {"items": [], "needs_schedule": True}
    sessions = scheduled_sessions(run, schedule)
    start, end = min(s["date"] for s in sessions), max(s["date"] for s in sessions)
    activities = (await db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.started_at >= day_start(date.fromisoformat(start), user), Activity.started_at < day_start(date.fromisoformat(end) + timedelta(days=1), user)))).all()
    items = compare_sessions(sessions, activities, user)
    for item in items:
        if item["activity_id"]:
            a = next(a for a in activities if str(a.id) == item["activity_id"])
            feedback = await db.get(ActivityFeedback, a.id)
            item.update(avg_hr=a.avg_hr, training_load=a.training_load, aerobic_effect=a.aerobic_training_effect, feedback=feedback.data if feedback else None)
    return {"items": items, "revision": schedule.revision}


class AdaptIn(BaseModel):
    session_id: str = Field(max_length=80)
    action: Literal["postpone", "easy"]
    revision: int
    apply: bool = False
    expected_after: dict | None = None


@router.post("/plans/{run_id}/adapt")
async def adapt(run_id: uuid.UUID, payload: AdaptIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    run = await plan_owned(db, user, run_id)
    schedule = await db.get(PlanSchedule, run_id)
    if not schedule or schedule.revision != payload.revision:
        raise HTTPException(409, "SCHEDULE_CHANGED_RELOAD")
    sessions = scheduled_sessions(run, schedule)
    before = next((s for s in sessions if s["id"] == payload.session_id), None)
    if not before:
        raise HTTPException(404, "SESSION_NOT_FOUND")
    after = copy.deepcopy(before)
    if payload.action == "postpone":
        # First free future day, within plan bounds; never overwrite another session.
        occupied = {s["date"] for s in sessions if s["id"] != before["id"]}
        target = max(date.fromisoformat(before["date"]) + timedelta(days=1), user_today(user))
        profile = await db.get(CoachProfile, user.id)
        allowed = (profile.data or {}).get("training_days", []) if profile else []
        while target.isoformat() in occupied or (allowed and target.isoweekday() not in allowed):
            target += timedelta(days=1)
        offset = (target - schedule.start_date).days
        if offset < 0 or offset // 7 + 1 > run.metadata_json["structured_plan"]["weeks"]:
            raise HTTPException(409, "NO_FREE_DAY_IN_PLAN")
        after.update(week=offset // 7 + 1, day=offset % 7 + 1, date=target.isoformat())
    else:
        after.update(name="Lockere Bewegung / Easy movement", sport="walking", duration_min=min(30, before["duration_min"]), steps=[{"type": "work", "duration_seconds": min(30, before["duration_min"]) * 60, "target": {"type": "none"}}], strength_exercises=[], notes="Optional ruhige Bewegung; bei Beschwerden auslassen. / Optional easy movement; skip if uncomfortable.")
    overrides = {**schedule.overrides, after["id"]: {k: v for k, v in after.items() if k != "date"}}
    overrides = validate_overrides(run, overrides)
    await guard_exported(db, user, run, schedule, schedule.start_date, overrides)
    if payload.apply and payload.expected_after != after:
        raise HTTPException(409, "PROPOSAL_CHANGED_REVIEW_AGAIN")
    if payload.apply:
        await save_schedule(run_id, ScheduleIn(start_date=schedule.start_date, overrides=overrides, revision=payload.revision), user, db)
    return {"before": before, "after": after, "applied": payload.apply, "revision": schedule.revision}


@router.get("/data-quality")
async def data_quality(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    # Review only: duplicate detection must never delete real sessions automatically.
    rows = list((await db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.started_at >= day_start(user_today(user) - timedelta(days=27), user)).order_by(Activity.started_at).limit(1000))).all())
    pairs = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            delta = abs((a.started_at - b.started_at).total_seconds())
            if delta > 120:
                break
            if sport_family(a.sport_type) == sport_family(b.sport_type) and a.duration_seconds and b.duration_seconds and abs(a.duration_seconds - b.duration_seconds) <= max(60, a.duration_seconds * .03):
                pairs.append({"first_id": str(a.id), "second_id": str(b.id), "name": a.name or a.sport_type, "started_at": a.started_at})
    return {"days": 28, "possible_duplicates": pairs[:30], "checked": len(rows), "limited": len(rows) == 1000}


class QuickSessionIn(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=120)
    sport: Literal["running", "cycling", "swimming", "walking", "hiking", "strength", "mobility", "yoga", "other"]
    duration_min: int = Field(ge=5, le=240)
    notes: str = Field(default="", max_length=1500)


@router.post("/quick-session")
async def quick_session(payload: QuickSessionIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    from pengucoach.training_plan.structured import render_plan_markdown
    if payload.date < user_today(user):
        raise HTTPException(422, "SESSION_DATE_IN_PAST")
    document = TrainingPlanDocument.model_validate({"title": payload.name, "weeks": 1, "summary": "Vom Nutzer aus dem Coach übernommene Einheit / Session confirmed by the user.", "sessions": [{"id": "coach-session", "week": 1, "day": payload.date.isoweekday(), "name": payload.name, "sport": payload.sport, "duration_min": payload.duration_min, "notes": payload.notes}]})
    run = AiRun(user_id=user.id, task_type="training_plan", provider_name="PenguCoach", model_name="User", prompt="User-confirmed coach suggestion", content=render_plan_markdown(document, str(user.locale)), metadata_json={"structured_plan": document.model_dump(), "source": "user_confirmed"})
    db.add(run)
    await db.flush()
    db.add(PlanSchedule(plan_run_id=run.id, user_id=user.id, start_date=payload.date-timedelta(days=payload.date.weekday()), overrides={}, revision=1))
    await db.commit()
    return {"run_id": str(run.id)}
