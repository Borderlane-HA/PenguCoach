import copy
import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from kombu.serialization import dumps
from sqlalchemy import select

from test_alpha61_continuation import data  # noqa: F401 shared real SQLite/worker fixture
from apps.api.routers import activities, continuation as continuation_api
from pengucoach.db.models import Activity, AiRun, GarminConnection, User, SourceRecord
from pengucoach.fit.service import load_recording_detail, load_recording_series
from pengucoach.garmin.gateway.workouts import build_typed_workout
from pengucoach.garmin.sync import service as garmin
from pengucoach.sparkyfitness.client import SparkyFitnessError
from pengucoach.sparkyfitness.telemetry import KEY, enrich_telemetry, frame, zones
from pengucoach.training_plan.structured import StrengthExercise, TrainingSession, TrainingPlanDocument, render_plan_markdown
from worker.tasks import ai, continuation as worker


def session(**kw):
    return dict(id='s', week=1, day=1, name='Strength', sport='strength', duration_min=30) | kw


@pytest.mark.parametrize('value,expected', [('6-8',(6,8,None,None)),('12–15',(12,15,None,None)),('45s',(None,None,45,None)),('1 min',(None,None,60,None)),('max-2',(None,None,None,2)),('max−2',(None,None,None,2))])
def test_strength_values_preserve_meaning(value,expected):
    if expected is None:
        with pytest.raises(ValidationError):StrengthExercise(name='Plank',reps=value)
        return
    ex=StrengthExercise(name='Plank',reps=value)
    assert (ex.reps,ex.reps_max,ex.duration_seconds,ex.reps_in_reserve)==expected
    assert StrengthExercise.model_validate(ex.model_dump())==ex

@pytest.mark.parametrize('fields', [{'reps':0},{'reps':'8-6'},{'reps':'8-101'},{'reps':True},{'reps':8,'duration_seconds':45},{'reps':None},{'reps':None,'reps_max':10},{'reps':'nonsense'},{'reps':None,'duration_seconds':-1}])
def test_invalid_strength_values_remain_invalid(fields):
    with pytest.raises(ValidationError):StrengthExercise(name='Plank',**fields)


def test_timed_exercise_default_zero_placeholder_and_legacy():
    for fields in ({'duration_seconds':45},{'duration_seconds':45,'reps':0}):
        assert StrengthExercise(name='Plank',**fields).reps is None
    assert StrengthExercise(name='Squat').reps==10


def test_strength_markdown_and_export_use_time_or_lap_not_fake_reps():
    s=TrainingSession(**session(strength_exercises=[{'name':'Plank','reps':'45s'},{'name':'Push-up','reps':'8-10'},{'name':'Pull-up','reps':'max-2'}]))
    plan=TrainingPlanDocument(title='Plan',weeks=1,sessions=[s])
    text=render_plan_markdown(plan)
    assert '3×45 s' in text and '3×8–10' in text and 'max − 2 Wdh.' in text
    groups=build_typed_workout(s).to_dict()['workoutSegments'][0]['workoutSteps']
    work=[g['workoutSteps'][0] for g in groups]
    assert work[0]['endCondition']['conditionTypeKey']=='time' and work[0]['endConditionValue']==45
    for row in work[1:]:
        assert row['endCondition']['conditionTypeKey']=='lap.button'
        assert 'endConditionValue' not in row
    assert '8–10' in work[1]['description'] and 'max − 2 reps' in work[2]['description']
    assert all(g['numberOfIterations']==3 and g['workoutSteps'][1]['endConditionValue']==90 for g in groups)


def recording():
    stamp='2026-10-17T12:38:'
    return {'source':'sparkyfitness','sparkyfitness':{KEY:{'version':1,'status':{'gps':'available','laps':'available','hr_zones':'available'},
        'gps':[{'t':stamp+f'{i:02d}Z','lat':52.5+i*.00001,'lon':13.4,'alt':100+i,'speed':1.5,'hr':95+i,'power':0,'cad':110,'dist':i*1.5,'vo':76,'gct':240,'stride':110,'temp':0} for i in range(6)],
        'laps':[{'lap_index':1,'duration_seconds':5,'distance_meters':7.5,'avg_heart_rate':98,'max_heart_rate':100,'avg_speed_mps':1.5}],
        'hr_zones':[{'zone_index':1,'zone_lower_bpm':90,'zone_upper_bpm':110,'seconds_in_zone':5}]}}}


def activity(raw=None):
    return SimpleNamespace(raw=raw if raw is not None else recording(),sport_type='hiking')


def test_sparky_recording_drives_charts_stats_laps_and_zones():
    a=activity();rows=load_recording_series(a,None,100)
    assert len(rows)==6 and rows[0]['elapsed_s']==0 and rows[-1]['elapsed_s']==5
    assert rows[-1]['heart_rate']==100 and rows[0]['position_lat']==52.5
    assert rows[0]['speed_kmh']==5.4 and rows[0]['temperature']==0 and rows[0]['power']==0
    detail=load_recording_detail(a,None)
    assert detail['stats']['heart_rate']['min']==95 and detail['source']=='sparkyfitness'
    assert detail['laps'][0]['total_distance']==7.5 and detail['laps'][0]['avg_heart_rate']==98
    assert detail['hr_zones'][0]=={'zone_number':1.,'min_bpm':90.,'max_bpm':110.,'duration_seconds':5.}
    json.dumps(detail,allow_nan=False);json.dumps(rows,allow_nan=False)
    assert len(load_recording_series(a,None,2))==2


def test_summary_only_is_not_fabricated_as_a_recording():
    a=activity({'sparkyfitness':{'raw_data':{'startTime':'2026-10-17T12:38:11Z','duration':{'quantity':1680},'totalDistance':2315}}})
    assert load_recording_series(a,None)==[] and load_recording_detail(a,None)['stats'] is None


def test_bad_samples_times_and_coordinates_stay_missing():
    raw=recording();points=raw['sparkyfitness'][KEY]['gps']
    points.extend([dict(points[0],t='invalid'),dict(points[0],t='2026-10-17T12:38:00'),dict(points[0])])
    points[1].update(hr=0,speed='NaN',lat=1000,temp=True,power='Infinity')
    points[-3]['lat']=True
    rows=load_recording_series(activity(raw),None)
    assert len(rows)==6
    assert rows[1]['heart_rate'] is None and rows[1]['speed'] is None and rows[1]['position_lat'] is None
    assert rows[1]['position_long'] is None and rows[1]['temperature'] is None
    points[5]['t']='2026-10-17T12:45:00Z'
    # alpha.80: a time gap alone no longer splits a simplified track ...
    assert frame(raw).iloc[-1]['track_segment']==0
    # ... an impossible jump after the gap does.
    points[5]['lat']=points[0]['lat']+1
    assert frame(raw).iloc[-1]['track_segment']==1


async def test_real_sparky_endpoint_shapes_cache_and_permission_fallback():
    calls=[];raw=recording()['sparkyfitness'][KEY]
    class Client:
        async def request(self,path):
            calls.append(path)
            if 'workout-gps/' in path:return {'data':{'points':raw['gps']}}
            if 'workout-laps/' in path:return {'data':raw['laps']}
            return {'data':raw['hr_zones']}
    client=Client();result,count=await enrich_telemetry(client,{'id':'entry'})
    assert count==3 and result[KEY]['gps']==raw['gps'] and len(calls)==3
    assert all(x.startswith('/generic-health/workout-') and x.endswith('/entry') for x in calls)
    cached,count=await enrich_telemetry(client,{'id':'entry'},result,refresh=False)
    assert count==0 and cached[KEY]==result[KEY]
    class Denied:
        async def request(self,path):raise SparkyFitnessError('denied',status_code=403)
    denied=Denied();first,count=await enrich_telemetry(denied,{'id':'one'},result)
    assert count==3 and first[KEY]['gps']==raw['gps'] and set(first[KEY]['status'].values())=={'permission_denied'}
    second,count=await enrich_telemetry(denied,{'id':'two'})
    assert count==0 and not second[KEY].get('gps')


async def test_invalid_plan_checkpoint_resumes_without_budget_increase(data,monkeypatch):
    factory,uid,_,mid=data;calls=[]
    monkeypatch.setattr(ai,'build_training_plan_context',AsyncMock(return_value={'lookback':{'days':7}}))
    monkeypatch.setattr(ai,'add_personal_context',AsyncMock(return_value={}))
    monkeypatch.setattr(ai,'build_training_weather_context',AsyncMock(return_value=None))
    def doc(valid=True):
        return json.dumps({'title':'Plan','weeks':2,'sessions':[dict(session(id=f's{w}-{d}',week=w,day=d),strength_exercises=[{'name':'Squat','reps':8 if valid else 0}]) for w in [1,2] for d in [1,2,3,4]]})
    async def chat(db,messages,context,locale,**kw):
        calls.append((context['goal']['plan_week_start'],kw['requested_max_tokens'],kw['instruction_prompt']+' '.join(m['content'] for m in messages)))
        valid=len(calls)==1 or len(calls)>3
        return {'content':doc(valid),'model_id':str(mid),'provider':'IONOS','model':'Qwen','max_output_tokens':kw['requested_max_tokens'],
            'usage':{'input_tokens':10,'output_tokens':20,'total_tokens':30},'truncated':False,'stop_reason':'stop','cost_eur':.01}
    monkeypatch.setattr(ai,'chat',chat)
    r=await ai._training_plan(str(uid),{'weeks':4,'days_per_week':4,'session_minutes':30,'max_tokens':3500,'model_id':str(mid),'use_personal_context':False})
    assert len(calls)==3 and r['metadata']['draft'] and r['metadata']['validated_weeks']==2
    assert not r['metadata']['truncated'] and r['continuation']['reason']=='invalid_plan'
    assert 'Previous attempt was invalid:' in calls[-1][2] and r['usage']['total_tokens']==90
    async with factory() as db:
        user=await db.get(User,uid)
        queued=await continuation_api.continue_run(uuid.UUID(r['run_id']),continuation_api.ContinueIn(revision=0,additional_tokens=0),user,db)
    done=await worker._continue(str(uid),{'run_id':r['run_id'],'revision':1},task_id=queued['task_id'])
    assert done['run_id']==r['run_id'] and len(calls)==4 and calls[-1][:2]==(3,3500)
    assert done['metadata']['structured_plan_valid'] and done['usage']['total_tokens']==120
    assert {s['week'] for s in done['metadata']['structured_plan']['sessions']}=={1,2,3,4}


async def test_sparky_api_uses_samples_without_fit_and_protects_owner(data):
    factory,uid,other,_=data
    async with factory() as db:
        a=Activity(user_id=uid,garmin_activity_id=-100,name='Hike',sport_type='hiking',started_at=datetime(2026,10,17,12,38,tzinfo=timezone.utc),raw=recording())
        db.add(a);await db.commit();user=await db.get(User,uid)
        assert len((await activities.series(a.id,100,user,db))['data'])==6
        detail=await activities.activity_analysis(a.id,user,db)
        assert detail['stats']['heart_rate']['min']==95 and len(detail['laps'])==1
        with pytest.raises(Exception) as exc:await activities.series(a.id,100,await db.get(User,other),db)
        assert exc.value.status_code==404


async def test_garmin_sync_result_can_cross_celery_json_boundary(data,monkeypatch):
    factory,uid,_,_=data
    class Gateway:
        def __getattr__(self,key):return lambda *a:[] if key=='get_activities_by_date' else {}
    monkeypatch.setattr(garmin,'gateway_from_connection',AsyncMock(return_value=(Gateway(),None)))
    monkeypatch.setattr(garmin,'serialize_refreshed_token',lambda _: 'refreshed')
    for method in ['_upsert_health','_upsert_sleep','_upsert_hrv','_upsert_body','_store_raw']:
        monkeypatch.setattr(garmin,method,AsyncMock())
    async with factory() as db:
        user=await db.get(User,uid);conn=GarminConnection(user_id=uid,status='connected',token_ciphertext='x')
        a=Activity(user_id=uid,garmin_activity_id=100,name='Ride',sport_type='cycling',started_at=datetime.now(timezone.utc))
        db.add_all([conn,a]);await db.commit()
        monkeypatch.setattr(garmin,'_upsert_activities',AsyncMock(return_value=(1,[a])))
        result=await garmin.run_incremental_sync(db,user,conn)
        assert result['status']=='success' and all(d['activity_ids']==[str(a.id)] for d in result['days'])
        dumps(result,serializer='json')
        assert 'activity_rows' not in json.dumps(result)


def test_fit_remains_primary_over_sparky_recording(tmp_path):
    import pandas as pd
    path=tmp_path/'fit.parquet'
    pd.DataFrame({'timestamp':pd.date_range('2026-10-17T12:00:00Z',periods=3,freq='s'),
        'heart_rate':[70,72,74],'position_lat':[50,50.001,50.002],'position_long':[10,10,10]}).to_parquet(path)
    fit=SimpleNamespace(status='parsed',parquet_path=str(path))
    assert load_recording_series(activity(),fit)[0]['heart_rate']==70
    assert load_recording_detail(activity(),fit)['stats']['heart_rate']['min']==70
    assert load_recording_detail(activity(),fit)['source']=='fit'


async def test_sync_persists_separate_telemetry_in_existing_activity_and_source(data):
    from pengucoach.sparkyfitness.sync import _sync_activities
    factory,uid,_,_=data
    item={'id':'hike-one','entry_date':'2026-10-17','entry_time':'14:38','record_timezone':'Europe/Berlin',
        'exercise_name':'Hiking','duration_minutes':28,'distance':2.315,'calories_burned':124}
    measured=recording()['sparkyfitness'][KEY]
    class Client:
        async def request(self,path,params=None):
            if path.endswith('/history'):return [item]
            if path.startswith('/exercise-entries/'):return item
            if 'workout-gps' in path:return {'data':{'points':measured['gps']}}
            if 'workout-laps' in path:return {'data':measured['laps']}
            if 'workout-hr-zones' in path:return {'data':measured['hr_zones']}
            raise AssertionError(path)
    async with factory() as db:
        first=await _sync_activities(db,Client(),uid,None);await db.commit()
        a=await db.scalar(select(Activity).where(Activity.user_id==uid));identifier=a.id
        assert first['activities_created']==1 and len(a.raw['sparkyfitness'][KEY]['gps'])==6
        source=await db.scalar(select(SourceRecord).where(SourceRecord.user_id==uid))
        assert source.payload[KEY]['laps'][0]['lap_index']==1
        second=await _sync_activities(db,Client(),uid,None);await db.commit()
        a=await db.scalar(select(Activity).where(Activity.user_id==uid))
        assert a.id==identifier and second['activities_created']==0
        assert len(load_recording_series(a,None))==6


def test_provider_detail_array_and_json_string_are_walked_without_visiting_gps_samples():
    from pengucoach.fit.activity_detail import selected_activity_extras
    from pengucoach.sparkyfitness.activity_time import resolve_activity_time
    raw={'sparkyfitness':{'entry_date':'2026-10-17','entry_time':'14:38','record_timezone':'Europe/Berlin',
        'provider_activity_details':{'details':[{'detail_type':'ExerciseSession_raw_data','detail_data':json.dumps({'startTime':'2026-10-17T12:38:11Z','minHeartRate':92})}]}}}
    assert selected_activity_extras(raw)['min_hr_bpm']==92
    assert resolve_activity_time(raw['sparkyfitness']).timestamp.minute==38


def test_first_gps_fix_keeps_its_offset_from_actual_recording_start():
    a=activity();a.raw['_sparkyfitness_time']={'precision':'second'}
    a.started_at=datetime(2026,10,17,12,37,45,tzinfo=timezone.utc)
    rows=load_recording_series(a,None)
    assert rows[0]['elapsed_s']==15 and rows[-1]['elapsed_s']==20
    a.raw['_sparkyfitness_time']={'precision':'date'}
    assert load_recording_series(a,None)[0]['elapsed_s']==0
