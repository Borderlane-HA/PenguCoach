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
from pengucoach.coach.training_intelligence import plan_intelligence, training_load_summary
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachCheckin, CoachDecisionLog, CoachMemory, CoachProfile, Conversation, GarminWorkoutExport, Message, PlanSchedule, User
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
    preferences: str = Field(default="", max_length=1000)
    avoidances: str = Field(default="", max_length=1000)
    milestones: str = Field(default="", max_length=1000)
    dismissed_memory_suggestions: list[str] = Field(default_factory=list, max_length=20)

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
    discomfort: str = Field(default="", max_length=500)
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


@router.get("/training-load")
async def get_training_load(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await training_load_summary(db, user)


async def _memory_suggestion_candidates(db: AsyncSession, user: User) -> list[dict]:
    profile_row = await db.get(CoachProfile, user.id)
    profile = dict(profile_row.data or {}) if profile_row else {}
    dismissed = set(profile.get("dismissed_memory_suggestions") or [])
    existing = [str(x).casefold() for x in (await db.scalars(select(CoachMemory.content).where(CoachMemory.user_id == user.id))).all()]
    since = datetime.now(timezone.utc) - timedelta(days=90)
    logs = list((await db.scalars(select(CoachDecisionLog).where(CoachDecisionLog.user_id == user.id, CoachDecisionLog.created_at >= since))).all())
    feedback_rows = list((await db.execute(
        select(ActivityFeedback, Activity).join(Activity, Activity.id == ActivityFeedback.activity_id).where(
            ActivityFeedback.user_id == user.id, Activity.started_at >= since
        )
    )).all())
    candidates = []
    indoor_count = sum(1 for row in logs if row.action == "indoor")
    if indoor_count >= 2:
        candidates.append({
            "key": "prefer_indoor_bad_weather",
            "text": "Bei ungünstigem Wetter bevorzuge ich eine passende Indoor-Alternative.",
            "reason": "confirmed_indoor_adaptations",
            "evidence_count": indoor_count,
        })
    hard_count = sum(1 for feedback, _ in feedback_rows if (feedback.data or {}).get("feeling") == "hard" or int((feedback.data or {}).get("exertion") or 0) >= 9)
    if hard_count >= 3:
        candidates.append({
            "key": "conservative_after_hard_feedback",
            "text": "Wenn sich mehrere Einheiten zu hart anfühlen, soll mein Coach die nächste Belastung eher konservativ planen.",
            "reason": "repeated_hard_feedback",
            "evidence_count": hard_count,
        })
    result = []
    for item in candidates:
        if item["key"] in dismissed:
            continue
        if any(item["text"].casefold() == value for value in existing):
            continue
        result.append(item)
    return result


@router.get("/memory-suggestions")
async def memory_suggestions(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _memory_suggestion_candidates(db, user)


@router.post("/memory-suggestions/{key}/accept")
async def accept_memory_suggestion(key: str, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    candidates = {item["key"]: item for item in await _memory_suggestion_candidates(db, user)}
    item = candidates.get(key)
    if not item:
        raise HTTPException(404, "MEMORY_SUGGESTION_NOT_FOUND")
    return await save_memory(MemoryIn(content=item["text"]), user, db)


@router.post("/memory-suggestions/{key}/dismiss")
async def dismiss_memory_suggestion(key: str, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(CoachProfile, user.id)
    if not row:
        row = CoachProfile(user_id=user.id, data=ProfileIn().model_dump(mode="json"))
        db.add(row)
    data = dict(row.data or {})
    dismissed = list(dict.fromkeys([*(data.get("dismissed_memory_suggestions") or []), key]))[-20:]
    data["dismissed_memory_suggestions"] = dismissed
    row.data = data
    await db.commit()
    return {"dismissed": True, "key": key}


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
    from pengucoach.coach.plan_evolution import comparison_data
    comparison_result = await comparison_data(db, user, run, schedule)
    items = comparison_result["items"]
    brief = await briefing(db, user)
    readiness = brief.get("readiness") or {}
    suggestions = []
    for item in items:
        if item["status"] == "unmatched" and date.fromisoformat(item["date"]) >= user_today(user) - timedelta(days=14):
            suggestions.append({"session_id": item["id"], "action": "postpone", "reason": "missed_session", "priority": 70})
        elif item["status"] == "planned" and item["date"] == brief.get("date"):
            if readiness.get("recommendation") == "check_discomfort":
                suggestions.append({"session_id": item["id"], "action": "postpone", "reason": "readiness_discomfort", "priority": 100})
            elif readiness.get("status") == "red":
                suggestions.append({"session_id": item["id"], "action": "easy", "reason": "readiness_red", "priority": 90})
            elif readiness.get("status") == "yellow":
                suggestions.append({"session_id": item["id"], "action": "reduce", "reason": "readiness_yellow", "priority": 80})
    intelligence = await plan_intelligence(db, user, run_id, sessions)
    for session_id, info in (intelligence.get("sessions") or {}).items():
        weather = info.get("weather") or {}
        if weather.get("indoor_recommended") and date.fromisoformat(info["date"]) >= user_today(user):
            suggestions.append({"session_id": session_id, "action": "indoor", "reason": "weather_unfavorable", "priority": 75})
    for conflict in intelligence.get("conflicts") or []:
        if conflict.get("session_id") and conflict.get("proposed_action"):
            suggestions.append({"session_id": conflict["session_id"], "action": conflict["proposed_action"], "reason": f"conflict_{conflict['type']}", "priority": 65})
    dedup = {}
    for suggestion in suggestions:
        key = (suggestion["session_id"], suggestion["action"])
        if key not in dedup or suggestion["priority"] > dedup[key]["priority"]:
            dedup[key] = suggestion
    suggestions = sorted(dedup.values(), key=lambda x: (-x["priority"], x["session_id"]))
    logs = list((await db.scalars(select(CoachDecisionLog).where(CoachDecisionLog.user_id == user.id, CoachDecisionLog.plan_run_id == run_id).order_by(CoachDecisionLog.created_at.desc()).limit(20))).all())
    decision_log = [{"id": str(row.id), "session_id": row.session_id, "action": row.action, "before": row.before, "after": row.after, "reasons": row.reasons, "created_at": row.created_at} for row in logs]
    return {"items": items, "freshness": comparison_result["freshness"], "revision": schedule.revision, "date": brief.get("date"), "readiness": readiness, "adaptive_suggestions": suggestions[:8], "conflicts": intelligence.get("conflicts", []), "session_intelligence": intelligence.get("sessions", {}), "weather": intelligence.get("weather", {}), "training_load": intelligence.get("load", {}), "decision_log": decision_log}


@router.get("/plans/{run_id}/intelligence")
async def get_plan_intelligence(run_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    run = await plan_owned(db, user, run_id)
    schedule = await db.get(PlanSchedule, run_id)
    virtual = False
    if not schedule:
        raw_start = ((run.metadata_json or {}).get("goal") or {}).get("start_date")
        try:
            generated_start = date.fromisoformat(str(raw_start)) if raw_start else None
        except ValueError:
            generated_start = None
        if not generated_start or generated_start.weekday() != 0:
            return {"needs_schedule": True, "load": await training_load_summary(db, user), "sessions": {}, "conflicts": [], "weather": {"available": False}}
        # Use the generated plan start for a read-only preview. The row is never
        # added to the session, so merely opening a plan does not persist data.
        schedule = PlanSchedule(plan_run_id=run_id, user_id=user.id, start_date=generated_start, overrides={}, revision=0)
        virtual = True
    result = await plan_intelligence(db, user, run_id, scheduled_sessions(run, schedule))
    result["needs_schedule"] = virtual
    result["preview_schedule"] = virtual
    result["revision"] = schedule.revision
    return result


@router.get("/plans/{run_id}/decision-log")
async def get_decision_log(run_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await plan_owned(db, user, run_id)
    rows = list((await db.scalars(select(CoachDecisionLog).where(CoachDecisionLog.user_id == user.id, CoachDecisionLog.plan_run_id == run_id).order_by(CoachDecisionLog.created_at.desc()).limit(100))).all())
    return [{"id": str(row.id), "session_id": row.session_id, "action": row.action, "before": row.before, "after": row.after, "reasons": row.reasons, "created_at": row.created_at} for row in rows]


class AdaptIn(BaseModel):
    session_id: str = Field(max_length=80)
    action: Literal["postpone", "easy", "reduce", "indoor"]
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
    elif payload.action == "easy":
        after.update(name="Lockere Bewegung / Easy movement", sport="walking", duration_min=min(30, before["duration_min"]), steps=[{"type": "work", "duration_seconds": min(30, before["duration_min"]) * 60, "target": {"type": "none"}}], strength_exercises=[], notes="Optional ruhige Bewegung; bei Beschwerden auslassen. / Optional easy movement; skip if uncomfortable.")
    elif payload.action == "indoor":
        label = "Indoor Bike" if before.get("sport") == "cycling" else "Laufband / Treadmill" if before.get("sport") == "running" else "Indoor Alternative"
        after.update(name=(f"{label} · {before['name']}")[:120], notes=(before.get("notes", "") + "\nWetterbedingte Indoor-Alternative; Trainingsreiz möglichst beibehalten. / Weather-based indoor alternative; keep the intended training stimulus where practical.").strip()[:1500])
    else:
        reduced_minutes = max(5, int(round(before["duration_min"] * 0.75)))
        if before.get("sport") == "strength":
            exercises = copy.deepcopy(before.get("strength_exercises") or [])
            for exercise in exercises:
                exercise["sets"] = max(1, int(round(exercise.get("sets", 1) * 0.67)))
            after.update(name=(f"Reduziert / Reduced · {before['name']}")[:120], duration_min=reduced_minutes, strength_exercises=exercises, notes=(before.get("notes", "") + "\nVolumen bewusst reduziert; Qualität vor Umfang. / Volume deliberately reduced; quality over quantity.").strip()[:1500])
        else:
            after.update(name=(f"Locker reduziert / Easy reduced · {before['name']}")[:120], duration_min=reduced_minutes, steps=[{"type": "work", "duration_seconds": reduced_minutes * 60, "target": {"type": "none"}, "description": "Locker / Easy"}], notes=(before.get("notes", "") + "\nIntensität und Umfang bewusst reduziert. / Intensity and volume deliberately reduced.").strip()[:1500])
    overrides = {**schedule.overrides, after["id"]: {k: v for k, v in after.items() if k != "date"}}
    overrides = validate_overrides(run, overrides)
    await guard_exported(db, user, run, schedule, schedule.start_date, overrides)
    if payload.apply and payload.expected_after != after:
        raise HTTPException(409, "PROPOSAL_CHANGED_REVIEW_AGAIN")
    if payload.apply:
        reasons = [{"type": "action", "value": payload.action}]
        brief = await briefing(db, user)
        readiness = brief.get("readiness") or {}
        if payload.action in {"easy", "reduce", "postpone"} and readiness.get("status") in {"yellow", "red"}:
            reasons.append({"type": "readiness", "status": readiness.get("status"), "score": readiness.get("score")})
            for factor in (readiness.get("factors") or [])[:5]:
                reasons.append({"type": "readiness_factor", **factor})
        if payload.action == "indoor":
            intelligence = await plan_intelligence(db, user, run_id, sessions)
            weather = ((intelligence.get("sessions") or {}).get(before["id"]) or {}).get("weather")
            if weather:
                reasons.append({"type": "weather", **weather})
        await save_schedule(run_id, ScheduleIn(start_date=schedule.start_date, overrides=overrides, revision=payload.revision), user, db)
        db.add(CoachDecisionLog(user_id=user.id, plan_run_id=run_id, session_id=before["id"], action=payload.action, before=before, after=after, reasons=reasons))
        await db.commit()
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
