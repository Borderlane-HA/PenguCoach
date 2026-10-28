import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.routers import companion as api
from pengucoach.coach.companion import add_personal_context, briefing, compare_sessions, conversation_excerpt
from pengucoach.common.dates import user_today
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachCheckin, Conversation, GarminWorkoutExport, LlmModel, LlmProvider, Message, User
from pengucoach.llm import service


@compiles(JSONB, "sqlite")
def jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
async def data():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(username="a", email="a@x", password_hash="x", timezone="Europe/Berlin")
        other = User(username="b", email="b@x", password_hash="x")
        db.add_all([user, other])
        await db.flush()
        yield db, user, other
    await engine.dispose()


async def test_personal_memory_edit_delete_isolation_and_context_selection(data):
    db, user, other = data
    await api.save_profile(api.ProfileIn(goal="100 km", training_days=[1,4]), user, db)
    memory = await api.save_memory(api.MemoryIn(content="Mittwochs keine Zeit"), user, db)
    with pytest.raises(HTTPException) as error:
        await api.edit_memory(uuid.UUID(memory["id"]), api.MemoryIn(content="SECRET"), other, db)
    assert error.value.status_code == 404
    await api.save_checkin(api.CheckinIn(energy=1, soreness=4), user, db)
    ctx = await add_personal_context(db, user, {}, {})
    assert ctx["personal_coaching"]["profile"]["goal"] == "100 km"
    assert ctx["personal_coaching"]["today_checkin"]["energy"] == 1
    off = await add_personal_context(db, user, {}, {"use_personal_context": False})
    assert "personal_coaching" not in off
    no_recovery = await add_personal_context(db,user,{}, {"context_data":{"recovery":False,"training":False}})
    assert "today_checkin" not in no_recovery["personal_coaching"]
    await api.delete_memory(uuid.UUID(memory["id"]),user,db)
    assert not (await add_personal_context(db,user,{},{}))["personal_coaching"]["memories"]
    assert not (await api.memories(other,db))


async def test_conversation_history_order_summary_and_delete(data):
    db,user,other=data
    conv=Conversation(user_id=user.id,title="My chat")
    db.add(conv)
    await db.flush()
    now=datetime.now(timezone.utc)
    for i in range(20):
        db.add(Message(conversation_id=conv.id,role="user" if i%2==0 else "assistant",content=f"message {i}",created_at=now+timedelta(seconds=i)))
    await db.flush()
    rows=await conversation_excerpt(db,conv)
    assert len(rows)==20 and "message 0" in conv.summary
    result=await api.get_conversation(conv.id,None,None,user,db)
    assert result["messages"][-1]["content"]=="message 19"
    with pytest.raises(HTTPException):
        await api.get_conversation(conv.id,None,None,other,db)
    run=AiRun(user_id=user.id,task_type="coach_chat",prompt="q",content="a",metadata_json={"conversation_id":str(conv.id)})
    db.add(run)
    await db.flush()
    await api.delete_conversation(conv.id,user,db)
    assert not (await db.scalars(select(Message))).all()
    assert not (await db.scalars(select(AiRun))).all()


def test_response_limit_and_blank_thinking():
    assert not service.response_truncated("stop",2500,2500)
    assert service.response_truncated("length",2499,2500)
    assert service.response_truncated(None,2500,2500)
    assert service.visible_answer("<think>hidden</think>answer")=="answer"
    assert service.visible_answer("<think>unfinished")==""


async def test_briefing_never_uses_stale_checkin_or_fabricates_training(data):
    db,user,_=data
    day=user_today(user)
    db.add(CoachCheckin(user_id=user.id,date=day-timedelta(days=1),data={"energy":1}))
    await db.flush()
    b=await briefing(db,user)
    assert b["current_week"]["sessions"]==0 and b["reasons"]==[]
    await api.save_checkin(api.CheckinIn(energy=1,minutes=0),user,db)
    b=await briefing(db,user)
    assert b["mode"]=="easy" and "no_time" in b["reasons"]


async def make_plan(db,user):
    run=AiRun(user_id=user.id,task_type="training_plan",prompt="q",content="plan",metadata_json={"structured_plan":{"title":"Plan","weeks":4,"sessions":[{"id":"s1","week":1,"day":1,"name":"Bike","sport":"cycling","duration_min":40},{"id":"s2","week":1,"day":2,"name":"Run","sport":"running","duration_min":30}]}})
    db.add(run)
    await db.flush()
    day=user_today(user)
    monday=day-timedelta(days=day.weekday())
    return run,monday


async def test_schedule_preview_apply_revision_and_export_guards(data):
    db,user,other=data
    run,monday=await make_plan(db,user)
    stored=await api.save_schedule(run.id,api.ScheduleIn(start_date=monday),user,db)
    assert stored["revision"]==1
    with pytest.raises(HTTPException):
        await api.get_schedule(run.id,other,db)
    with pytest.raises(HTTPException) as err:
        await api.save_schedule(run.id,api.ScheduleIn(start_date=monday,revision=0),user,db)
    assert err.value.detail=="SCHEDULE_CHANGED_RELOAD"
    preview=await api.adapt(run.id,api.AdaptIn(session_id="s1",action="easy",revision=1),user,db)
    assert preview["after"]["sport"]=="walking"
    assert (await api.get_schedule(run.id,user,db))["revision"]==1
    with pytest.raises(HTTPException):
        await api.adapt(run.id,api.AdaptIn(session_id="s1",action="easy",revision=1,apply=True),user,db)
    await api.adapt(run.id,api.AdaptIn(session_id="s1",action="easy",revision=1,apply=True,expected_after=preview["after"]),user,db)
    assert (await api.get_schedule(run.id,user,db))["revision"]==2
    db.add(GarminWorkoutExport(user_id=user.id,plan_run_id=run.id,session_id="s2",scheduled_date=monday+timedelta(days=1),status="exported",workout_id="123"))
    await db.flush()
    with pytest.raises(HTTPException) as err:
        await api.adapt(run.id,api.AdaptIn(session_id="s2",action="easy",revision=2),user,db)
    assert err.value.detail=="EXPORTED_SESSION_LOCKED"


def test_activity_matching_is_one_to_one_and_local_date():
    u=SimpleNamespace(timezone="Europe/Berlin")
    a=Activity(id=uuid.uuid4(),started_at=datetime(2026,9,26,22,30,tzinfo=timezone.utc),sport_type="road_biking",duration_seconds=2700)
    s={"id":"s1","date":"2026-09-27","sport":"cycling","duration_min":40}
    r=compare_sessions([s],[a],u)
    assert r[0]["status"]=="matched" and r[0]["difference_minutes"]==5
    assert all(x["status"]=="ambiguous" for x in compare_sessions([s,{**s,"id":"s2"}],[a],u))
    assert compare_sessions([s],[a,Activity(id=uuid.uuid4(),started_at=a.started_at,sport_type=a.sport_type)],u)[0]["status"]=="ambiguous"


async def test_feedback_is_private_and_changes_briefing(data):
    db,user,other=data
    a=Activity(user_id=user.id,garmin_activity_id=-9,started_at=datetime.now(timezone.utc),name="Ride",sport_type="cycling",duration_seconds=1800)
    db.add(a)
    await db.flush()
    with pytest.raises(HTTPException):
        await api.save_feedback(a.id,api.FeedbackIn(),other,db)
    await api.save_feedback(a.id,api.FeedbackIn(feeling="hard"),user,db)
    assert "hard_feedback" in (await briefing(db,user))["reasons"]
    await api.delete_feedback(a.id,user,db)
    assert await db.get(ActivityFeedback,a.id) is None


def test_context_compaction_is_bounded_valid_json_and_keeps_profile():
    c={"period_days":7,"data_inventory":{"activity_count":30},"recent_activities":[{"summary":{"name":"ride"*100,"duration_s":4000}}]*30,"personal_coaching":{"profile":{"goal":"100 km"},"memories":[{"text":"Mittwochs keine Zeit"}]},"conversation_summary":"I like bikes"}
    payload,meta=service.bounded_personal_context(c,3000)
    assert len(payload)<=3000 and meta["context_truncated"]
    result=json.loads(payload)
    assert result["personal_coaching"]["profile"]["goal"]=="100 km"
    assert result["data_inventory"]["activity_count"]==30


async def test_ollama_disables_thinking_and_rejects_empty_answers(monkeypatch):
    provider=SimpleNamespace(provider_type="ollama",base_url="http://test",name="Ollama",is_local=True)
    model=SimpleNamespace(id=uuid.uuid4(),model_identifier="custom-gemma",display_name="Gemma",temperature=.2,context_window=8192,metadata_json={})
    monkeypatch.setattr(service,"resolve_model",AsyncMock(return_value=(provider,model)))
    monkeypatch.setattr(service,"task_settings",AsyncMock(return_value={"max_output_tokens":2500,"context_window_tokens":8192,"max_context_chars":24000,"default_prompt":"Be concise."}))
    captured={}
    chunks=[{"message":{"content":"Hello"},"done":False},{"done":True,"done_reason":"stop","prompt_eval_count":100,"eval_count":2500}]
    class Stream:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def raise_for_status(self):pass
        async def aiter_lines(self):
            for c in chunks:yield json.dumps(c)
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def stream(self,*args,**kwargs):captured.update(kwargs["json"]);return Stream()
    monkeypatch.setattr(service.httpx,"AsyncClient",Client)
    answer=await service.chat(None,[{"role":"user","content":"Hello"}],{},"de")
    assert captured["think"] is False
    assert answer["content"]=="Hello" and not answer["truncated"]
    chunks[:]=[{"message":{"thinking":"hidden"},"done":False},{"done":True,"done_reason":"length","eval_count":2500}]
    with pytest.raises(RuntimeError,match="AI_EMPTY_RESPONSE_THINKING_LIMIT"):
        await service.chat(None,[{"role":"user","content":"Hello"}],{},"de")
    chunks[:]=[{"message":{"content":"partial"},"done":False}]
    with pytest.raises(RuntimeError,match="OLLAMA_STREAM_INCOMPLETE"):
        await service.chat(None,[{"role":"user","content":"Hello"}],{},"de")


async def test_worker_chat_reuses_history_and_personal_context(data, monkeypatch):
    from worker.tasks import ai
    db,user,_=data
    await api.save_profile(api.ProfileIn(goal="100 km cycling"),user,db)
    await api.save_memory(api.MemoryIn(content="No Wednesdays"),user,db)
    provider=LlmProvider(name="test",provider_type="ollama",base_url="http://test",is_local=True)
    db.add(provider)
    await db.flush()
    model=LlmModel(provider_id=provider.id,model_identifier="test",display_name="Test")
    db.add(model)
    await db.flush()
    captures=[]
    async def fake_chat(db,messages,context,locale,**kwargs):
        captures.append((messages,context))
        return {"content":"A short answer","model_id":str(model.id),"provider":"test","model":"Test","max_output_tokens":100,"usage":{},"evidence":{}}
    class Session:
        async def __aenter__(self):return db
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(ai,"SessionLocal",Session)
    monkeypatch.setattr(ai,"chat",fake_chat)
    one=await ai._coach_chat(str(user.id),{"message":"What should I do?","context_mode":"none"})
    two=await ai._coach_chat(str(user.id),{"message":"Only 30 minutes","conversation_id":one["conversation_id"],"context_mode":"none"})
    assert one["conversation_id"]==two["conversation_id"]
    assert [m["role"] for m in captures[-1][0]]==["user","assistant","user"]
    assert captures[-1][1]["personal_coaching"]["profile"]["goal"]=="100 km cycling"
    messages=(await api.get_conversation(uuid.UUID(one["conversation_id"]),None,None,user,db))["messages"]
    assert len(messages)==4 and messages[-1]["metadata"]["model"]=="Test"


async def test_quick_session_creates_reviewed_local_calendar_only(data):
    db,user,_=data
    result=await api.quick_session(api.QuickSessionIn(date=user_today(user),name="Easy ride",sport="cycling",duration_min=30),user,db)
    schedule=await api.get_schedule(uuid.UUID(result["run_id"]),user,db)
    assert schedule["revision"]==1
    assert schedule["start_date"].weekday()==0
    assert not (await db.scalars(select(GarminWorkoutExport))).all()
    with pytest.raises(HTTPException):
        await api.quick_session(api.QuickSessionIn(date=user_today(user)-timedelta(days=1),name="Past",sport="walking",duration_min=30),user,db)


async def test_chat_job_ownership_protects_progress_and_cancellation(data):
    from apps.api.routers.jobs import _check_owner
    from pengucoach.db.models import BackgroundJob
    db,user,other=data
    row=BackgroundJob(user_id=user.id,job_type="coach_chat")
    db.add(row)
    await db.flush()
    await _check_owner(str(row.id),user,db)
    with pytest.raises(HTTPException):
        await _check_owner(str(row.id),other,db)
