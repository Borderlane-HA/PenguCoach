import copy
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator, ValidationError
from test_alpha61_continuation import data  # noqa: F401
from test_alpha65_interval_groups import document

from pengucoach.db.models import AiRun, LlmModel, LlmProvider
from pengucoach.llm import service
from pengucoach.training_plan.generation import training_plan_instruction
from pengucoach.training_plan.schema import generation_schema
from pengucoach.training_plan.structured import STRUCTURED_PLAN_INSTRUCTION, TrainingPlanDocument
from worker.tasks import ai


def valid_document():
    raw = document()
    for session in raw['sessions']:
        session['steps'][1]['type'] = 'repeat'
    return raw


def test_generation_schema_is_valid_reusable_and_has_request_specific_completeness():
    base = TrainingPlanDocument.model_json_schema()
    snapshot = copy.deepcopy(base)
    schema = generation_schema(2, 4, base)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(valid_document())
    assert base == snapshot
    assert generation_schema(3, 3)['properties']['sessions']['minItems'] == 9
    assert schema['properties']['sessions']['minItems'] == 8
    for changes in ({'weeks': 8}, {'sessions': valid_document()['sessions'][:4]}):
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate({**valid_document(), **changes})


@pytest.mark.parametrize('step', [
    {'type': 'interval', 'repeat': 4, 'steps': [{'type': 'work', 'duration_seconds': 30}]},
    {'type': 'work', 'duration_seconds': 30, 'repeat': 4},
    {'type': 'recovery', 'duration_seconds': 30, 'steps': [{'type': 'work', 'duration_seconds': 30}]},
    {'type': 'work'},
    {'type': 'repeat', 'repeat': 4, 'steps': []},
    {'type': 'repeat', 'steps': [{'type': 'work', 'duration_seconds': 30}]},
    {'type': 'repeat', 'repeat': 4, 'steps': [{'type': 'work'}]},
    {'type': 'repeat', 'repeat': 4, 'target': {'type': 'power_watts', 'watts': 250}, 'steps': [{'type': 'work', 'duration_seconds': 30}]},
    {'type': 'work', 'duration_seconds': 30, 'target': {'type': 'heart_rate_zone'}},
])
def test_generation_schema_prevents_step_shapes_that_previously_reached_after_validation(step):
    raw = valid_document()
    raw['sessions'][0]['steps'] = [step]
    with pytest.raises(ValidationError):
        Draft202012Validator(generation_schema(2, 4)).validate(raw)


@pytest.mark.parametrize('step', [
    {'type': 'work', 'duration_seconds': 60},
    {'type': 'interval', 'duration_seconds': 60, 'target': {'type': 'heart_rate_zone', 'zone': 4}},
    {'type': 'interval', 'distance_meters': 400, 'target': {'type': 'power_watts', 'watts': 250}},
    {'type': 'recovery', 'duration_seconds': 60, 'repeat': None, 'steps': []},
    {'type': 'repeat', 'repeat': 4, 'steps': [{'type': 'work', 'duration_seconds': 60}]},
])
def test_executable_and_repeat_variants_still_validate_as_exportable_plan_steps(step):
    raw = valid_document()
    raw['sessions'][0]['steps'] = [step]
    Draft202012Validator(generation_schema(2, 4)).validate(raw)
    TrainingPlanDocument.model_validate(raw)


@pytest.mark.parametrize('prescription', [
    {'reps': 8}, {'reps': 8, 'reps_max': 10},
    {'duration_seconds': 45}, {'duration_seconds': 45, 'reps': None},
    {'reps_in_reserve': 2, 'reps': None},
])
def test_generation_schema_preserves_strength_target_types(prescription):
    raw = valid_document()
    raw['sessions'][0].update(sport='strength', steps=[], strength_exercises=[{'name': 'Plank', **prescription}])
    Draft202012Validator(generation_schema(2, 4)).validate(raw)
    TrainingPlanDocument.model_validate(raw)


@pytest.mark.parametrize('prescription', [
    {'reps': 8, 'duration_seconds': 45}, {'reps': 0},
    {'duration_seconds': 45, 'reps_max': 10}, {'reps': '45s'},
])
def test_conflicting_strength_targets_are_excluded_from_new_generations(prescription):
    raw = valid_document()
    raw['sessions'][0].update(sport='strength', steps=[], strength_exercises=[{'name': 'Plank', **prescription}])
    with pytest.raises(ValidationError):
        Draft202012Validator(generation_schema(2, 4)).validate(raw)


def test_long_custom_prompt_cannot_remove_schema_contract_segment_counts_or_repair_feedback():
    instruction = training_plan_instruction('Custom preferences. ' * 1500, 'SEGMENT 1-2. Need 8 sessions. Validation feedback: bad repeat.')
    assert len(instruction) <= 16000
    assert STRUCTURED_PLAN_INSTRUCTION in instruction
    assert instruction.endswith('Validation feedback: bad repeat.')
    assert instruction.startswith('Custom preferences.')


def test_native_ollama_times_do_not_confuse_generation_speed_with_request_throughput():
    assert service.ollama_timing({'total_duration': 12000000000, 'load_duration': 100000000,
        'prompt_eval_duration': 1900000000, 'eval_duration': 10000000000, 'eval_count': 1000}) == {
        'total_seconds': 12, 'load_seconds': .1, 'prompt_seconds': 1.9,
        'generation_seconds': 10, 'generation_tokens_per_second': 100}
    assert service.ollama_timing({'eval_duration': 0, 'eval_count': 10}) == {'generation_seconds': 0}
    assert service.ollama_timing({'eval_duration': float('nan'), 'load_duration': True, 'total_duration': -1}) == {}


def contexts(monkeypatch):
    monkeypatch.setattr(ai, 'build_training_plan_context', AsyncMock(return_value={'lookback': {'days': 7}}))
    monkeypatch.setattr(ai, 'add_personal_context', AsyncMock(return_value={}))
    monkeypatch.setattr(ai, 'build_training_weather_context', AsyncMock(return_value=None))


async def test_successful_plan_retains_all_first_attempt_reasons_and_does_not_repeat_valid_segments(data, monkeypatch):
    factory, uid, _, mid = data
    contexts(monkeypatch)
    calls = []
    progress = []
    async def chat(db, messages, context, locale, **kw):
        calls.append({**kw, "messages": messages})
        raw = valid_document()
        # Exercise both completeness checks; the raw data stays schema-valid.
        if len(calls) == 1:
            raw['sessions'] = raw['sessions'][:4]
        elif len(calls) == 4:
            raw['sessions'][4]['week'] = 1
        kw['progress_callback']({'stage': 'connecting'})
        return {'content': json.dumps(raw), 'model_id': str(mid), 'model': 'Local', 'provider': 'Ollama',
            'max_output_tokens': kw['requested_max_tokens'], 'usage': {'input_tokens': 10, 'output_tokens': 100, 'total_tokens': 110},
            'elapsed_seconds': 10, 'tokens_per_second': 10, 'provider_timing': {'generation_seconds': 5},
            'truncated': False, 'stop_reason': 'stop'}
    monkeypatch.setattr(ai, 'chat', chat)
    result = await ai._training_plan(str(uid), {'weeks': 8, 'days_per_week': 4, 'session_minutes': 40,
        'max_tokens': 8000, 'model_id': str(mid), 'use_personal_context': False}, progress_callback=progress.append)
    metadata = result['metadata']
    rows = metadata['generation_calls']
    assert [r['attempt'] for r in rows] == [1, 2, 1, 1, 2, 1]
    assert rows[0]['validation_error'] == 'SEGMENT_SESSION_COUNT:4<8'
    assert rows[3]['validation_error'] == 'SEGMENT_WEEK_SESSION_COUNT:2:3/4'
    assert all(rows[i]['validation_valid'] for i in (1, 2, 4, 5))
    assert rows[0]['provider_timing'] == {'generation_seconds': 5}
    assert progress[1]['attempt'] == 2 and progress[1]['retry_reason'] == rows[0]['validation_error']
    assert metadata['elapsed_seconds'] == 60 and len(metadata['structured_plan']['sessions']) == 32
    assert result['usage']['total_tokens'] == 660
    assert 'SEGMENT_SESSION_COUNT:4<8' in calls[1]['messages'][-1]['content']
    assert all(c['response_format_schema']['properties']['sessions']['minItems'] == 8 for c in calls)
    async with factory() as db:
        saved = await db.get(AiRun, uuid.UUID(result['run_id']))
        assert saved.metadata_json['generation_calls'] == rows


async def test_real_ollama_request_passes_specialized_schema_and_preserves_native_timings(data, monkeypatch):
    factory, uid, _, mid = data
    contexts(monkeypatch)
    async with factory() as db:
        model = await db.get(LlmModel, mid)
        provider = await db.get(LlmProvider, model.provider_id)
        provider.provider_type = 'ollama'
        provider.base_url = 'http://local.test'
        await db.commit()
    requests = []
    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/api/show'):
            return httpx.Response(200, json={'thinking': {'values': [False, True]}})
        requests.append(body)
        schema = body['format']
        assert schema['properties']['weeks']['const'] == 2
        assert schema['properties']['sessions']['minItems'] == 8
        assert body['think'] is False
        Draft202012Validator(schema).validate(valid_document())
        chunks = [{'message': {'content': json.dumps(valid_document())}, 'done': False},
            {'message': {'content': ''}, 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 100,
            'eval_count': 1000, 'total_duration': 12000000000, 'load_duration': 100000000,
            'prompt_eval_duration': 1900000000, 'eval_duration': 10000000000}]
        return httpx.Response(200, content='\n'.join(json.dumps(c) for c in chunks)+'\n', headers={'content-type': 'application/x-ndjson'})
    client = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(handler)))
    result = await ai._training_plan(str(uid), {'weeks': 8, 'days_per_week': 4, 'session_minutes': 40,
        'model_id': str(mid), 'max_tokens': 8000, 'use_personal_context': False})
    assert len(requests) == 4
    assert all(c['validation_valid'] and c['provider_timing']['generation_tokens_per_second'] == 100
        for c in result['metadata']['generation_calls'])


def test_context_compaction_retains_previous_segment_progression():
    outline = [{'week': 1, 'day': 1, 'name': 'Easy ride', 'duration_min': 30}]
    context = {'goal': {'weeks': 2}, 'previous_plan_segment': outline,
        'lookback': {'activities': [{'details': 'data ' * 1000}] * 10}}
    payload, _ = service.bounded_personal_context(context, 4000)
    assert json.loads(payload)['previous_plan_segment'] == outline


@pytest.mark.parametrize('locale, label', [('de', 'Versuch 2 (erneut)'), ('en', 'attempt 2 (retry)')])
def test_live_status_distinguishes_last_segment_retry_from_first_attempt(locale, label):
    rows = []
    callback = ai._progress_callback(SimpleNamespace(update_state=lambda **kw: rows.append(kw)), {'locale': locale}, 'plan')
    callback({'stage': 'connecting', 'chunk_index': 4, 'chunk_count': 4, 'attempt': 2, 'retry_reason': 'SEGMENT_SESSION_COUNT:4<8'})
    assert label in rows[0]['meta']['message'] and '4/4' in rows[0]['meta']['message']
