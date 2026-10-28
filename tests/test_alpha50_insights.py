import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.routers import insights
from pengucoach.coach.progress import milestones, personal_patterns, readiness_history
from pengucoach.coach.workout_review import evaluate_goals, route_match, route_metrics
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, AiRun, CoachCheckin, FitFile, PlanActivityMatch, PlanSchedule, User


def samples(n=61, *, hr=140, power=180, interval=1):
    return [{"elapsed_s": i*interval, "distance_km": i*.01, "position_lat": 52.0, "position_long": 13+i*.00015, "heart_rate": hr, "power": power, "speed_kmh": 36/interval} for i in range(n)]


def step(seconds=60, kind="heart_rate_zone", zone=2):
    return {"type": "work", "duration_seconds": seconds, "target": {"type": kind, "zone": zone}}


def test_review_weights_real_seconds_and_splits_boundary_crossings():
    rows = [{"elapsed_s": t, "heart_rate": hr} for t, hr in [(0, 100), (1, 140), (11, 190), (21, 140), (30, 140)]]
    result = evaluate_goals(rows, {"steps": [step(15), step(15)]}, {"heart_rate_zone": [{"zone": 2, "low_bpm": 120, "high_bpm": 150}]})
    assert result["coverage_pct"] == 100
    assert result["in_target_pct"] == 63.3  # 19 seconds, not 3 of 5 samples.
    assert result["steps"][0]["above_pct"] == 26.7
    assert result["steps"][1]["above_pct"] == 40


def test_review_expands_nested_repeats_and_accepts_zero_power():
    nested = {"type": "repeat", "repeat": 2, "steps": [{"type": "repeat", "repeat": 2, "steps": [step(15, "power_zone", 1)]}]}
    result = evaluate_goals(samples(power=0), {"steps": [nested]}, {"power_zone": [{"zone": 1, "low_w": 0, "high_w": 100}]})
    assert len(result["steps"]) == 4
    assert result["in_target_pct"] == 100 and result["status"] == "on_target"


def test_review_never_invents_times_sensor_gaps_or_unknown_zone_success():
    assert evaluate_goals([{"heart_rate": 140}]*20, {"steps": [step()]}, {})["reason"] == "missing_time"
    rows = samples();rows[1:50] = [{**r, "heart_rate": None} for r in rows[1:50]]
    result = evaluate_goals(rows, {"steps": [step()]}, {"heart_rate_zone": [{"zone": 2, "low": 120, "high": 150}]})
    assert result["status"] == "unassessed" and result["in_target_pct"] is None
    gap = evaluate_goals([{"elapsed_s": 0, "heart_rate": 140}, {"elapsed_s": 60, "heart_rate": 140}], {"steps": [step()]}, {"heart_rate_zone": [{"zone": 2, "low": 120, "high": 150}]})
    assert gap["observed_seconds"] == 0
    result = evaluate_goals(samples(), {"steps": [step(50), step(10, "power_zone")]}, {"heart_rate_zone": [{"zone": 2, "low": 120, "high": 150}]})
    assert result["coverage_pct"] == 83.3 and result["status"] == "partial"


def test_distance_steps_and_recording_offset_use_recorded_boundaries():
    series = samples()
    distance = {"type": "work", "distance_meters": 300, "target": {"type": "heart_rate_zone", "zone": 2}}
    profiles = {"heart_rate_zone": [{"zone": 2, "low": 120, "high": 150}]}
    result = evaluate_goals(series, {"steps": [distance, step(10)]}, profiles, offset_s=10)
    assert result["steps"][0]["end_s"] == pytest.approx(30)
    assert result["steps"][1]["end_s"] == 40
    assert result["observed_seconds"] == 40
    unknown = evaluate_goals([{**r, "distance_km": None} for r in series], {"steps": [distance, step()]}, profiles)
    assert len(unknown["steps"]) == 1 and unknown["reason"] == "missing_distance"


def test_routes_require_ordered_shape_and_support_selected_segments():
    rows = samples()
    assert route_match(rows, rows)["mean_gap_m"] == 0
    assert route_match(rows, [{**r, "position_lat": 52.1} for r in rows]) is None
    backwards = [{**r, "position_long": rows[-1-i]["position_long"]} for i, r in enumerate(rows)]
    assert route_match(rows, backwards) is None
    match = route_match(rows[15:46], rows, segment=True)
    assert (match["start_index"], match["end_index"]) == (15, 45)
    assert route_match(rows, [{**r, "track_segment": 1 if i<30 else 2} for i, r in enumerate(rows)]) is None
    sparse = [{**r, "position_lat": None} if i<30 else r for i,r in enumerate(rows)]
    assert route_match(rows, sparse) is None


def test_route_metrics_hide_sparse_channels_and_preserve_coasting():
    data = samples(power=0)
    assert route_metrics(data)["avg_power"] == 0
    sparse = [{**r, "heart_rate": None if i<40 else 150} for i,r in enumerate(data)]
    assert "avg_hr" not in route_metrics(sparse)
    assert "avg_hr" not in route_metrics([{**r, "elapsed_s": None} for r in data])


def test_readiness_history_excludes_future_measurements_and_keeps_missing_open():
    today = date(2026, 10, 10)
    ctx = {"sleep_30d": [{"date": "2026-10-10", "duration_s": 8*3600}], "health_30d": [{"date": "2026-10-10", "training_readiness": 90}]}
    result = readiness_history(ctx, {}, [], [], today=today, days=7)
    assert all(r["score"] is None for r in result[:-1])
    assert result[-1]["score"] is not None and result[0]["training_minutes"] is None


def test_patterns_require_both_cohorts_and_do_not_double_count_a_day():
    sleeps = [{"date": f"2026-10-0{i}", "duration_s": (5 if i<=3 else 8)*3600} for i in range(1,7)]
    checks = {r["date"]: {"energy": 2 if i<3 else 4} for i,r in enumerate(sleeps)}
    pattern = personal_patterns(sleeps, checks, [])[0]
    assert (pattern["short_value"], pattern["long_value"]) == (2,4)
    assert not personal_patterns(sleeps[:2]+sleeps[3:], checks, [])
    feedback = [{"date": "2026-10-01", "feeling": "hard"}]*10 + [{"date": r["date"], "feeling": "right"} for r in sleeps[3:]]
    assert not personal_patterns(sleeps, {}, feedback)


def test_milestones_need_completed_weeks_and_use_explicit_90_day_records():
    today = date(2026,10,10)
    rows = [{"id": str(i), "date": d, "sport": "running", "duration_seconds": 1800} for i,d in enumerate(["2026-09-21","2026-09-23","2026-09-25","2026-09-28","2026-09-30","2026-10-02"])]
    assert milestones(rows,today)[0]["key"] == "regularity"
    rows.append({"id":"new", "date":"2026-10-10", "sport":"running", "duration_seconds":2400})
    record = milestones(rows,today)[1]
    assert record["window_days"] == 90 and record["value"] == 40
    assert not milestones(rows[-1:],today)


@compiles(JSONB, "sqlite")
def json_type(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
async def db_users():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        first, second = [User(id=uuid.uuid4(), username=n, email=f"{n}@test.dev", password_hash="x", timezone="Europe/Berlin") for n in ("first", "second")]
        db.add_all([first,second]);await db.commit()
        yield db,first,second
    await engine.dispose()


async def test_progress_and_activity_reviews_are_user_scoped(db_users):
    db,first,second = db_users
    now = datetime.now(timezone.utc)-timedelta(minutes=2)
    activity = Activity(id=uuid.uuid4(),user_id=first.id,garmin_activity_id=-21,started_at=now,sport_type="running",duration_seconds=1800,name="Private run",raw={})
    db.add(activity);db.add(CoachCheckin(user_id=first.id,date=now.date(),data={"energy":5,"soreness":1}));await db.commit()
    with pytest.raises(HTTPException) as error:
        await insights.goal_review(activity.id, None, None, 0, second, db)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        await insights.route_comparison(activity.id, 0, 100, "distance", second, db)
    other = await insights.progress(7, second, db)
    assert all(r["score"] is None and r["sessions"] == 0 for r in other["history"])
    own = await insights.progress(7, first, db)
    assert sum(r["sessions"] for r in own["history"]) == 1


async def test_api_review_uses_complete_recording_and_sport_specific_zones(db_users, tmp_path, monkeypatch):
    db,user,_ = db_users
    activity = Activity(id=uuid.uuid4(),user_id=user.id,garmin_activity_id=-22,started_at=datetime.now(timezone.utc)-timedelta(minutes=2),sport_type="running",duration_seconds=60,name="Recorded run",raw={})
    run = AiRun(id=uuid.uuid4(),user_id=user.id,task_type="training_plan",prompt="test",content="Plan",metadata_json={"structured_plan":{"format_version":1,"title":"Plan","weeks":1,"sessions":[{"id":"s1","week":1,"day":1,"name":"Run","sport":"running","duration_min":5,"steps":[step()]}]}})
    db.add_all([activity,run]);await db.flush()
    db.add(PlanSchedule(plan_run_id=run.id,user_id=user.id,start_date=insights.user_today(user)))
    db.add(PlanActivityMatch(user_id=user.id,plan_run_id=run.id,session_id="s1",activity_id=activity.id,state="matched"))
    path=tmp_path/'run.parquet';pd.DataFrame({"timestamp":pd.date_range('2026-10-10',periods=61,freq='s',tz='UTC'),"heart_rate":[140]*61}).to_parquet(path)
    db.add(FitFile(user_id=user.id,activity_id=activity.id,original_path="run.fit",parquet_path=str(path),file_size=1,sha256="x",status="parsed"));await db.commit()
    async def snapshot(db,user_id):
        return {"source":"garmin","heart_rate":{"profiles":[{"sport":"RUNNING","zones":[{"zone":2,"low_bpm":120,"high_bpm":150}]}]}}
    monkeypatch.setattr(insights,"training_zone_snapshot",snapshot)
    result=await insights.goal_review(activity.id,None,None,0,user,db)
    assert result["review"]["in_target_pct"] == 100
    assert result["selected"]["match_basis"] == "user_confirmed"
    assert not insights._profile({"heart_rate":{"profiles":[{"sport":"CYCLING","zones":[1]}]}},"heart_rate","running")


async def test_http_validates_ranges_and_offset(db_users):
    from httpx import AsyncClient, ASGITransport
    from apps.api.main import app
    from pengucoach.auth.dependencies import safety_confirmed_user
    from pengucoach.db.session import get_db
    db,user,_ = db_users
    async def database():
        yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[safety_confirmed_user]=lambda:user
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
            assert (await client.get('/api/v1/coach/progress?days=6')).status_code == 422
            assert (await client.get('/api/v1/coach/progress?days=7')).status_code == 200
            assert (await client.get(f'/api/v1/activities/{uuid.uuid4()}/goal-review?offset_s=-1')).status_code == 422
    finally:
        app.dependency_overrides.clear()


async def test_route_api_checks_real_tracks_and_excludes_other_users(db_users, tmp_path):
    db,user,other = db_users
    now=datetime.now(timezone.utc)-timedelta(hours=1)
    rows=[]
    for index, owner in enumerate((user,user,other)):
        a=Activity(id=uuid.uuid4(),user_id=owner.id,garmin_activity_id=-100-index,started_at=now-timedelta(days=index),sport_type="running",duration_seconds=60,distance_m=600,name="Same track",raw={})
        db.add(a);await db.flush()
        path=tmp_path/f'{index}.parquet'
        points=samples()
        frame=pd.DataFrame(points)
        frame['timestamp']=pd.date_range(now,periods=61,freq='s')
        frame['distance']=frame['distance_km']*1000
        frame['speed']=3.6
        frame.to_parquet(path)
        db.add(FitFile(user_id=owner.id,activity_id=a.id,original_path="run.fit",parquet_path=str(path),file_size=1,sha256=str(index),status="parsed"))
        rows.append(a)
    await db.commit()
    result=await insights.route_comparison(rows[0].id,0,100,"distance",user,db)
    assert len(result["items"])==1 and result["items"][0]["activity_id"]==str(rows[1].id)
    assert result["reference"]["avg_hr"]==140
    segment=await insights.route_comparison(rows[0].id,25,75,"distance",user,db)
    assert segment["segment"] and len(segment["items"])==1
    assert segment["reference"]["distance_km"]==.3


def test_mixed_steps_and_track_breaks_are_not_reported_as_success():
    points=samples(n=101)
    for index,row in enumerate(points):
        row['heart_rate']=100 if index<16 else 180 if index<32 else 140
    result=evaluate_goals(points,{"steps":[step(100)]},{"heart_rate_zone":[{"zone":2,"low":120,"high":150}]})
    assert result['status']=='mixed'
    broken=[{**r,'track_segment':0 if i==0 else 1} for i,r in enumerate(samples(n=3,interval=20))]
    result=evaluate_goals(broken,{"steps":[step(40)]},{"heart_rate_zone":[{"zone":2,"low":120,"high":150}]})
    assert result['coverage_pct']==50 and result['status']=='unassessed'


def test_closed_routes_match_finish_to_finish_and_reject_reversed_direction():
    import math
    rows=[dict(position_lat=52+.004*math.sin(i/120*2*math.pi),position_long=13+.004*math.cos(i/120*2*math.pi),distance_km=i*.025,elapsed_s=i*10) for i in range(121)]
    assert route_match(rows,rows)['end_index']==120
    reverse=[{**r,'position_lat':rows[-1-i]['position_lat'],'position_long':rows[-1-i]['position_long']} for i,r in enumerate(rows)]
    assert route_match(rows,reverse) is None


def test_distance_boundary_is_not_interpolated_across_a_recording_gap():
    rows=[{'elapsed_s':t,'distance_km':d,'heart_rate':140} for t,d in [(0,0),(10,.1),(100,1),(110,1.1)]]
    planned={'type':'work','distance_meters':600,'target':{'type':'heart_rate_zone','zone':2}}
    result=evaluate_goals(rows,{'steps':[planned,step()]},{'heart_rate_zone':[{'zone':2,'low':120,'high':150}]})
    assert result['reason']=='distance_boundary_gap' and result['status']=='unassessed'
    assert len(result['steps'])==1
