import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from apps.api.routers import continuation as api
from apps.api.routers.coach import _run_payload
from pengucoach.db.base import Base
from pengucoach.db.models import AiRun, BackgroundJob, LlmModel, LlmProvider, Message, User, UserPreference
from pengucoach.llm import service
from pengucoach.llm.continuation import append_text
from pengucoach.security import crypto
from worker.tasks import ai, continuation as worker

@compiles(JSONB,'sqlite')
def sqlite_json(type_,compiler,**kw):return 'JSON'

@pytest.fixture
async def data(tmp_path,monkeypatch):
    monkeypatch.setattr(crypto.settings,'encryption_key',Fernet.generate_key().decode())
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/state.sqlite')
    async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(ai,'SessionLocal',factory);monkeypatch.setattr(worker,'SessionLocal',factory)
    monkeypatch.setattr(ai,'build_coach_weather_context',AsyncMock(return_value=None))
    monkeypatch.setattr(api,'AsyncResult',lambda *a,**kw:SimpleNamespace(ready=lambda:False,state='PENDING'))
    monkeypatch.setattr(worker.continue_ai,'apply_async',lambda *a,**kw:None)
    async with factory() as db:
        u=User(username='test',email='a@x',password_hash='x',timezone='UTC',locale='de')
        other=User(username='other',email='b@x',password_hash='x',timezone='UTC')
        db.add_all([u,other]);await db.flush()
        db.add(UserPreference(user_id=u.id,local_ai_only=False,cloud_health_ai_allowed=True))
        p=LlmProvider(name='OpenRouter',provider_type='openrouter',enabled=True,is_local=False,secret_ciphertext=crypto.SecretBox().encrypt('test-key'))
        db.add(p);await db.flush()
        m=LlmModel(provider_id=p.id,model_identifier='vendor/model',display_name='Model',context_window=32768,metadata_json={'provider_max_output_tokens':16384},enabled=True,temperature=.2)
        db.add(m);await db.commit();yield factory,u.id,other.id,m.id
    await engine.dispose()


def transport(monkeypatch,replies):
    requests=[];client_class=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        content,reason,tokens=replies.pop(0)
        return httpx.Response(200,json={'choices':[{'message':{'content':content},'finish_reason':reason}],
            'usage':{'prompt_tokens':10,'completion_tokens':tokens,'total_tokens':10+tokens}})
    monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kw:client_class(**kw,transport=httpx.MockTransport(handler)))
    return requests

async def initial(data,monkeypatch,replies):
    factory,uid,other,mid=data;requests=transport(monkeypatch,replies)
    result=await ai._coach_chat(str(uid),{'message':'Wie läuft es?','model_id':str(mid),'max_tokens':128,
        'context_window_tokens':16384,'context_mode':'none','use_personal_context':False})
    return result,requests

async def extend(data,run_id,revision=0):
    factory,uid,_,_=data
    async with factory() as db:
        user=await db.get(User,uid)
        queued=await api.continue_run(uuid.UUID(run_id),api.ContinueIn(revision=revision),user,db)
    result=await worker._continue(str(uid),{'run_id':run_id,'revision':revision+1},task_id=queued['task_id'])
    return result

async def test_partial_output_is_preserved_continued_and_accounted(data,monkeypatch):
    result,requests=await initial(data,monkeypatch,[('Erster Teil.','length',128),('Zweiter Teil.','stop',50)])
    assert result['continuation']['available'] and '_resume' not in result
    continued=await extend(data,result['run_id'])
    assert continued['content']=='Erster Teil.\n\nZweiter Teil.'
    assert continued['usage']=={'input_tokens':20,'output_tokens':178,'total_tokens':198}
    assert not continued['continuation']['available']
    assert requests[1]['max_tokens']==8000
    assert any(m['role']=='assistant' and m['content']=='Erster Teil.' for m in requests[1]['messages'])
    factory,uid,_,_=data
    async with factory() as db:
        run=await db.get(AiRun,uuid.UUID(result['run_id']))
        assert '_resume' not in run.metadata_json and '_continuation_job' not in run.metadata_json
        message=await db.get(Message,uuid.UUID(run.metadata_json['assistant_message_id']))
        assert message.content==continued['content'] and message.metadata_json['run_id']==str(run.id)
        assert '_resume' not in _run_payload(run)['metadata']
        assert len((await db.scalars(select(AiRun))).all())==1

async def test_empty_reasoning_limit_can_retry_with_larger_budget(data,monkeypatch):
    result,requests=await initial(data,monkeypatch,[('','length',128),('Endlich sichtbar.','stop',50)])
    assert result['content']=='' and result['empty_due_to_limit']
    r=await extend(data,result['run_id'])
    assert r['content']=='Endlich sichtbar.' and requests[1]['max_tokens']==8128

async def test_repeat_continuation_does_not_duplicate_old_assistant_prefix(data,monkeypatch):
    result,requests=await initial(data,monkeypatch,[('Teil 1.','length',128),('Teil 2.','length',8000),('Teil 3.','stop',50)])
    second=await extend(data,result['run_id'])
    assert second['continuation']['available']
    third=await extend(data,result['run_id'],1)
    assert third['content']=='Teil 1.\n\nTeil 2.\n\nTeil 3.'
    assert [m['content'] for m in requests[2]['messages'] if m['role']=='assistant']==['Teil 1.\n\nTeil 2.']

async def test_owned_revision_duplicate_queue_and_cloud_policy(data,monkeypatch):
    result,requests=await initial(data,monkeypatch,[('Part','length',128)])
    factory,uid,other,_=data;rid=uuid.UUID(result['run_id'])
    async with factory() as db:
        user=await db.get(User,uid);foreign=await db.get(User,other)
        with pytest.raises(HTTPException) as error:await api.continue_run(rid,api.ContinueIn(revision=0),foreign,db)
        assert error.value.status_code==404
        with pytest.raises(HTTPException):await api.continue_run(rid,api.ContinueIn(revision=5),user,db)
        pref=await db.get(UserPreference,uid);pref.local_ai_only=True;await db.commit()
        with pytest.raises(HTTPException) as error:await api.continue_run(rid,api.ContinueIn(revision=0),user,db)
        assert error.value.detail=='NO_ELIGIBLE_LLM_MODEL_CONFIGURED'
        pref.local_ai_only=False;await db.commit()
        one=await api.continue_run(rid,api.ContinueIn(revision=0),user,db)
        two=await api.continue_run(rid,api.ContinueIn(revision=0),user,db)
        assert one['task_id']==two['task_id'] and two['already_running']
        assert len((await db.scalars(select(BackgroundJob))).all())==1
    assert len(requests)==1

async def test_changed_conversation_cannot_append_to_old_message(data,monkeypatch):
    result,_=await initial(data,monkeypatch,[('Part','length',128)])
    factory,uid,_,_=data
    async with factory() as db:
        user=await db.get(User,uid)
        db.add(Message(conversation_id=uuid.UUID(result['conversation_id']),role='user',content='New question',created_at=datetime.now(timezone.utc)))
        await db.commit()
        with pytest.raises(HTTPException) as e:await api.continue_run(uuid.UUID(result['run_id']),api.ContinueIn(revision=0),user,db)
        assert e.value.detail=='CONVERSATION_CHANGED_RELOAD'

async def test_cancelled_continuation_keeps_text_and_unlocks_claim(data,monkeypatch):
    result,requests=await initial(data,monkeypatch,[('Original','length',128)])
    factory,uid,_,_=data
    async with factory() as db:
        q=await api.continue_run(uuid.UUID(result['run_id']),api.ContinueIn(revision=0),await db.get(User,uid),db)
    with pytest.raises(service.AiGenerationCancelled):
        await worker._continue(str(uid),{'run_id':result['run_id'],'revision':1},cancel_check=lambda:True,task_id=q['task_id'])
    async with factory() as db:
        r=await db.get(AiRun,uuid.UUID(result['run_id']))
        assert r.content=='Original' and '_continuation_job' not in r.metadata_json
        assert (await db.get(BackgroundJob,uuid.UUID(q['task_id']))).status=='cancelled'
    assert len(requests)==1

def test_only_exact_overlap_is_removed():
    prefix='Ein Satz mit ausreichend langem Abschluss.'
    assert append_text(prefix,'mit ausreichend langem Abschluss. Weiter')==prefix+' Weiter'
    assert append_text('Old','New')=='Old\n\nNew'

async def test_segmented_plan_draft_resumes_checkpoint_and_same_run(data,monkeypatch):
    factory,uid,_,mid=data
    calls=[]
    monkeypatch.setattr(ai,'build_training_plan_context',AsyncMock(return_value={'lookback':{'days':7}}))
    monkeypatch.setattr(ai,'add_personal_context',AsyncMock(return_value={}))
    monkeypatch.setattr(ai,'build_training_weather_context',AsyncMock(return_value=None))
    def document():
        return json.dumps({'title':'Plan','weeks':2,'sessions':[{'id':f's{w}-{d}','week':w,'day':d,'name':'Ride','sport':'cycling','duration_min':30,'steps':[{'type':'work','duration_seconds':1800}]} for w in [1,2] for d in [1,2,3,4]]})
    async def fake_chat(db,messages,context,locale,**kwargs):
        calls.append((context['goal']['plan_week_start'],kwargs['requested_max_tokens']))
        valid=len(calls)==1 or len(calls)>3
        return {'content':document() if valid else '{"title":"partial', 'truncated':not valid,
            'model_id':str(mid),'provider':'OpenRouter','model':'Model','max_output_tokens':kwargs['requested_max_tokens'],
            'usage':{'input_tokens':10,'output_tokens':20,'total_tokens':30},'cost_eur':None,
            'continuation':{'available':not valid,'revision':0},'stop_reason':'stop' if valid else 'length'}
    monkeypatch.setattr(ai,'chat',fake_chat)
    r=await ai._training_plan(str(uid),{'weeks':4,'days_per_week':4,'session_minutes':30,'max_tokens':5000,'model_id':str(mid),'use_personal_context':False})
    assert r['metadata']['draft'] and not r['metadata']['structured_plan_valid']
    assert len(calls)==3 and calls[0][0]==1 and calls[1][0]==3
    done=await extend(data,r['run_id'])
    assert done['run_id']==r['run_id'] and len(calls)==4 and calls[-1][0]==3
    assert done['metadata']['structured_plan_valid'] and len(done['metadata']['structured_plan']['sessions'])==16
    assert {s['week'] for s in done['metadata']['structured_plan']['sessions']}=={1,2,3,4}
    assert not done['metadata']['continuation']['available']
