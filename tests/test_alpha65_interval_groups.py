import copy
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from test_alpha61_continuation import data  # noqa: F401 real SQLite/worker fixture
from apps.api.routers import continuation as continuation_api
from pengucoach.coach.plan_evolution import seconds
from pengucoach.coach.workout_review import flatten_steps
from pengucoach.garmin.gateway.workouts import build_typed_workout
from pengucoach.training_plan.structured import PlanStep, TrainingSession, extract_structured_plan, render_plan_markdown
from worker.tasks import ai, continuation as worker
from pengucoach.db.models import User
import uuid


def block(kind='interval', **extra):
    return {'type':kind,'repeat':4,'description':'Four controlled intervals','steps':[
        {'type':'interval','duration_seconds':180,'target':{'type':'heart_rate_zone','zone':4}},
        {'type':'recovery','duration_seconds':120,'target':{'type':'heart_rate_zone','zone':2}}],**extra}


@pytest.mark.parametrize('kind',['interval','work'])
def test_explicit_interval_groups_preserve_count_children_and_targets(kind):
    original=block(kind);snapshot=copy.deepcopy(original)
    step=PlanStep.model_validate(original)
    assert original==snapshot
    assert step.type=='repeat' and step.repeat==4 and step.description==original['description']
    assert [s.duration_seconds for s in step.steps]==[180,120]
    assert [s.target.zone for s in step.steps]==[4,2]
    assert seconds(step.model_dump())==1200
    assert len(flatten_steps([step.model_dump()]))==8
    assert PlanStep.model_validate(step.model_dump())==step


@pytest.mark.parametrize('changes',[
    {'repeat':None},{'repeat':1},{'repeat':0},{'repeat':-4},{'repeat':101},
    {'steps':[]},{'steps':[{'type':'interval'}]},
    {'target':{'type':'heart_rate_zone','zone':4}},
    {'type':'warmup'},
])
def test_incomplete_or_ambiguous_groups_still_require_repair(changes):
    with pytest.raises(ValidationError):PlanStep.model_validate(block(**changes))


def test_normal_executable_interval_and_canonical_repeat_remain_unchanged():
    step=PlanStep.model_validate({'type':'interval','duration_seconds':180,'repeat':None,'steps':[]})
    assert step.type=='interval' and step.repeat is None and step.duration_seconds==180
    assert PlanStep.model_validate(block('repeat')).model_dump()==PlanStep.model_validate(block()).model_dump()


def test_nested_alias_groups_are_normalized_recursively():
    step=PlanStep.model_validate(block(steps=[block(),{'type':'recovery','duration_seconds':300}]))
    assert step.type=='repeat' and step.steps[0].type=='repeat'
    assert step.repeat==4 and step.steps[0].repeat==4
    assert seconds(step.model_dump())==6000


def document():
    sessions=[]
    for week in (1,2):
        for day in (1,2,3,4):
            sessions.append({'id':f'w{week}-d{day}','week':week,'day':day,'name':'Controlled intervals','sport':'running',
                'duration_min':40,'steps':[{'type':'warmup','duration_seconds':600},block(),{'type':'cooldown','duration_seconds':600}]})
    return {'title':'Two-week segment','weeks':2,'sessions':sessions}


def test_reported_validation_paths_render_and_export_as_repeat_groups():
    raw=document();raw['sessions'][0]['steps'].insert(1,{'type':'work','duration_seconds':60})
    plan,error=extract_structured_plan(json.dumps(raw))
    assert error is None and plan is not None
    assert plan.sessions[0].steps[2].type=='repeat' and plan.sessions[3].steps[1].type=='repeat'
    assert '4× (Intervall · 3 min · HF Z4; Erholung · 2 min · HF Z2)' in render_plan_markdown(plan)
    payload=build_typed_workout(plan.sessions[3]).to_dict()
    repeat=payload['workoutSegments'][0]['workoutSteps'][1]
    assert repeat['type']=='RepeatGroupDTO' and repeat['numberOfIterations']==4
    assert [s['endConditionValue'] for s in repeat['workoutSteps']]==[180,120]
    assert [s['zoneNumber'] for s in repeat['workoutSteps']]==[4,2]


async def test_eight_week_generation_accepts_reported_ollama_shape_without_retries(data,monkeypatch):
    factory,uid,_,mid=data;calls=[]
    monkeypatch.setattr(ai,'build_training_plan_context',AsyncMock(return_value={'lookback':{'days':7}}))
    monkeypatch.setattr(ai,'add_personal_context',AsyncMock(return_value={}))
    monkeypatch.setattr(ai,'build_training_weather_context',AsyncMock(return_value=None))
    async def chat(db,messages,context,locale,**kw):
        calls.append(context['goal']['plan_week_start'])
        assert 'Child steps belong only to type=repeat' in json.dumps(kw['response_format_schema'])
        return {'content':json.dumps(document()),'model_id':str(mid),'provider':'Ollama','model':'Local',
            'max_output_tokens':kw['requested_max_tokens'],'usage':{'input_tokens':10,'output_tokens':100,'total_tokens':110},
            'truncated':False,'stop_reason':'stop','cost_eur':None}
    monkeypatch.setattr(ai,'chat',chat)
    result=await ai._training_plan(str(uid),{'weeks':8,'days_per_week':4,'session_minutes':40,'max_tokens':8000,'model_id':str(mid),'use_personal_context':False})
    assert calls==[1,3,5,7]
    plan=result['metadata']['structured_plan']
    assert result['metadata']['structured_plan_valid'] and len(plan['sessions'])==32
    assert all(s['steps'][1]['type']=='repeat' and s['steps'][1]['repeat']==4 for s in plan['sessions'])
    assert result['usage']['total_tokens']==440 and not result['continuation']['available']


async def test_saved_alpha64_draft_can_resume_after_fix(data,monkeypatch):
    factory,uid,_,mid=data
    monkeypatch.setattr(ai,'build_training_plan_context',AsyncMock(return_value={'lookback':{'days':7}}))
    monkeypatch.setattr(ai,'add_personal_context',AsyncMock(return_value={}))
    monkeypatch.setattr(ai,'build_training_weather_context',AsyncMock(return_value=None))
    async def chat(db,messages,context,locale,**kw):
        return {'content':json.dumps(document()),'model_id':str(mid),'provider':'Ollama','model':'Local','max_output_tokens':8000,
            'usage':{'input_tokens':10,'output_tokens':100,'total_tokens':110},'truncated':False,'stop_reason':'stop'}
    # Save the same recoverable checkpoint structure as alpha.64 produced.
    async with factory() as db:
        user=await db.get(User,uid)
        goal={'goal_type':'running_10k','goal_text':'','equipment':'','constraints':'','experience':'intermediate',
            'weeks':8,'days_per_week':4,'session_minutes':40,'start_date':'2026-10-19'}
        draft=await ai._save_plan_draft(db,user,{'weeks':8,'days_per_week':4,'session_minutes':40,'model_id':str(mid),'use_personal_context':False},
            {'goal':goal},await chat(None,None,None,None),[],'de',validation_error='TRAINING_PLAN_SEGMENT_INVALID:1-2:only repeat steps may contain nested steps')
        queued=await continuation_api.continue_run(uuid.UUID(draft['run_id']),continuation_api.ContinueIn(revision=0,additional_tokens=0),user,db)
    monkeypatch.setattr(ai,'chat',chat)
    result=await worker._continue(str(uid),{'run_id':draft['run_id'],'revision':1},task_id=queued['task_id'])
    assert result['run_id']==draft['run_id'] and result['metadata']['structured_plan_valid']
    assert len(result['metadata']['structured_plan']['sessions'])==32
