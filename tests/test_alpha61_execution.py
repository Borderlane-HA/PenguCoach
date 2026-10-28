import copy
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from apps.api.routers import execution as api, plan_evolution as matches
from pengucoach.coach import execution as domain
from pengucoach.coach.plan_evolution import compare_v2, planned_start, seconds
from pengucoach.coach.workout_review import evaluate_goals
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, FitFile, GarminWorkoutExport, PlanActivityMatch, PlanSchedule, TrainingReview, User
from pengucoach.training_plan.structured import PlanStep
from pengucoach.garmin.gateway.workouts import _target_payload

@compiles(JSONB, 'sqlite')
def json_sqlite(type_, compiler, **kw):return 'JSON'

def session(**values):
    return {'id':'s1','week':1,'day':1,'name':'4 × 1 min','sport':'cycling','duration_min':28,
        'steps':[{'type':'warmup','duration_seconds':600},{'type':'repeat','repeat':4,'steps':[
        {'type':'interval','duration_seconds':60,'target':{'type':'power_watts','watts':250}},
        {'type':'recovery','duration_seconds':60}]},{'type':'cooldown','duration_seconds':600}],**values}

def activity(stamp):
    return SimpleNamespace(id=uuid.uuid4(),name='Ride',sport_type='cycling',started_at=datetime.fromisoformat(stamp),duration_seconds=1680,avg_hr=None,avg_power=None)

def test_four_hour_matching_crosses_midnight_and_incomplete_duration():
    user=SimpleNamespace(timezone='Europe/Berlin');s=session(date='2026-10-10',start_time='23:00')
    a=activity('2026-10-11T00:59:00+00:00');a.duration_seconds=600
    result=compare_v2([s],[a],user)[0]
    assert result['status']=='matched' and result['match_basis']=='within_four_hours_sport'
    a.started_at=datetime.fromisoformat('2026-10-11T01:01:00+00:00')
    assert compare_v2([s],[a],user)[0]['activity_id'] is None

def test_matching_ambiguity_reservations_other_plans_and_date_only():
    user=SimpleNamespace(timezone='UTC');s=session(date='2026-10-10',start_time='10:00')
    a,b=activity('2026-10-10T09:00:00+00:00'),activity('2026-10-10T11:00:00+00:00')
    assert compare_v2([s],[a,b],user)[0]['status']=='ambiguous'
    assert compare_v2([s],[a],user,reserved={str(a.id)})[0]['activity_id'] is None
    assert compare_v2([s],[a],user,other_sessions=[{**s,'id':'other','match_key':'other:other'}])[0]['activity_id'] is None
    assert compare_v2([{**s,'start_time':None}],[a],user)[0]['status']=='matched'
    a.sport_type='running';assert compare_v2([s],[a],user)[0]['activity_id'] is None

@pytest.mark.parametrize('day',['2026-03-29','2026-10-25'])
def test_dst_nonexistent_and_ambiguous_times_need_manual_matching(day):
    assert planned_start({'date':day,'start_time':'02:30'},SimpleNamespace(timezone='Europe/Berlin')) is None

def test_absolute_watts_validation_weighted_measurement_and_garmin():
    target=PlanStep.model_validate({'type':'interval','duration_seconds':60,'target':{'type':'power_watts','watts':250}})
    assert _target_payload(target)[1]=={'targetValueOne':237.5,'targetValueTwo':262.5}
    for watts in [-1,0,float('nan'),float('inf'),3001]:
        with pytest.raises(ValidationError):PlanStep.model_validate({'type':'work','duration_seconds':60,'target':{'type':'power_watts','watts':watts}})
    rows=[{'elapsed_s':i,'power':250} for i in range(61)]
    result=evaluate_goals(rows,{'steps':[target.model_dump()]},{})
    assert result['status']=='on_target' and result['steps'][0]['avg_value']==250
    assert result['coverage_pct']==100 and result['in_target_pct']==100
    assert evaluate_goals([rows[0],rows[-1]],{'steps':[target.model_dump()]},{})['status']=='unassessed'

def test_adaptation_preserves_preparation_recovery_and_repeat_count():
    before=session(date='2026-10-20');original=copy.deepcopy(before)
    reduced=domain.adapt_session(before,'reduce');interval=reduced['steps'][1]['steps'][0]
    assert interval['duration_seconds']==45 and interval['target']['watts']==245
    assert reduced['steps'][1]['repeat']==4 and reduced['steps'][1]['steps'][1]['duration_seconds']==60
    assert reduced['steps'][0]['duration_seconds']==600 and reduced['steps'][2]['duration_seconds']==600
    assert sum(seconds(x) for x in reduced['steps'])==1620 and reduced['duration_min']==27
    increased=domain.adapt_session(before,'increase')
    assert increased['steps'][1]['steps'][0]['target']['watts']==255 and increased['steps'][1]['steps'][0]['duration_seconds']==60
    assert before==original

@pytest.fixture
async def data(tmp_path):
    engine=create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        user=User(username='first',email='a@x',password_hash='x',timezone='UTC');other=User(username='other',email='b@x',password_hash='x',timezone='UTC')
        db.add_all([user,other]);await db.flush()
        monday=date.today()-timedelta(days=date.today().weekday()+7)
        run=AiRun(user_id=user.id,task_type='training_plan',prompt='p',content='plan',metadata_json={
            'structured_plan':{'title':'Measured plan','weeks':4,'sessions':[session(),session(id='s2',week=2),session(id='future',week=3)]}})
        db.add(run);await db.flush()
        schedule=PlanSchedule(plan_run_id=run.id,user_id=user.id,start_date=monday,revision=0,overrides={});db.add(schedule)
        acts=[]
        for index,power in enumerate((190,250)):
            stamp=datetime.combine(monday+timedelta(days=index*7),datetime.min.time(),timezone.utc)+timedelta(hours=9)
            a=Activity(user_id=user.id,garmin_activity_id=100+index,name='Ride',sport_type='cycling',started_at=stamp,duration_seconds=1680,avg_power=power)
            db.add(a);await db.flush();path=tmp_path/f'{index}.parquet'
            pd.DataFrame({'timestamp':pd.date_range(stamp,periods=1681,freq='s'),'power':[power]*1681}).to_parquet(path)
            db.add(FitFile(activity_id=a.id,user_id=user.id,status='parsed',parquet_path=str(path),original_path=str(path),file_size=10,sha256='x'))
            db.add(ActivityFeedback(activity_id=a.id,user_id=user.id,data={'feeling':'hard' if index==0 else 'easy','exertion':8 if index==0 else 3,'discomfort':''}))
            db.add(PlanActivityMatch(user_id=user.id,plan_run_id=run.id,session_id=f's{index+1}',activity_id=a.id,state='matched'));acts.append(a)
        await db.commit();yield db,user,other,run,schedule,acts
    await engine.dispose()

async def test_review_metrics_cache_ownership_and_stale_evidence(data):
    db,user,other,run,schedule,acts=data
    r=await api.get_review(run.id,'s1',None,user,db)
    assert r['review']['summary']['status']=='too_low' and r['review']['summary']['assessed_intervals']==4
    assert (await api.get_review(run.id,'s1',None,user,db))['fingerprint']==r['fingerprint']
    assert len((await domain.execution_context(db,user))['items'])==1
    assert (await domain.execution_context(db,other))['items']==[]
    with pytest.raises(HTTPException) as e:await api.get_review(run.id,'s1',None,other,db)
    assert e.value.status_code==404
    acts[0].duration_seconds=1200;await db.commit()
    assert (await domain.execution_context(db,user))['items']==[]
    assert (await api.get_review(run.id,'s1',None,user,db))['fingerprint']!=r['fingerprint']

async def test_time_revision_and_foreign_manual_assignment(data):
    db,user,other,run,schedule,acts=data
    assert (await api.save_start_time(run.id,'s1',api.StartTimeIn(start_time='09:30',revision=0),user,db))['revision']==1
    with pytest.raises(HTTPException):await api.save_start_time(run.id,'s1',api.StartTimeIn(start_time='10:00',revision=0),user,db)
    assert [r['id'] for r in (await api.candidates(run.id,'s1',user,db))['items']]==[str(acts[0].id)]
    foreign=Activity(user_id=other.id,garmin_activity_id=999,name='Private',sport_type='cycling',started_at=acts[0].started_at,duration_seconds=1680)
    db.add(foreign);await db.commit()
    assert 'Private' not in str(await api.candidates(run.id,'s1',user,db))
    with pytest.raises(HTTPException):await matches.match_activity(run.id,matches.MatchIn(session_id='s1',activity_id=foreign.id,revision=1),user,db)

async def test_adaptation_review_apply_and_repeated_source_guard(data):
    db,user,other,run,schedule,acts=data
    r=await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=0),user,db)
    assert r['direction']=='reduce' and r['items'][0]['after']['id']=='future' and schedule.overrides=={}
    with pytest.raises(HTTPException):await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=0,apply=True,review_token='forged',expected_items=r['items']),user,db)
    result=await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=0,apply=True,review_token=r['review_token'],expected_items=r['items']),user,db)
    assert result['applied'] and result['revision']==1
    assert schedule.overrides['future']['steps'][1]['steps'][0]['target']['watts']==245
    assert (await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=1),user,db))['reason']=='REVIEW_ALREADY_APPLIED'

async def test_feedback_changes_and_exports_block_stale_proposals(data):
    db,user,other,run,schedule,acts=data
    r=await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=0),user,db)
    f=await db.get(ActivityFeedback,acts[0].id);f.data={'feeling':'easy','exertion':3,'discomfort':'Knee'};await db.commit()
    with pytest.raises(HTTPException):await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=0,apply=True,review_token=r['review_token'],expected_items=r['items']),user,db)
    f.data={'feeling':'hard','exertion':8,'discomfort':''}
    db.add(GarminWorkoutExport(user_id=user.id,plan_run_id=run.id,session_id='future',scheduled_date=schedule.start_date+timedelta(days=14),status='exported',workout_id='123'));await db.commit()
    assert (await api.adaptation(run.id,'s1',api.AdaptiveIn(revision=0),user,db))['reason']=='NO_UNLOCKED_COMPARABLE_FUTURE_SESSION'

async def test_progression_needs_two_successes_and_green_recovery(data,monkeypatch):
    db,user,other,run,schedule,acts=data
    await api.get_review(run.id,'s2',None,user,db)
    assert (await api.adaptation(run.id,'s2',api.AdaptiveIn(revision=0),user,db))['items']==[]
    fit=await db.scalar(select(FitFile).where(FitFile.activity_id==acts[0].id))
    frame=pd.read_parquet(fit.parquet_path);frame['power']=250;frame.to_parquet(fit.parquet_path)
    f=await db.get(ActivityFeedback,acts[0].id);f.data={'feeling':'easy','exertion':3,'discomfort':''};await db.commit()
    await api.get_review(run.id,'s1',None,user,db)
    from pengucoach.coach import today
    monkeypatch.setattr(today,'readiness_snapshot',AsyncMock(return_value={'readiness':{'status':'green'}}))
    r=await api.adaptation(run.id,'s2',api.AdaptiveIn(revision=0),user,db)
    assert r['direction']=='increase' and r['items'][0]['after']['steps'][1]['steps'][0]['target']['watts']==255
    monkeypatch.setattr(today,'readiness_snapshot',AsyncMock(return_value={'readiness':{'status':'yellow'}}))
    assert (await api.adaptation(run.id,'s2',api.AdaptiveIn(revision=0),user,db))['reason']=='RECOVERY_NOT_READY_FOR_INCREASE'

async def test_session_ai_uses_measured_comparison_privacy_and_rejects_stale_fingerprint(data,monkeypatch):
    from worker.tasks import ai
    db,user,other,run,schedule,acts=data
    uid,rid=user.id,run.id
    reviewed=await api.get_review(rid,'s1',None,user,db)
    monkeypatch.setattr(ai,'SessionLocal',async_sessionmaker(db.bind,expire_on_commit=False))
    monkeypatch.setattr(ai,'build_activity_analysis_context',AsyncMock(return_value={'activity':{'summary':{'name':'Ride'}}}))
    calls=[]
    async def fake_chat(db,messages,context,locale,**kwargs):
        calls.append((context,kwargs))
        assert context['planned_training_review']['summary']['assessed_intervals']==4
        assert context['planned_training_review']['summary']['work_in_target_pct']==0
        assert kwargs['local_only'] is True
        return {'content':'Geplant 250 W, aufgezeichnet unter dem Ziel.','model_id':str(uuid.uuid4()),
            'provider':'Local','model':'Model','max_output_tokens':3500,'usage':{'input_tokens':20,'output_tokens':40,'total_tokens':60},'truncated':False}
    monkeypatch.setattr(ai,'chat',fake_chat)
    payload={'plan_id':str(rid),'session_id':'s1','review_fingerprint':reviewed['fingerprint']}
    result=await ai._session_analysis(str(uid),payload)
    assert not result['stale'] and result['content'].startswith('Geplant 250')
    assert len(calls)==1
    with pytest.raises(RuntimeError,match='REVIEW_CHANGED_RELOAD'):
        await ai._session_analysis(str(uid),{**payload,'review_fingerprint':'old'})
    assert len(calls)==1


def test_compaction_preserves_planned_review_and_execution_evidence():
    from pengucoach.llm.service import bounded_personal_context
    context={'lookback':{'activities':[{'name':'long'*1000}]*50,'training_execution':{'items':[{'summary':{'status':'too_low'}}]}},
        'planned_training_review':{'summary':{'status':'too_low','work_in_target_pct':25},'intervals':[{'index':n,'reason':'detail'*50} for n in range(60)]}}
    import json
    encoded,meta=bounded_personal_context(context,3500)
    result=json.loads(encoded)
    assert len(encoded)<=3500 and 'planned_training_review' in result
    assert result['planned_training_review']['summary']['work_in_target_pct']==25

def test_different_power_and_interval_workouts_are_not_adapted_as_comparable():
    original=session()
    different=copy.deepcopy(original);different['steps'][1]['steps'][0]['duration_seconds']=600
    assert not domain.comparable(original,different)
    different=copy.deepcopy(original);different['steps'][1]['steps'][0]['target']['watts']=400
    assert not domain.comparable(original,different)

async def test_plan_deletion_removes_its_derived_ai_reports_only(data):
    from apps.api.routers.coach import delete_training_plan_local
    db,user,other,run,schedule,acts=data
    planned=AiRun(user_id=user.id,task_type='activity_analysis',prompt='p',content='planned review',metadata_json={'planned_session':{'plan_id':str(run.id),'session_id':'s1'}})
    unrelated=AiRun(user_id=user.id,task_type='activity_analysis',prompt='p',content='other report',metadata_json={})
    db.add_all([planned,unrelated]);await db.commit()
    pid,other_id=planned.id,unrelated.id
    await delete_training_plan_local(run.id,user,db)
    assert await db.get(AiRun,pid) is None
    assert await db.get(AiRun,other_id) is not None
