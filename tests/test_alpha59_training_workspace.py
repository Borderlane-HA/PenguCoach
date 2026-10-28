import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.routers import companion, plan_evolution, training_workspace as api
from pengucoach.coach.goal_journey import GoalJourneyIn, goal_progress
from pengucoach.common.dates import user_today
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, AiRun, CoachProfile, PlanSchedule, User


@compiles(JSONB, "sqlite")
def json_sqlite(type_, compiler, **kw):
    return "JSON"


def recorded(stamp="2026-10-16T10:00:00+00:00", **values):
    return SimpleNamespace(id=uuid.uuid4(), name="Run", started_at=datetime.fromisoformat(stamp),
                           sport_type=values.get("sport", "running"), duration_seconds=values.get("seconds", 1800),
                           distance_m=values.get("distance", 5000))


def goal(**values):
    return {"title": "10 km", "metric": "distance_km", "sport": "running", "target": 10,
            "start_date": "2026-10-01", "target_date": None, **values}


def test_distance_is_one_recorded_session_and_has_activity_evidence():
    a, b = recorded(distance=4000), recorded(distance=6000)
    p = goal_progress(goal(), [a, b], SimpleNamespace(timezone="Europe/Berlin"), now=datetime(2026, 10, 17, tzinfo=timezone.utc))
    assert p["value"] == 6 and p["percent"] == 60
    assert [m["reached"] for m in p["milestones"]] == [True, True, False, False]
    assert p["milestones"][1]["activity_id"] == str(b.id)


def test_goal_period_and_local_midnight_exclude_future_and_other_sports():
    now = datetime(2026, 10, 16, 23, tzinfo=timezone.utc)
    activities = [recorded("2026-10-16T22:30:00+00:00", distance=7000),
                  recorded("2026-10-16T23:30:00+00:00", distance=12000),
                  recorded("2026-10-16T21:30:00+00:00", distance=13000),
                  recorded("2026-10-16T22:00:00+00:00", distance=20000, sport="cycling")]
    p = goal_progress(goal(start_date="2026-10-17"), activities, SimpleNamespace(timezone="Europe/Berlin"), now=now)
    assert p["value"] == 7 and p["observed_activities"] == 1
    assert p["evidence"]["date"] == "2026-10-17"
    expired = goal_progress(goal(target_date="2026-10-15"), activities, SimpleNamespace(timezone="Europe/Berlin"), now=now)
    assert expired["value"] is None and expired["status"] == "no_data"


def test_missing_measurements_are_unknown_and_counts_require_five_minutes():
    user = SimpleNamespace(timezone="UTC")
    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    p = goal_progress(goal(), [recorded(distance=None), recorded(distance=float("nan"))], user, now=now)
    assert p["value"] is None and p["percent"] == 0
    p = goal_progress(goal(metric="sessions", target=3, sport="any"), [recorded(seconds=299), recorded(seconds=300), recorded(seconds=1000, sport="strength")], user, now=now)
    assert p["value"] == 2 and len(p["milestones"]) == 3
    assert [m["reached"] for m in p["milestones"]] == [True, True, False]


@pytest.mark.parametrize("fields", [{"title": " "}, {"metric": "sessions", "target": 2.5}, {"target": float("nan")}, {"target": -1}, {"sport": "strength"}, {"target_date": "2026-09-01"}])
def test_invalid_goal_contract(fields):
    with pytest.raises(ValidationError):
        GoalJourneyIn(**goal(**fields))


@pytest.fixture
async def data():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(username="first", email="first@x", password_hash="x", timezone="Europe/Berlin")
        other = User(username="second", email="second@x", password_hash="x", timezone="UTC")
        db.add_all([user, other]); await db.flush()
        yield db, user, other
    await engine.dispose()


async def test_goal_preserves_profile_and_rejects_stale_update_and_delete(data):
    db, user, _ = data
    db.add(CoachProfile(user_id=user.id, data={"goal": "Existing context", "equipment": "Bike"})); await db.commit()
    saved = await api.save_goal(GoalJourneyIn(**goal()), user, db)
    assert saved["revision"] == 1
    await companion.save_profile(companion.ProfileIn(goal="Updated context", equipment="Dumbbells"), user, db)
    assert (await api.get_goal(user, db))["goal"]["title"] == "10 km"
    for operation in (api.save_goal(GoalJourneyIn(**goal()), user, db), api.delete_goal(0, user, db)):
        with pytest.raises(HTTPException) as exc:
            await operation
        assert exc.value.status_code == 409
    deleted = await api.delete_goal(1, user, db)
    assert deleted["goal"] is None and deleted["revision"] == 2
    profile = await db.get(CoachProfile, user.id)
    assert profile.data["equipment"] == "Dumbbells" and profile.data["goal"] == "Updated context"
    with pytest.raises(HTTPException):
        await api.save_goal(GoalJourneyIn(**goal(), revision=1), user, db)


async def test_progress_and_goals_are_isolated_per_user(data):
    db, user, other = data
    today = user_today(user)
    for owner, distance in ((user, 4000), (other, 100000)):
        db.add(Activity(user_id=owner.id, garmin_activity_id=1, started_at=datetime.now(timezone.utc)-timedelta(seconds=1), sport_type="running", distance_m=distance, duration_seconds=1800))
    await db.commit()
    saved = await api.save_goal(GoalJourneyIn(**goal(start_date=today.isoformat())), user, db)
    assert saved["progress"]["value"] == 4
    assert (await api.get_goal(other, db))["goal"] is None


async def create_plan(db, user):
    today = user_today(user)
    monday = today-timedelta(days=today.weekday())
    session = {"id": "s1", "week": 2, "day": 1, "name": "Easy run", "sport": "running", "duration_min": 30, "steps": [{"type": "work", "duration_seconds": 1800}]}
    run = AiRun(user_id=user.id, task_type="training_plan", prompt="q", content="plan", metadata_json={"goal": {"start_date": monday.isoformat()}, "structured_plan": {"title": "Plan", "weeks": 3, "sessions": [session]}})
    db.add(run); await db.commit()
    return run, monday


async def test_workspace_preview_is_read_only_and_enforces_plan_ownership(data):
    db, user, other = data
    run, monday = await create_plan(db, user)
    preview = await api.workspace(run.id, user, db)
    assert preview["needs_schedule"] and preview["revision"] == 0
    assert preview["items"][0]["date"] == (monday+timedelta(days=7)).isoformat()
    assert await db.get(PlanSchedule, run.id) is None
    with pytest.raises(HTTPException) as exc:
        await api.workspace(run.id, other, db)
    assert exc.value.status_code == 404


async def test_week_assistant_can_explicitly_override_profile_days_without_saving_profile(data, monkeypatch):
    db, user, _ = data
    run, monday = await create_plan(db, user)
    saved = await companion.save_schedule(run.id, companion.ScheduleIn(start_date=monday), user, db)
    db.add(CoachProfile(user_id=user.id, data={"training_days": [1], "session_minutes": 30})); await db.commit()
    async def brief(*args):
        return {"readiness": {"status": "green"}, "checkin": {}, "reasons": []}
    async def intelligence(*args):
        return {"conflicts": []}
    monkeypatch.setattr(plan_evolution, "briefing", brief)
    monkeypatch.setattr(plan_evolution, "plan_intelligence", intelligence)
    start = monday+timedelta(days=7)
    availability = {start+timedelta(days=i): 30 if i == 1 else 0 for i in range(7)}
    payload = plan_evolution.WeekIn(start=start, revision=saved["revision"], availability=availability, override_training_days=True)
    proposal = await plan_evolution.review_week(run.id, payload, user, db)
    assert proposal["items"][0]["after"]["date"] == (start+timedelta(days=1)).isoformat()
    assert (await db.get(CoachProfile, user.id)).data["training_days"] == [1]
    assert (await db.get(PlanSchedule, run.id)).revision == saved["revision"]
