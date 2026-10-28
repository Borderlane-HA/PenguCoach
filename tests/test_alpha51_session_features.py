import copy
import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.routers import companion, session_features as api
from pengucoach.coach.session_features import alternative_days, best_efforts, matching_experiences, route_briefing, route_plan_overlay, active_experiences
from pengucoach.coach.training_intelligence import plan_conflicts
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachProfile, FitFile, GarminWorkoutExport, PlanSchedule, User


def samples(n=1201):
    return [{'elapsed_s':i,'power':200,'speed_kmh':12,'heart_rate':140,'distance_km':i*.003,'altitude_m':100+i*.15,'position_lat':52,'position_long':13+i*.00004} for i in range(n)]


def test_best_efforts_weight_seconds_and_split_exact_window_edges():
    rows=[{'elapsed_s':t,'power':p} for t,p in [(0,0),(10,100),(20,500),(40,500),(60,500),(80,0),(90,0)]]
    effort=best_efforts(rows,(60,))[0]
    assert effort['value']==500 and (effort['start_s'],effort['end_s'])==(20,80)
    # A boundary on the end minus window, not just a recorded start, can win.
    rows=[{'elapsed_s':t,'power':p} for t,p in [(0,10),(17,20),(33,100),(50,50),(70,20),(90,0)]]
    effort=best_efforts(rows,(40,))[0]
    assert effort['start_s']==30 and effort['value']==69


def test_best_efforts_require_whole_windows_and_keep_zero_watts():
    rows=samples()
    assert len(best_efforts(rows))==6
    assert best_efforts([{**r,'power':0} for r in rows])[0]['value']==0
    assert not best_efforts([{'power':100}]*100)
    assert not best_efforts([{'elapsed_s':0,'power':500},{'elapsed_s':61,'power':500}])
    rows=samples(61);rows[30]['power']=None
    assert all(e['metric']!='power' for e in best_efforts(rows))
    rows=samples(61);rows[30]['track_segment']=2
    assert not best_efforts(rows)
    rows=samples(61);rows[30]['elapsed_s']=20
    assert not best_efforts(rows)


def test_hills_need_recorded_gps_distance_and_height():
    rows=samples(401)
    hills=route_briefing(rows)['hills']
    assert len(hills)==1 and hills[0]['gain_m']>=50 and hills[0]['grade_pct']==5
    assert 'avg_hr' in hills[0]['metrics']
    assert not route_briefing([{**r,'altitude_m':None} for r in rows])['hills']
    assert not route_briefing([{**r,'position_lat':None} for r in rows])['hills']
    assert not route_briefing([{**r,'altitude_m':100} for r in rows])['hills']
    no_sensor=route_briefing([{**r,'power':None,'heart_rate':None} for r in rows])['hills'][0]
    assert 'avg_power' not in no_sensor['metrics'] and 'avg_hr' not in no_sensor['metrics']


def test_route_overlay_never_fabricates_time_or_distance_step_durations():
    steps=[{'type':'warmup','duration_seconds':60},{'type':'repeat','repeat':2,'steps':[{'type':'interval','duration_seconds':120,'target':{'type':'heart_rate_zone','zone':4}},{'type':'recovery','duration_seconds':60}]}]
    result=route_plan_overlay(samples(501),{'steps':steps})
    assert len(result['items'])==5 and result['items'][1]['start_s']==60
    assert result['items'][1]['distance_km']==pytest.approx(.18)
    assert not result['recording_shorter']
    assert route_plan_overlay(samples(100),{'steps':steps})['recording_shorter']
    assert route_plan_overlay([{'distance_km':1}]*30,{'steps':steps})['reason']=='missing_time'
    assert route_plan_overlay(samples(),{'steps':[{'type':'work','distance_meters':1000}]})['reason']=='distance_steps'


def test_hard_day_detection_includes_easy_same_day_and_other_plans():
    rows=[{'id':'hard1','name':'Intervals','date':'2026-10-12'},{'id':'easy','name':'Easy','date':'2026-10-12'},{'id':'hard2','name':'Intervals','date':'2026-10-13'}]
    assert any(c['type']=='hard_back_to_back' and c['session_id']=='hard2' for c in plan_conflicts(rows,{}))
    assert any(c['type']=='hard_back_to_back' for c in plan_conflicts(rows[:1],{},other_plan_sessions=[rows[2]]))


def test_alternative_dates_respect_hard_spacing_weekdays_bounds_and_locks():
    rows=[{'id':'s1','name':'Intervals','date':'2026-10-12'},{'id':'s2','name':'Intervals','date':'2026-10-13'}]
    result=alternative_days(rows,{'training_days':[1,3,5]},date(2026,10,12),1,today=date(2026,10,12),locked=['s1'])
    assert 's1' not in result
    assert all(a['date']>='2026-10-14' and a['day'] in [3,5] for a in result['s2'])
    assert rows[1]['date']=='2026-10-13'
    result=alternative_days(rows,{'training_days':[1]},date(2026,10,12),1,today=date(2026,10,12))
    assert not result['s2']


def test_experiences_match_explicit_sport_and_type_only():
    entries=[{'text':'Run intervals','sport':'running','kind':'interval','enabled':True},{'text':'Ride','sport':'cycling','kind':'all','enabled':True},{'text':'Paused','sport':'running','kind':'all','enabled':False}]
    assert matching_experiences(entries,{'name':'Easy','sport':'running'})==[]
    assert matching_experiences(entries,{'name':'Intervals','sport':'running'})[0]['text']=='Run intervals'


@compiles(JSONB,'sqlite')
def json_type(type_,compiler,**kw):
    return 'JSON'


@pytest.fixture
async def db_users():
    engine=create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        users=[User(id=uuid.uuid4(),username=n,email=f'{n}@test.dev',password_hash='x',timezone='Europe/Berlin') for n in ('owner','other')]
        db.add_all(users);await db.commit()
        yield db,*users
    await engine.dispose()


async def recorded(db,user,tmp_path,*,sport='running',identifier=-1):
    activity=Activity(id=uuid.uuid4(),user_id=user.id,garmin_activity_id=identifier,sport_type=sport,started_at=datetime.now(timezone.utc)-timedelta(hours=2),name='Private route',raw={})
    db.add(activity);await db.flush()
    rows=samples();frame=pd.DataFrame(rows)
    frame['timestamp']=pd.date_range(datetime.now(timezone.utc)-timedelta(hours=2),periods=len(frame),freq='s')
    frame['distance']=frame['distance_km']*1000;frame['altitude']=frame['altitude_m'];frame['speed']=frame['speed_kmh']/3.6
    path=tmp_path/f'{identifier}.parquet';frame.to_parquet(path)
    db.add(FitFile(activity_id=activity.id,user_id=user.id,original_path='x.fit',parquet_path=str(path),sha256=str(identifier),file_size=1,status='parsed'))
    await db.commit()
    return activity


async def test_experiences_feedback_notes_independent_and_user_scoped(db_users,tmp_path):
    db,user,other=db_users;activity=await recorded(db,user,tmp_path)
    await companion.save_feedback(activity.id,companion.FeedbackIn(feeling='hard',comment='Keep feedback'),user,db)
    await api.save_experience(activity.id,api.ExperienceIn(text='After work harder',kind='interval'),user,db)
    note=await api.save_route_note(activity.id,api.RouteNoteIn(text='<script>gravel</script>',point_index=100),user,db)
    await companion.save_feedback(activity.id,companion.FeedbackIn(feeling='right'),user,db)
    row=await db.get(ActivityFeedback,activity.id)
    assert row.data['experience']['text']=='After work harder' and row.data['route_notes'][0]['id']==note['id']
    assert not await api.list_experiences(other,db)
    with pytest.raises(HTTPException):
        await api.save_experience(activity.id,api.ExperienceIn(text='No'),other,db)
    with pytest.raises(HTTPException):
        await api.save_route_note(activity.id,api.RouteNoteIn(text='No',point_index=0),other,db)
    with pytest.raises(HTTPException):
        await api.delete_route_note(activity.id,uuid.UUID(note['id']),other,db)
    await companion.delete_feedback(activity.id,user,db)
    assert row.data['experience'] and row.data['route_notes'] and 'feeling' not in row.data
    await api.delete_experience(activity.id,user,db)
    assert 'experience' not in row.data and row.data['route_notes']
    await api.delete_route_note(activity.id,uuid.UUID(note['id']),user,db)
    assert not row.data['route_notes']


async def test_profile_disable_and_clear_include_training_experiences(db_users,tmp_path):
    db,user,_=db_users;activity=await recorded(db,user,tmp_path)
    await api.save_experience(activity.id,api.ExperienceIn(text='My experience'),user,db)
    await api.save_route_note(activity.id,api.RouteNoteIn(text='My note',point_index=10),user,db)
    assert await active_experiences(db,user)
    db.add(CoachProfile(user_id=user.id,data={'enabled':False}));await db.commit()
    assert not await active_experiences(db,user)
    await companion.clear_profile(user,db)
    assert not await api.list_experiences(user,db)
    assert (await db.get(ActivityFeedback,activity.id)).data['route_notes']


async def test_recorded_effort_api_and_route_briefing_ownership(db_users,tmp_path):
    db,user,other=db_users;activity=await recorded(db,user,tmp_path)
    efforts=await api.activity_efforts(activity.id,user,db)
    assert len(efforts['items'])==6 and efforts['items'][0]['value']==200
    own=await api.personal_efforts('running',user,db)
    assert own['scanned']==1 and len(own['items'])==6
    assert not (await api.personal_efforts('cycling',user,db))['items']
    assert not (await api.personal_efforts('running',other,db))['items']
    with pytest.raises(HTTPException):
        await api.activity_efforts(activity.id,other,db)
    with pytest.raises(HTTPException):
        await api.get_route_briefing(activity.id,None,None,other,db)
    brief=await api.get_route_briefing(activity.id,None,None,user,db)
    assert brief['hills'] and brief['overlay'] is None
    with pytest.raises(HTTPException):
        await api.save_route_note(activity.id,api.RouteNoteIn(text='outside',point_index=4999),user,db)


async def plan(db,user):
    start=api.user_today(user);start-=timedelta(days=start.weekday());start+=timedelta(days=7)
    sessions=[{'id':f's{i}','week':1,'day':i+1,'name':'Intervals','sport':'running','duration_min':40,'steps':[{'type':'work','duration_seconds':2400,'target':{'type':'heart_rate_zone','zone':4}}]} for i in range(2)]
    run=AiRun(id=uuid.uuid4(),user_id=user.id,task_type='training_plan',prompt='x',content='x',metadata_json={'structured_plan':{'format_version':1,'title':'Plan','weeks':1,'sessions':sessions}})
    db.add(run);await db.flush();schedule=PlanSchedule(plan_run_id=run.id,user_id=user.id,start_date=start,overrides={},revision=1);db.add(schedule);await db.commit()
    return run,schedule,sessions


async def test_draft_check_is_read_only_and_preserves_revision_exports_and_owner(db_users):
    db,user,other=db_users;run,schedule,sessions=await plan(db,user)
    payload=companion.ScheduleIn(start_date=schedule.start_date,overrides={},revision=1)
    result=await api.check_schedule(run.id,payload,user,db)
    assert result['read_only'] and any(c['type']=='hard_back_to_back' for c in result['conflicts'])
    assert result['conflicts'][0]['alternatives']
    assert schedule.revision==1 and schedule.overrides=={}
    with pytest.raises(HTTPException):await api.check_schedule(run.id,payload,other,db)
    with pytest.raises(HTTPException):await api.check_schedule(run.id,payload.model_copy(update={'revision':0}),user,db)
    db.add(GarminWorkoutExport(user_id=user.id,plan_run_id=run.id,session_id='s0',status='exported',scheduled_date=schedule.start_date,workout_id=123));await db.commit()
    changed=copy.deepcopy(sessions[0]);changed['day']=5
    with pytest.raises(HTTPException) as error:
        await api.check_schedule(run.id,payload.model_copy(update={'overrides':{'s0':changed}}),user,db)
    assert error.value.detail=='EXPORTED_SESSION_LOCKED'


async def test_http_new_feature_input_validation(db_users):
    from httpx import AsyncClient, ASGITransport
    from apps.api.main import app
    from pengucoach.auth.dependencies import safety_confirmed_user
    from pengucoach.db.session import get_db
    db,user,_=db_users
    async def database():yield db
    app.dependency_overrides[get_db]=database;app.dependency_overrides[safety_confirmed_user]=lambda:user
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get('/api/v1/coach/best-efforts?sport=invalid')).status_code==422
            assert (await client.get('/api/v1/coach/experiences')).json()==[]
            assert (await client.put(f'/api/v1/coach/experiences/{uuid.uuid4()}',json={'text':'','kind':'all'})).status_code==422
            assert (await client.put(f'/api/v1/activities/{uuid.uuid4()}/route-notes',json={'text':'x','point_index':-1})).status_code==422
    finally:app.dependency_overrides.clear()


async def test_paused_experiences_and_route_notes_do_not_leak_into_ai_feedback(db_users,tmp_path):
    from pengucoach.coach.companion import personal_context
    db,user,_=db_users;activity=await recorded(db,user,tmp_path)
    await companion.save_feedback(activity.id,companion.FeedbackIn(comment='Ordinary feedback'),user,db)
    await api.save_experience(activity.id,api.ExperienceIn(text='Paused private experience',enabled=False),user,db)
    await api.save_route_note(activity.id,api.RouteNoteIn(text='Private route note',point_index=10),user,db)
    context=await personal_context(db,user,training=True,recovery=False)
    assert not context['training_experiences']
    assert context['recent_feedback'][0]['comment']=='Ordinary feedback'
    assert 'experience' not in context['recent_feedback'][0]
    assert 'route_notes' not in context['recent_feedback'][0]


async def test_route_notes_work_without_time_and_keep_hills_split(db_users,tmp_path,monkeypatch):
    db,user,_=db_users;activity=await recorded(db,user,tmp_path)
    rows=[{**r,'elapsed_s':None} for r in samples(401)]
    async def series(*args):return rows
    monkeypatch.setattr(api,'_series',series)
    note=await api.save_route_note(activity.id,api.RouteNoteIn(text='GPX note',point_index=30),user,db)
    assert note['start_s'] is None and note['distance_km']==pytest.approx(.09)
    brief=await api.get_route_briefing(activity.id,None,None,user,db)
    assert brief['notes'][0]['text']=='GPX note' and brief['hills']
    broken=samples(401);broken[200]['altitude_m']=None
    hills=route_briefing(broken)['hills']
    assert len(hills)==2 and max(h['length_m'] for h in hills)<650


def test_missing_clock_breaks_only_windows_crossing_the_missing_sample():
    rows=samples(200);rows[80]['elapsed_s']=None
    efforts=best_efforts(rows,(60,))
    assert len(efforts)==2
    assert all(e['end_s']<=79 or e['start_s']>=81 for e in efforts)


async def test_route_plan_selection_excludes_completed_sessions_and_other_owners(db_users,tmp_path):
    from pengucoach.db.models import PlanActivityMatch
    db,user,other=db_users;activity=await recorded(db,user,tmp_path)
    run,schedule,sessions=await plan(db,user)
    result=await api.get_route_briefing(activity.id,run.id,'s0',user,db)
    assert result['overlay']['items'] and result['overlay']['recording_shorter']
    assert len(result['plans'])==2
    with pytest.raises(HTTPException):await api.get_route_briefing(activity.id,uuid.uuid4(),'s0',user,db)
    db.add(PlanActivityMatch(user_id=user.id,plan_run_id=run.id,session_id='s0',activity_id=activity.id,state='matched'));await db.commit()
    result=await api.get_route_briefing(activity.id,None,None,user,db)
    assert all(s['session_id']!='s0' for s in result['plans'])
    with pytest.raises(HTTPException):await api.get_route_briefing(activity.id,run.id,'s0',user,db)
