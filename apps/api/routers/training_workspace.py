"""Training workspace and a user-owned measurable goal; existing tables are reused."""
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.companion import plan_owned
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.companion import scheduled_sessions
from pengucoach.coach.goal_journey import GoalJourneyIn, goal_progress
from pengucoach.coach.plan_evolution import comparison_data
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, CoachProfile, GarminWorkoutExport, PlanSchedule, User
from pengucoach.db.session import get_db

router = APIRouter(prefix="/coach", tags=["training workspace"])


async def journey_payload(db, user, row):
    data = (row.data or {}) if row else {}
    goal = data.get("goal_journey")
    today = user_today(user)
    progress = None
    if goal:
        end = min(today, date.fromisoformat(goal["target_date"])) if goal.get("target_date") else today
        activities = (await db.execute(select(Activity.id, Activity.name, Activity.started_at,
            Activity.sport_type, Activity.duration_seconds, Activity.distance_m).where(Activity.user_id == user.id,
            Activity.started_at >= day_start(date.fromisoformat(goal["start_date"]), user),
            Activity.started_at < day_start(end + timedelta(days=1), user),
            Activity.started_at <= datetime.now(timezone.utc)))).all()
        progress = goal_progress(goal, activities, user)
    return {"goal": goal, "progress": progress, "revision": int(data.get("_goal_journey_revision", 0)), "date": today.isoformat()}


@router.get("/goal-journey")
async def get_goal(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await journey_payload(db, user, await db.get(CoachProfile, user.id))


async def locked_profile(db, user, revision):
    row = await db.scalar(select(CoachProfile).where(CoachProfile.user_id == user.id).with_for_update().execution_options(populate_existing=True))
    if int((row.data or {}).get("_goal_journey_revision", 0) if row else 0) != revision:
        raise HTTPException(409, "GOAL_CHANGED_RELOAD")
    return row


@router.put("/goal-journey")
async def save_goal(payload: GoalJourneyIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await locked_profile(db, user, payload.revision)
    if not row:
        row = CoachProfile(user_id=user.id, data={})
        db.add(row)
    row.data = {**(row.data or {}), "goal_journey": payload.model_dump(mode="json", exclude={"revision"}), "_goal_journey_revision": payload.revision + 1}
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "GOAL_CHANGED_RELOAD") from exc
    return await journey_payload(db, user, row)


@router.delete("/goal-journey")
async def delete_goal(revision: int = Query(ge=0), user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await locked_profile(db, user, revision)
    if row:
        data = dict(row.data or {})
        data.pop("goal_journey", None)
        row.data = {**data, "_goal_journey_revision": revision + 1}
        await db.commit()
    return await journey_payload(db, user, row)


@router.get("/plans/{run_id}/workspace")
async def workspace(run_id: uuid.UUID, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    run = await plan_owned(db, user, run_id)
    schedule = await db.get(PlanSchedule, run_id)
    today = user_today(user)
    needs_schedule = schedule is None
    if schedule is None:
        try:
            start = date.fromisoformat((run.metadata_json.get("goal") or {}).get("start_date", ""))
            if start.weekday() != 0:
                raise ValueError
        except (ValueError, TypeError):
            start = today + timedelta(days=(7-today.weekday()) % 7)
        schedule = PlanSchedule(plan_run_id=run_id, user_id=user.id, start_date=start, overrides={}, revision=0)
    compared = await comparison_data(db, user, run, schedule) if not needs_schedule else {"items": [{**s, "status": "planned", "activity_id": None} for s in scheduled_sessions(run, schedule)]}
    exports = (await db.scalars(select(GarminWorkoutExport).where(GarminWorkoutExport.user_id == user.id, GarminWorkoutExport.plan_run_id == run_id))).all()
    locked = {x.session_id for x in exports if x.status == "exported" or x.workout_id or x.scheduled_workout_id}
    return {"date": today.isoformat(), "start_date": schedule.start_date.isoformat(), "weeks": run.metadata_json["structured_plan"]["weeks"],
            "revision": schedule.revision, "needs_schedule": needs_schedule, "overrides": schedule.overrides,
            "items": [{**s, "locked": s["id"] in locked} for s in compared["items"]]}
