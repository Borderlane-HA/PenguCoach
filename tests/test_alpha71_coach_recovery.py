import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from apps.api.routers import jobs
from pengucoach.db.models import BackgroundJob, User
from pengucoach.llm import service
from test_alpha61_continuation import data  # noqa: F401


class Lines:
    def __init__(self, values, delay=0):
        self.values, self.delay = values, delay
        self.closed = False

    async def aiter_lines(self):
        for value in self.values:
            await asyncio.sleep(self.delay)
            yield value if isinstance(value, str) else json.dumps(value)

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize('task', ['coach_chat', 'activity_analysis', 'training_plan'])
@pytest.mark.parametrize('reason', ['stop', 'length'])
async def test_ollama_done_finishes_without_waiting_for_connection_close(monkeypatch, task, reason):
    provider = SimpleNamespace(provider_type='ollama', base_url='http://test', name='Ollama', is_local=True)
    model = SimpleNamespace(id=uuid.uuid4(), model_identifier='gemma', display_name='Gemma',
                            temperature=.2, context_window=8192, metadata_json={})
    monkeypatch.setattr(service, 'resolve_model', AsyncMock(return_value=(provider, model)))
    monkeypatch.setattr(service, 'task_settings', AsyncMock(return_value={
        'max_output_tokens':2500, 'context_window_tokens':8192,
        'max_context_chars':24000, 'default_prompt':'Be concise.'}))
    monkeypatch.setattr(service, 'ollama_think', AsyncMock(return_value=False))
    class Stream(Lines):
        async def __aenter__(self):return self
        async def __aexit__(self, *args):await self.aclose()
        def raise_for_status(self):pass
        async def aiter_lines(self):
            yield json.dumps({'message':{'content':'Antwort '}})
            yield json.dumps({'done':True, 'message':{'content':'fertig.'}, 'done_reason':reason,
                              'prompt_eval_count':3929, 'eval_count':311})
            raise AssertionError('A completed model response must not await more HTTP data')
    stream = Stream([])
    class Client:
        def __init__(self, **kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self, *args):pass
        def stream(self, *args, **kwargs):return stream
    monkeypatch.setattr(service.httpx, 'AsyncClient', Client)
    progress = []
    result = await asyncio.wait_for(service.chat(None, [{'role':'user','content':'Frage'}], {}, 'de',
        task=task, recover_limit=True, progress_callback=progress.append), timeout=1)
    assert result['content'] == 'Antwort fertig.'
    assert result['usage']['input_tokens'] == 3929
    assert result['usage']['output_tokens'] == 311
    assert result['continuation']['available'] is (reason == 'length')
    assert progress[-1]['stage'] == 'finalizing'
    assert progress[-1]['content_preview'] == result['content']
    assert stream.closed


@pytest.mark.parametrize('heartbeat', ['', '  ', {}, {'message':{'content':''}}])
async def test_blank_heartbeats_do_not_keep_ollama_alive(heartbeat):
    response = Lines([heartbeat]*100, delay=.01)
    with pytest.raises(httpx.ReadTimeout, match='OLLAMA_STREAM_STALLED'):
        async for _ in service._ollama_chunks(response, idle_seconds=.04):
            pass


async def test_meaningful_generation_can_exceed_total_idle_budget():
    chunks = [{'message':{'thinking':'reasoning'}}]*4 + [{'message':{'content':'answer'}}]*4 + [{'done':True}]
    result = [chunk async for chunk in service._ollama_chunks(Lines(chunks, delay=.015), idle_seconds=.06)]
    assert len(result) == 9  # ~135 ms total, with an idle allowance of 60 ms.
    assert result[-1]['done']


async def test_no_first_chunk_times_out():
    with pytest.raises(httpx.ReadTimeout):
        async for _ in service._ollama_chunks(Lines([{'done':True}], delay=1), idle_seconds=.02):
            pass


async def test_empty_eof_does_not_fabricate_completion():
    assert [x async for x in service._ollama_chunks(Lines([]), idle_seconds=.05)] == []


@pytest.mark.parametrize('invalid', ['not-json', [], {'message':['invalid']}])
async def test_invalid_ollama_chunks_have_fixed_error(invalid):
    with pytest.raises(service.AiProviderResponseError, match='OLLAMA_STREAM_INVALID_RESPONSE'):
        async for _ in service._ollama_chunks(Lines([invalid]), idle_seconds=.05):
            pass


async def test_job_age_is_available_only_after_owner_check(data, monkeypatch):
    factory, uid, other, _ = data
    created = datetime.now(timezone.utc) - timedelta(hours=1)
    async with factory() as db:
        user = await db.get(User, uid)
        stranger = await db.get(User, other)
        row = BackgroundJob(user_id=uid, job_type='coach_chat', created_at=created)
        db.add(row)
        await db.flush()
        monkeypatch.setattr(jobs, 'AsyncResult', lambda *a, **kw:SimpleNamespace(
            state='PENDING', ready=lambda:False, successful=lambda:False, failed=lambda:False))
        status = await jobs.job_status(str(row.id), user, db)
        assert status['created_at'] == created and not status['ready']
        with pytest.raises(HTTPException) as exc:
            await jobs.job_status(str(row.id), stranger, db)
        assert exc.value.status_code == 404
