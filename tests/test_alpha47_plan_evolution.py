import copy
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.routers import companion as old, plan_evolution as api
from pengucoach.coach.plan_evolution import compare_v2, seconds, short_variant, week_proposal
from pengucoach.common.dates import user_today
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, AiRun, CoachDecisionLog, GarminWorkoutExport, PlanActivityMatch, User


@compiles(JSONB, "sqlite")
def compile_json(type_, compiler, **kw):
    return "JSON"


def workout(**changes):
    return {"id":"s1","week":1,"day":1,"date":"2026-10-05","name":"Intervals","sport":"running","duration_min":45,"steps":[
        {"type":"warmup","duration_seconds":600,"target":{"type":"heart_rate_zone","zone":2}},
        {"type":"repeat","repeat":6,"steps":[{"type":"interval","duration_seconds":180,"target":{"type":"heart_rate_zone","zone":4}},{"type":"recovery","duration_seconds":120,"target":{"type":"none"}}]},
        {"type":"cooldown","duration_seconds":300,"target":{"type":"none"}},
    ], **changes}


def activity(day, minutes=45):
    return Activity(id=uuid.uuid4(),started_at=datetime.fromisoformat(day+"T12:00:00+00:00"),duration_seconds=minutes*60,sport_type="running",name="Run")


def test_matching_uses_local_date_duration_and_never_silently_matches_shifted_day():
    user=SimpleNamespace(timezone="Europe/Berlin")
    a=activity("2026-10-05")
    assert compare_v2([workout()],[a],user)[0]["status"]=="matched"
    a.started_at=datetime(2026,10,4,22,30,tzinfo=timezone.utc)
    assert compare_v2([workout()],[a],user)[0]["status"]=="matched"
    shifted=activity("2026-10-06")
    result=compare_v2([workout()],[shifted],user)[0]
    assert result["status"]=="ambiguous" and result["activity_id"] is None
    assert result["candidates"][0]["day_difference"]==1
    different=activity("2026-10-05",120)
    assert compare_v2([workout()],[different],user)[0]["status"]=="ambiguous"


def test_activity_is_not_reused_in_same_or_other_plan():
    user=SimpleNamespace(timezone="UTC")
    a=activity("2026-10-05")
    s=workout()
    assert all(x["status"]=="ambiguous" for x in compare_v2([s,{**s,"id":"s2"}],[a],user))
    r=compare_v2([s],[a],user,other_sessions=[{**s,"match_key":"other:s1"}])
    assert r[0]["activity_id"] is None
    assert compare_v2([s],[a],user,reserved={str(a.id)})[0]["candidate_ids"]==[]


def test_missing_activity_stays_pending_until_user_marks_it_missed():
    user=SimpleNamespace(timezone="UTC")
    s=workout(date=(user_today(user)-timedelta(days=2)).isoformat())
    assert compare_v2([s],[],user)[0]["status"]=="pending"
    marker=SimpleNamespace(activity_id=None,state="missed")
    assert compare_v2([s],[],user,confirmed={s["id"]:marker})[0]["status"]=="unmatched"


def test_short_variant_preserves_preparation_and_complete_intervals():
    before=workout()
    proposal=short_variant(before,30)
    after=proposal["after"]
    assert before==workout()
    assert after["steps"][0]["duration_seconds"]==600
    assert after["steps"][-1]["duration_seconds"]==300
    assert after["steps"][1]["repeat"]==3
    assert after["steps"][1]["steps"][0]["duration_seconds"]==180
    assert after["steps"][1]["steps"][1]["duration_seconds"]==120
    assert sum(seconds(s) for s in after["steps"])==1800
    with pytest.raises(ValueError,match="MINIMUM_SESSION_DURATION"):
        short_variant(before,15)
    distance=workout(steps=[{"type":"work","distance_meters":5000}])
    with pytest.raises(ValueError,match="DISTANCE_STEP"):
        short_variant(distance,20)


def test_short_strength_reduces_sets_without_compressing_rest():
    s=workout(sport="strength",steps=[],strength_exercises=[{"name":"Squat","sets":4,"reps":10,"rest_seconds":90},{"name":"Row","sets":4,"reps":8,"rest_seconds":120}])
    result=short_variant(s,25)
    assert sum(x["sets"] for x in result["after"]["strength_exercises"])==4
    assert [(x["reps"],x["rest_seconds"]) for x in result["after"]["strength_exercises"]]==[(10,90),(8,120)]
    with pytest.raises(ValueError,match="MINIMUM_SESSION_DURATION"):
        short_variant(s,5)


def test_week_proposal_respects_export_bounds_recovery_and_time():
    start=date(2026,10,5)
    first=workout()
    second=workout(id="s2",date="2026-10-07",day=3)
    original=copy.deepcopy([first,second])
    result=week_proposal([first,second],[],start=start,plan_start=start,weeks=3,profile={"training_days":[1,2,3,4,5,6,7]},availability={"2026-10-06":30},readiness={"status":"red"},today=start,locked={"s2"})
    assert [first,second]==original
    assert result["items"][0]["after"]==second
    # Tuesday cannot become a hard day immediately before the protected Wednesday.
    moved=next(x for x in result["items"] if x["before"]["id"]=="s1")
    assert moved["after"]["date"]=="2026-10-09"
    assert result["proposed_minutes"]<=result["original_minutes"]
    assert result["readiness_scope"]=="today_only"


def test_week_never_catches_up_unresolved_sessions_or_uses_other_plan_dates():
    start=date(2026,10,5)
    s=workout(name="Easy run",steps=[])
    result=week_proposal([s],[{**s,"date":"2026-10-04","status":"pending"}],start=start,plan_start=start,weeks=1,profile={},availability={"2026-10-05":0},readiness={},today=start,blocked_dates={"2026-10-06"})
    assert len(result["items"])==1 and result["unresolved_past_sessions"]==1
    assert result["items"][0]["after"]["date"]=="2026-10-07"


@pytest.fixture
async def data():
    engine=create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        user=User(username="first",email="first@x",password_hash="x",timezone="Europe/Berlin")
        other=User(username="second",email="second@x",password_hash="x",timezone="UTC")
        db.add_all([user,other]);await db.flush()
        yield db,user,other
    await engine.dispose()


async def plan(db,user,past=False):
    today=user_today(user)
    monday=today-timedelta(days=today.weekday())
    day=today-timedelta(days=1) if past else today
    if day<monday:
        monday-=timedelta(days=7)
    s=workout(day=day.isoweekday(),week=1,name="Easy run",steps=[{"type":"warmup","duration_seconds":600},{"type":"work","duration_seconds":1800},{"type":"cooldown","duration_seconds":300}])
    s.pop("date")
    run=AiRun(user_id=user.id,task_type="training_plan",prompt="q",content="plan",metadata_json={"structured_plan":{"title":"Plan","weeks":3,"sessions":[s]}})
    db.add(run);await db.flush()
    await old.save_schedule(run.id,old.ScheduleIn(start_date=monday),user,db)
    return run,day


async def test_explicit_matches_are_owned_unique_and_revision_checked(data):
    db,user,other=data
    run,day=await plan(db,user,True)
    a=activity(day.isoformat());a.user_id=user.id;a.garmin_activity_id=-1
    db.add(a);await db.flush()
    with pytest.raises(HTTPException) as error:
        await api.match_activity(run.id,api.MatchIn(session_id="s1",activity_id=a.id,revision=1),other,db)
    assert error.value.status_code==404
    await api.match_activity(run.id,api.MatchIn(session_id="s1",activity_id=a.id,revision=1),user,db)
    run2,_=await plan(db,user,True)
    with pytest.raises(HTTPException) as error:
        await api.match_activity(run2.id,api.MatchIn(session_id="s1",activity_id=a.id,revision=1),user,db)
    assert error.value.detail=="ACTIVITY_ALREADY_ASSIGNED"
    with pytest.raises(HTTPException) as error:
        await api.clear_match(run.id,"s1",1,user,db)
    assert error.value.detail=="SCHEDULE_CHANGED_RELOAD"
    row=(await old.comparison(run.id,user,db))["items"][0]
    assert row["match_basis"]=="user_confirmed" and row["activity_id"]==str(a.id)
    await api.clear_match(run.id,"s1",2,user,db)
    assert not (await db.scalars(select(PlanActivityMatch))).all()


async def test_short_preview_is_read_only_and_apply_requires_exact_review(data):
    db,user,_=data
    run,_=await plan(db,user)
    p=await api.review_short(run.id,api.ShortIn(session_id="s1",minutes=30,revision=1),user,db)
    assert (await old.get_schedule(run.id,user,db))["revision"]==1
    with pytest.raises(HTTPException) as error:
        await api.review_short(run.id,api.ShortIn(session_id="s1",minutes=30,revision=1,apply=True,expected_after={}),user,db)
    assert error.value.detail=="PROPOSAL_CHANGED_REVIEW_AGAIN"
    await api.review_short(run.id,api.ShortIn(session_id="s1",minutes=30,revision=1,apply=True,expected_after=p["after"]),user,db)
    assert (await old.get_schedule(run.id,user,db))["revision"]==2
    assert (await db.scalars(select(CoachDecisionLog))).one().action=="short_variant"


async def test_week_preview_apply_protects_revision_and_records_changes(data):
    db,user,_=data
    run,day=await plan(db,user)
    req=api.WeekIn(revision=1,availability={day+timedelta(days=i):30 for i in range(7)})
    p=await api.review_week(run.id,req,user,db)
    assert p["items"][0]["changed"] and p["proposed_minutes"]==30
    assert (await old.get_schedule(run.id,user,db))["revision"]==1
    bad=req.model_copy(update={"apply":True,"review_token":"wrong","expected_items":p["items"]})
    with pytest.raises(HTTPException) as error:
        await api.review_week(run.id,bad,user,db)
    assert error.value.detail=="PROPOSAL_CHANGED_REVIEW_AGAIN"
    good=req.model_copy(update={"apply":True,"review_token":p["review_token"],"expected_items":p["items"]})
    saved=await api.review_week(run.id,good,user,db)
    assert saved["revision"]==2 and saved["applied"]
    assert (await db.scalars(select(CoachDecisionLog))).one().action=="week_review"
    with pytest.raises(HTTPException) as error:
        await api.review_week(run.id,good,user,db)
    assert error.value.detail=="SCHEDULE_CHANGED_RELOAD"


async def test_garmin_exported_sessions_cannot_be_shortened(data):
    db,user,_=data
    run,day=await plan(db,user)
    db.add(GarminWorkoutExport(user_id=user.id,plan_run_id=run.id,session_id="s1",scheduled_date=day,status="exported",workout_id="123"));await db.flush()
    with pytest.raises(HTTPException) as error:
        await api.review_short(run.id,api.ShortIn(session_id="s1",minutes=30,revision=1),user,db)
    assert error.value.detail=="EXPORTED_SESSION_LOCKED"
    p=await api.review_week(run.id,api.WeekIn(revision=1,availability={day:0}),user,db)
    assert not p["items"][0]["changed"] and p["items"][0]["reasons"]==["garmin_export_locked"]


async def test_imported_activity_changes_week_snapshot_before_apply(data):
    db,user,_=data
    run,day=await plan(db,user)
    request=api.WeekIn(revision=1,availability={day+timedelta(days=i):30 for i in range(7)})
    preview=await api.review_week(run.id,request,user,db)
    a=activity(day.isoformat());a.user_id=user.id;a.garmin_activity_id=-7
    # Record before the current instant even if tests run before midday.
    a.started_at=datetime.now(timezone.utc)-timedelta(minutes=1)
    db.add(a);await db.flush()
    with pytest.raises(HTTPException) as error:
        await api.review_week(run.id,request.model_copy(update={"apply":True,"review_token":preview["review_token"],"expected_items":preview["items"]}),user,db)
    assert error.value.detail=="PROPOSAL_CHANGED_REVIEW_AGAIN"
    assert (await old.get_schedule(run.id,user,db))["revision"]==1


async def test_http_routes_validate_and_isolate_review_requests(data):
    from httpx import ASGITransport, AsyncClient
    from apps.api.main import app
    from pengucoach.auth.dependencies import safety_confirmed_user
    from pengucoach.db.session import get_db
    db,user,_=data
    run,_=await plan(db,user)
    async def database():
        yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[safety_confirmed_user]=lambda:user
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
            response=await client.post(f"/api/v1/coach/plans/{run.id}/week-review",json={"revision":1})
            assert response.status_code==200 and response.json()["method"]=="deterministic_seven_day_review"
            response=await client.post(f"/api/v1/coach/plans/{run.id}/short-variant",json={"revision":1,"session_id":"s1","minutes":30})
            assert response.status_code==200 and not response.json()["applied"]
            response=await client.post(f"/api/v1/coach/plans/{run.id}/week-review",json={"revision":1,"availability":{user_today(user).isoformat():-1}})
            assert response.status_code==422
            response=await client.get("/api/v1/coach/freshness")
            assert response.status_code==200
    finally:
        app.dependency_overrides.clear()


async def test_migration_can_upgrade_existing_schema_and_is_idempotent(data):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    db,_,_=data
    spec=importlib.util.spec_from_file_location("migration47",Path("db/migrations/versions/0014_plan_evolution.py"))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    await db.commit()
    conn=await db.connection()
    def exercise(connection):
        PlanActivityMatch.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade();migration.upgrade()
            constraints=inspect(connection).get_unique_constraints("plan_activity_matches")
            assert {tuple(x["column_names"]) for x in constraints}=={("activity_id",),("plan_run_id","session_id")}
            migration.downgrade()
            assert "plan_activity_matches" not in inspect(connection).get_table_names()
    await conn.run_sync(exercise)
