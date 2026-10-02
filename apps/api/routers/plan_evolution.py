"""Alpha.47: explicit activity matching, short variants and reviewed rolling weeks."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.companion import owned, plan_owned, guard_exported, validate_overrides
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.companion import briefing, scheduled_sessions
from pengucoach.coach.plan_evolution import compare_v2, short_variant, week_proposal, sport_family, local_day, comparison_data, freshness
from pengucoach.coach.training_intelligence import plan_intelligence
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, ActivityFeedback, ActivityMetric, AiRun, CoachDecisionLog, CoachProfile, GarminConnection, GarminWorkoutExport, PlanActivityMatch, PlanSchedule, SparkyFitnessConnection, User
from pengucoach.db.session import get_db
from pengucoach.weather.service import fetch_forecast, weather_config
from pengucoach.db.models import UserPreference

router = APIRouter(prefix="/coach", tags=["plan evolution"])


@router.get("/freshness")
async def get_freshness(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await freshness(db, user)


@router.get("/plans/{run_id}/detail")
async def plan_detail(run_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    from apps.api.routers.coach import _run_payload
    return _run_payload(await plan_owned(db,user,run_id))


async def get_schedule(db, user, run_id, revision, apply=False):
    run = await plan_owned(db,user,run_id)
    query = select(PlanSchedule).where(PlanSchedule.plan_run_id == run.id)
    if apply:
        query = query.with_for_update().execution_options(populate_existing=True)
    schedule = await db.scalar(query)
    if not schedule or schedule.revision != revision:
        raise HTTPException(409,"SCHEDULE_CHANGED_RELOAD")
    return run, schedule


class MatchIn(BaseModel):
    session_id: str = Field(min_length=1,max_length=80)
    activity_id: uuid.UUID | None = None
    state: Literal["matched", "missed"] = "matched"
    revision: int = Field(ge=0)


@router.put("/plans/{run_id}/activity-match")
async def match_activity(run_id: uuid.UUID, payload: MatchIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    run, schedule = await get_schedule(db,user,run_id,payload.revision,True)
    session = next((s for s in scheduled_sessions(run,schedule) if s["id"] == payload.session_id),None)
    if not session:
        raise HTTPException(404,"SESSION_NOT_FOUND")
    if payload.state == "matched":
        if not payload.activity_id:
            raise HTTPException(422,"ACTIVITY_REQUIRED")
        a = await owned(db,Activity,payload.activity_id,user)
        stamp = a.started_at.replace(tzinfo=timezone.utc) if a.started_at and not a.started_at.tzinfo else a.started_at
        if stamp is None or stamp > datetime.now(timezone.utc) or sport_family(a.sport_type) != sport_family(session["sport"]) or abs((local_day(a,user)-date.fromisoformat(session["date"])).days) > 7:
            raise HTTPException(422,"ACTIVITY_DOES_NOT_FIT_SESSION")
        clash = await db.scalar(select(PlanActivityMatch).where(PlanActivityMatch.activity_id == a.id))
        if clash and (clash.plan_run_id != run.id or clash.session_id != session["id"]):
            raise HTTPException(409,"ACTIVITY_ALREADY_ASSIGNED")
    elif payload.activity_id or date.fromisoformat(session["date"]) >= user_today(user):
        raise HTTPException(422,"ONLY_PAST_SESSIONS_CAN_BE_MISSED")
    row = await db.scalar(select(PlanActivityMatch).where(PlanActivityMatch.plan_run_id == run.id,PlanActivityMatch.session_id == session["id"]))
    if row is None:
        row = PlanActivityMatch(user_id=user.id,plan_run_id=run.id,session_id=session["id"])
        db.add(row)
    row.activity_id, row.state = payload.activity_id, payload.state
    schedule.revision += 1
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,"ACTIVITY_ALREADY_ASSIGNED")
    return {"saved": True,"revision":schedule.revision}


@router.delete("/plans/{run_id}/activity-match/{session_id}")
async def clear_match(run_id: uuid.UUID, session_id: str, revision: int, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    _, schedule = await get_schedule(db,user,run_id,revision,True)
    row = await db.scalar(select(PlanActivityMatch).where(PlanActivityMatch.plan_run_id == run_id,PlanActivityMatch.session_id == session_id,PlanActivityMatch.user_id == user.id))
    if row:
        await db.delete(row)
        schedule.revision += 1
        await db.commit()
    return {"deleted": bool(row), "revision":schedule.revision}


async def apply_changes(db,user,run,schedule,items,action,reasons):
    overrides = dict(schedule.overrides or {})
    for item in items:
        if item["before"] != item["after"]:
            overrides[item["after"]["id"]] = {k:v for k,v in item["after"].items() if k != "date"}
    overrides = validate_overrides(run,overrides)
    await guard_exported(db,user,run,schedule,schedule.start_date,overrides)
    for item in items:
        if item["before"] != item["after"]:
            db.add(CoachDecisionLog(user_id=user.id,plan_run_id=run.id,session_id=item["after"]["id"],action=action,before=item["before"],after=item["after"],reasons=[{"type":"rule","value":r} for r in item.get("reasons",reasons)]))
    schedule.overrides = overrides
    schedule.revision += 1
    await db.commit()


class ShortIn(BaseModel):
    session_id: str = Field(min_length=1,max_length=80)
    minutes: int = Field(ge=5,le=480)
    revision: int = Field(ge=0)
    apply: bool = False
    expected_after: dict | None = None


@router.post("/plans/{run_id}/short-variant")
async def review_short(run_id: uuid.UUID,payload: ShortIn,user: User = Depends(safety_confirmed_user),db: AsyncSession = Depends(get_db)):
    run,schedule = await get_schedule(db,user,run_id,payload.revision,payload.apply)
    before = next((s for s in scheduled_sessions(run,schedule) if s["id"] == payload.session_id),None)
    if not before:
        raise HTTPException(404,"SESSION_NOT_FOUND")
    if date.fromisoformat(before["date"]) < user_today(user):
        raise HTTPException(422,"SESSION_DATE_IN_PAST")
    comparison = await comparison_data(db,user,run,schedule)
    if any(s["id"] == before["id"] and s["status"] == "matched" for s in comparison["items"]):
        raise HTTPException(409,"SESSION_ALREADY_COMPLETED")
    try:
        proposal = short_variant(before,payload.minutes)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    overrides = {**(schedule.overrides or {}),before["id"]:{k:v for k,v in proposal["after"].items() if k != "date"}}
    await guard_exported(db,user,run,schedule,schedule.start_date,validate_overrides(run,overrides))
    if payload.apply:
        if payload.expected_after != proposal["after"]:
            raise HTTPException(409,"PROPOSAL_CHANGED_REVIEW_AGAIN")
        await apply_changes(db,user,run,schedule,[proposal],"short_variant",proposal["reasons"])
    return {**proposal,"applied":payload.apply,"revision":schedule.revision}


class WeekIn(BaseModel):
    start: date | None = None
    availability: dict[date,int] = Field(default_factory=dict,max_length=7)
    revision: int = Field(ge=0)
    apply: bool = False
    review_token: str | None = None
    expected_items: list[dict] | None = Field(default=None,max_length=168)


@router.post("/plans/{run_id}/week-review")
async def review_week(run_id: uuid.UUID,payload: WeekIn,user: User = Depends(safety_confirmed_user),db: AsyncSession = Depends(get_db)):
    run,schedule = await get_schedule(db,user,run_id,payload.revision,payload.apply)
    today = user_today(user)
    start = payload.start or today
    plan_end = schedule.start_date+timedelta(weeks=run.metadata_json["structured_plan"]["weeks"])-timedelta(days=1)
    if start < today or start > today+timedelta(days=7) or start > plan_end:
        raise HTTPException(422,"WEEK_OUTSIDE_PLAN")
    if any(d < start or d > start+timedelta(days=6) or v < 0 or v > 480 for d,v in payload.availability.items()):
        raise HTTPException(422,"INVALID_WEEK_AVAILABILITY")
    comparisons = await comparison_data(db,user,run,schedule)
    brief = await briefing(db,user)
    profile = await db.get(CoachProfile,user.id)
    sessions = scheduled_sessions(run,schedule)
    intel = await plan_intelligence(db,user,run_id,sessions)
    blocked = {c["date"] for c in intel["conflicts"] if c["type"] in {"other_pengucoach_plan_same_day","other_garmin_plan_same_day"}}
    # Include all other schedule dates, even dates without a current collision.
    other_rows = (await db.execute(select(PlanSchedule,AiRun).join(AiRun,AiRun.id == PlanSchedule.plan_run_id).where(PlanSchedule.user_id == user.id,PlanSchedule.plan_run_id != run.id))).all()
    for other_schedule,other_run in other_rows:
        blocked.update(s["date"] for s in scheduled_sessions(other_run,other_schedule))
    exports = list((await db.scalars(select(GarminWorkoutExport).where(GarminWorkoutExport.user_id == user.id,GarminWorkoutExport.plan_run_id == run.id))).all())
    locked = {x.session_id for x in exports if x.status == "exported" or x.workout_id or x.scheduled_workout_id}
    weather_rows = {}
    cfg = weather_config(await db.get(UserPreference,user.id))
    if cfg.get("enabled") and cfg.get("latitude") is not None and cfg.get("longitude") is not None:
        try:
            forecast = await fetch_forecast(float(cfg["latitude"]),float(cfg["longitude"]),str(cfg.get("timezone") or "auto"),16)
            weather_rows = {x["date"]:x for x in forecast.get("daily",[]) if start.isoformat() <= x.get("date","") <= (start+timedelta(days=6)).isoformat()}
        except Exception:
            pass
    caps = {d.isoformat():v for d,v in payload.availability.items()}
    check = brief.get("checkin") or {}
    if start <= today <= start+timedelta(days=6) and today not in payload.availability and check.get("minutes") is not None:
        caps[today.isoformat()] = check["minutes"]
    result = week_proposal(sessions,comparisons["items"],start=start,plan_start=schedule.start_date,weeks=run.metadata_json["structured_plan"]["weeks"],profile=(profile.data or {}) if profile else {},availability=caps,readiness=brief["readiness"],today=today,locked=locked,weather=weather_rows,blocked_dates=blocked,caution=bool(set(brief.get("reasons") or []) - {"no_time"}))
    result.update(revision=schedule.revision,readiness=brief["readiness"],freshness=comparisons["freshness"],recent_completed=sum(s["status"] == "matched" and (today-timedelta(days=6)).isoformat() <= (s.get("actual_date") or "") <= today.isoformat() for s in comparisons["items"]),availability=caps)
    # Freshness age changes by the minute, so exclude transient timestamps from
    # the token while retaining all actual comparison/readiness facts.
    stable = {k:v for k,v in result.items() if k != "freshness"}
    review_token = hashlib.sha256(json.dumps({"result":stable,"comparison":comparisons["items"]},sort_keys=True,default=str).encode()).hexdigest()
    if payload.apply:
        if payload.review_token != review_token or payload.expected_items != result["items"]:
            raise HTTPException(409,"PROPOSAL_CHANGED_REVIEW_AGAIN")
        if any(x["changed"] for x in result["items"]):
            await apply_changes(db,user,run,schedule,result["items"],"week_review",[])
    return {**result,"review_token":review_token,"revision":schedule.revision,"applied":payload.apply}
