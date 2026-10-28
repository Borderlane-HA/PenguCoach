import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.routers.health import today, save_manual_body_measurement, ManualBodyMeasurementIn
from pengucoach.common.dates import user_today
from pengucoach.coach.context import build_coach_context, build_training_plan_context, build_activity_analysis_context
from pengucoach.coach.selection import auto_context_days, ContextSelection, context_selection
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, BodyMeasurement, DailyHealth, SleepSession, HrvDaily, User
from pengucoach.health.provenance import body_snapshot, merge_metric
from pengucoach.garmin.sync.service import _upsert_health, _upsert_activities
from pengucoach.sparkyfitness.sync import _merge_checkins, _merge_sleep, _sync_hydration
from pengucoach.sparkyfitness.client import SparkyFitnessError


@compiles(JSONB, "sqlite")
def compile_jsonb(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
async def data_db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(username="athlete", email="a@example.test", password_hash="fixture", timezone="Europe/Berlin")
        other = User(username="other", email="b@example.test", password_hash="fixture")
        db.add_all([user, other]); await db.flush()
        yield db, user, other
    await engine.dispose()


def body(at, **values):
    provider = values.pop("provider", "garmin")
    return BodyMeasurement(measured_at=datetime.fromisoformat(at), raw={"_metric_sources": {k: provider for k in values}}, **values)


def test_newest_body_metric_wins_within_day_and_bmi_uses_effective_inputs():
    rows = [body("2026-01-01T07:00:00+00:00", weight_kg=80, height_cm=180, provider="manual"),
            body("2026-01-01T08:00:00+00:00", weight_kg=79, provider="garmin"),
            body("2026-01-01T10:00:00+00:00", weight_kg=78, provider="sparkyfitness"),
            body("2099-01-01T10:00:00+00:00", weight_kg=90)]
    snapshot = body_snapshot(rows)
    assert snapshot["weight_kg"] == 78
    assert snapshot["height_cm"] == 180
    assert snapshot["sources"]["weight_kg"] == "sparkyfitness"
    assert snapshot["sources"]["height_cm"] == "manual"
    assert snapshot["bmi"] == round(78 / 1.8**2, 2)
    assert snapshot["sources"]["bmi"] == "pengucoach"
    assert snapshot["measured_at_by_metric"]["height_cm"].hour == 7


def test_merge_updates_same_source_and_rejects_older_or_missing_values():
    row = DailyHealth(raw={})
    t = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert merge_metric(row, "steps", 1000, "sparkyfitness", t)
    assert merge_metric(row, "steps", 2000, "sparkyfitness", t+timedelta(hours=1))
    assert not merge_metric(row, "steps", 900, "garmin", t)
    assert not merge_metric(row, "steps", None, "garmin")
    assert row.steps == 2000
    assert merge_metric(row, "hydration_ml", 0, "sparkyfitness")
    assert row.hydration_ml == 0


async def test_sparky_only_context_covers_all_domains_and_selection(data_db):
    db, user, other = data_db
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    day = user_today(user)
    db.add_all([
        Activity(user_id=user.id, garmin_activity_id=-1, name="Swim", sport_type="swimming", started_at=now, duration_seconds=1800, raw={"source":"sparkyfitness"}),
        Activity(user_id=other.id, garmin_activity_id=-2, name="SECRET", started_at=now, raw={}),
        DailyHealth(user_id=user.id, date=day, steps=1000, hydration_ml=1500, resting_hr=55, raw={"_metric_sources":{"steps":"sparkyfitness","hydration_ml":"sparkyfitness","resting_hr":"sparkyfitness"}}),
        SleepSession(user_id=user.id, date=day, duration_seconds=25000, raw={"sparkyfitness":{}}),
        HrvDaily(user_id=user.id, date=day, overnight_average=45, raw={"sparkyfitness":{}}),
        BodyMeasurement(user_id=user.id, measured_at=now, weight_kg=75, raw={"source":"manual_body"}),
    ]); await db.flush()
    ctx = await build_coach_context(db,user,7)
    assert ctx["data_inventory"]["activity_count"] == 1
    assert ctx["recent_activities"][0]["summary"]["source"] == "sparkyfitness"
    assert ctx["health_30d"][0]["hydration_ml"] == 1500
    assert len(ctx["sleep_30d"]) == len(ctx["hrv_30d"]) == 1
    assert "SECRET" not in json.dumps(ctx,default=str)
    off = {f"include_{key}":False for key in ContextSelection.model_fields}
    filtered = await build_coach_context(db,user,7,**off)
    assert not filtered["recent_activities"] and not filtered["health_30d"]
    assert not filtered["body_profile"] and not filtered["training_zones"]
    plan = await build_training_plan_context(db,user,7,include_hydration=False,include_body=False)
    assert "hydration_ml" not in json.dumps(plan, default=str)
    assert plan["lookback"]["body_profile"] is None


async def test_today_keeps_sleep_and_hrv_without_daily_health(data_db):
    db,user,_=data_db
    db.add(SleepSession(user_id=user.id,date=user_today(user),duration_seconds=24000,raw={"sparkyfitness":{}}))
    db.add(HrvDaily(user_id=user.id,date=user_today(user),overnight_average=51,raw={"sparkyfitness":{}}))
    await db.flush()
    result=await today(user=user,db=db)
    assert result["available"] is True
    assert result["sleep"]["duration_seconds"] == 24000
    assert result["hrv"]["overnight_average"] == 51
    assert result["sleep"]["source"] == "sparkyfitness"


async def test_sparky_corrections_refresh_but_empty_garmin_never_erases(data_db):
    db,user,_=data_db
    day=user_today(user).isoformat()
    await _merge_checkins(db,user.id,[{"id":"a","entry_date":day,"steps":1000,"water_ml":500}])
    await db.flush()
    await _merge_checkins(db,user.id,[{"id":"a","entry_date":day,"steps":2000,"water_ml":1000}])
    await db.flush()
    await _upsert_health(db,user,user_today(user),{})
    row=await db.scalar(select(DailyHealth).where(DailyHealth.user_id==user.id))
    assert row.steps == 2000 and row.hydration_ml == 1000
    assert row.raw["_metric_sources"]["steps"] == "sparkyfitness"
    await _merge_sleep(db,user.id,[{"id":"sleep","entry_date":day,"duration_seconds":20000}]);await db.flush()
    await _merge_sleep(db,user.id,[{"id":"sleep","entry_date":day,"duration_seconds":24000}]);await db.flush()
    sleep=await db.scalar(select(SleepSession).where(SleepSession.user_id==user.id))
    assert sleep.duration_seconds == 24000


async def test_manual_entry_immediately_visible_and_historical_analysis_has_no_future_body(data_db):
    db,user,_=data_db
    result=await save_manual_body_measurement(ManualBodyMeasurementIn(weight_kg=73,height_cm=180),user,db)
    assert result["current"]["weight_kg"]==73
    old=datetime.now(timezone.utc)-timedelta(days=20)
    activity=Activity(user_id=user.id,garmin_activity_id=-4,started_at=old,name="Historic",sport_type="hiking",raw={"source":"sparkyfitness"})
    db.add(activity);await db.flush()
    context=await build_activity_analysis_context(db,user,activity.id,1)
    assert context["activity"]["summary"]["name"] == "Historic"
    assert context["lookback"]["body_profile"] is None
    isolated=await build_activity_analysis_context(db,user,activity.id,0)
    assert isolated["lookback"]["body_profile"] is None


async def test_garmin_after_sparky_reuses_session_and_preserves_source(data_db):
    db,user,_=data_db
    start=datetime.now(timezone.utc)-timedelta(hours=1)
    activity=Activity(user_id=user.id,garmin_activity_id=-10,started_at=start,name="Ride",sport_type="cycling",avg_hr=135,duration_seconds=3600,distance_m=30000,raw={"source":"sparkyfitness","sparkyfitness":{"id":"ride"},"sparkyfitness_external_id":"ride"})
    db.add(activity);await db.flush();original_id=activity.id
    count,rows=await _upsert_activities(db,user,[{"activityId":123,"activityName":"Ride","activityType":{"typeKey":"cycling"},"startTimeGMT":start.isoformat(),"duration":3600,"distance":30000}])
    assert rows[0].id == original_id
    assert rows[0].garmin_activity_id == 123 and "sparkyfitness" in rows[0].raw
    assert rows[0].avg_hr == 135
    assert rows[0].raw["_metric_sources"]["avg_hr"] == "sparkyfitness"
    assert count == 0
    assert len((await db.scalars(select(Activity).where(Activity.user_id==user.id))).all()) == 1


async def test_water_range_and_older_server_fallback_are_bounded(data_db):
    db,user,_=data_db
    class Client:
        calls=[]
        async def request(self,path,**kwargs):
            self.calls.append(path)
            if "-range/" in path: raise SparkyFitnessError("SPARKYFITNESS_HTTP_404",status_code=404)
            return {"water_ml":1250}
    client=Client()
    result=await _sync_hydration(db,client,user.id,user_today(user)-timedelta(days=100),user_today(user))
    assert result["days"] == 28 and len(client.calls) == 29
    assert result["mode"] == "daily_fallback_max_28_days"


def test_short_advice_auto_window_and_selection_defaults_are_shared():
    assert auto_context_days("Was soll ich heute trainieren?")==7
    assert auto_context_days("Und heute?")==7
    assert auto_context_days("Analysiere die letzten 14 Tage")==14
    assert context_selection({})["include_hydration"] is True


async def test_battery_levels_are_not_charge_deltas_and_missing_hrv_is_not_weekly_average(data_db):
    from pengucoach.garmin.sync.service import _upsert_hrv
    db,user,_=data_db
    await _upsert_health(db,user,user_today(user),{"body_battery":[{"charged":25,"drained":17,"bodyBatteryValuesArray":[[1,80],[2,65]]}]})
    await db.flush()
    row=await db.scalar(select(DailyHealth).where(DailyHealth.user_id==user.id))
    assert (row.body_battery_high,row.body_battery_low)==(80,65)
    await _upsert_hrv(db,user,user_today(user),{"weeklyAvg":70})
    await db.flush()
    hrv=await db.scalar(select(HrvDaily).where(HrvDaily.user_id==user.id))
    assert hrv.overnight_average is None


def test_invalid_provider_sentinels_are_missing_and_integer_units_normalized():
    row=DailyHealth(raw={})
    assert not merge_metric(row,"stress_avg",-1,"garmin")
    assert not merge_metric(row,"spo2_avg",float("nan"),"garmin")
    assert merge_metric(row,"hydration_ml",1250.2,"sparkyfitness")
    assert row.hydration_ml==1250 and isinstance(row.hydration_ml,int)
