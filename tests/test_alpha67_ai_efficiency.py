"""Regression cases from the cross-provider token/continuation audit."""
import asyncio
import copy
import json
import time
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator
from fastapi import HTTPException
from sqlalchemy import select
from test_alpha61_continuation import data  # noqa: F401
from test_alpha66_plan_generation import contexts, valid_document

from apps.api.routers import coach, continuation, admin_ai
from pengucoach.coach import execution
from pengucoach.db.models import Activity, AiRun, BackgroundJob, LlmModel, LlmProvider, PlanSchedule, TrainingReview, User, UserPreference
from pengucoach.llm import providers, service
from pengucoach.llm.usage import calculate_cost_eur, quality_budget
from worker.tasks import ai, continuation as worker, execution as execution_worker


@pytest.fixture(autouse=True)
def clear_capability_cache():
    providers._thinking.clear()
    providers._rejections.clear()


def mock_http(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kw: client(**kw, transport=httpx.MockTransport(handler)))


async def change_provider(data, kind, identifier=None):
    factory, _, _, mid = data
    async with factory() as db:
        model = await db.get(LlmModel, mid)
        provider = await db.get(LlmProvider, model.provider_id)
        provider.provider_type, provider.name, provider.base_url = kind, kind, "http://provider.test"
        if identifier:
            model.model_identifier = identifier
        await db.commit()


async def extend(data, run_id, additional=8000):
    factory, uid, _, _ = data
    async with factory() as db:
        queued = await continuation.continue_run(uuid.UUID(run_id), continuation.ContinueIn(revision=0, additional_tokens=additional), await db.get(User, uid), db)
    return await worker._continue(str(uid), {"run_id": run_id, "revision": 1}, task_id=queued["task_id"])


@pytest.mark.parametrize("kind", ["ollama", "openai", "openai_compatible", "ionos", "gemini", "xai", "openrouter", "anthropic"])
@pytest.mark.parametrize("feature", ["coach", "activity", "plan", "execution"])
@pytest.mark.parametrize("empty", [False, True])
async def test_every_feature_provider_and_empty_or_partial_limit_can_continue(data, monkeypatch, kind, feature, empty):
    factory, uid, _, mid = data
    contexts(monkeypatch)
    monkeypatch.setattr(execution_worker, "refresh_user", AsyncMock(return_value=None))
    monkeypatch.setattr(ai, "build_activity_analysis_context", AsyncMock(return_value={"activity": {"summary": {"name": "Ride"}}, "lookback": {"days": 7}}))
    async with factory() as db:
        activity = Activity(user_id=uid, garmin_activity_id=1, name="Ride", sport_type="cycling")
        db.add(activity)
        await db.flush()
        aid = activity.id
        parent = AiRun(user_id=uid, task_type="training_plan", model_id=mid, provider_name="Test", model_name="Test", prompt="", content="Plan", metadata_json={"structured_plan": valid_document()})
        db.add(parent)
        await db.flush()
        pid = parent.id
        db.add(PlanSchedule(plan_run_id=pid, user_id=uid, start_date=date(2026, 10, 12)))
        db.add(TrainingReview(user_id=uid, plan_run_id=pid, session_id="s1", activity_id=aid, fingerprint="fp", data={}))
        await db.commit()
    review = {"fingerprint": "fp", "session": {"activity_id": str(aid)}, "review": {"facts": {"planned": {}, "activity": {}, "feedback": {}, "offset_s": 0, "zone_date": None}, "summary": {}, "goals": {"steps": []}}}
    monkeypatch.setattr(execution, "review_session", AsyncMock(return_value=review))
    await change_provider(data, kind)
    replies, bodies = [], []
    limited = "" if empty else '{"title":"partial' if feature == "plan" else "Erster Teil."
    replies.extend([(limited, True)] * (2 if feature == "plan" else 1))
    replies.append((json.dumps(valid_document()) if feature == "plan" else "Weiterer Teil.", False))

    def handler(request):
        if request.url.path.endswith("/api/show"):
            return httpx.Response(200, json={"thinking": {"values": [False, True]}})
        bodies.append(json.loads(request.content))
        text, limit = replies.pop(0)
        count = 128 if limit else 20
        if kind == "ollama":
            events = [{"message": {"content": text}, "done": False}, {"message": {"content": ""}, "done": True, "done_reason": "length" if limit else "stop", "prompt_eval_count": 10, "eval_count": count}]
            return httpx.Response(200, content="\n".join(json.dumps(e) for e in events) + "\n")
        if kind == "anthropic":
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "stop_reason": "max_tokens" if limit else "end_turn", "usage": {"input_tokens": 10, "output_tokens": count}})
        return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "length" if limit else "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": count, "total_tokens": 10 + count}})

    mock_http(monkeypatch, handler)
    payload = {"model_id": str(mid), "max_tokens": 128, "context_window_tokens": 32768, "use_personal_context": False, "context_data": {"training": False}}
    if feature == "coach":
        initial = await ai._coach_chat(str(uid), {**payload, "message": "Frage", "context_mode": "none"})
    elif feature == "activity":
        initial = await ai._activity_analysis(str(uid), {**payload, "activity_id": str(aid)})
    elif feature == "execution":
        initial = await ai._session_analysis(str(uid), {**payload, "plan_id": str(pid), "session_id": "s1", "review_fingerprint": "fp"})
    else:
        initial = await ai._training_plan(str(uid), {**payload, "weeks": 2, "days_per_week": 4})
    assert initial["continuation"]["available"]
    result = await extend(data, initial["run_id"])
    assert not result["continuation"]["available"] and not replies
    assert result["usage"]["input_tokens"] == (30 if feature == "plan" else 20)
    assert result["usage"]["output_tokens"] == (276 if feature == "plan" else 148)
    if feature == "plan":
        assert len(result["metadata"]["structured_plan"]["sessions"]) == 8
    else:
        assert result["content"] == ("Weiterer Teil." if empty else "Erster Teil.\n\nWeiterer Teil.")
    if feature == "plan" and kind != "ollama":
        assert all(("output_config" if kind == "anthropic" else "response_format") in b for b in bodies)


async def test_saved_profiles_return_their_own_budget_after_loading(data):
    factory, uid, _, _ = data
    async with factory() as db:
        pref = await db.get(UserPreference, uid)
        pref.dashboard_config = {"ai_quality_profiles": {"coach_chat": "very_low", "activity_analysis": "low", "training_plan": "high"}}
        await db.commit()
        result = await coach.capabilities("de", await db.get(User, uid), db)
    for task, profile in [("coach_chat", "very_low"), ("activity_analysis", "low"), ("training_plan", "high")]:
        cfg = result["tasks"][task]
        assert cfg["max_output_tokens"] == quality_budget(task, cfg["standard_max_output_tokens"], profile)
        assert next(p["max_output_tokens"] for p in cfg["quality_profiles"] if p["id"] == profile) == cfg["max_output_tokens"]


async def test_default_model_caps_are_applied_before_form_values_are_loaded(data):
    factory, uid, _, mid = data
    async with factory() as db:
        model = await db.get(LlmModel, mid)
        model.context_window = 8192
        model.metadata_json = {"provider_max_output_tokens": 2048}
        await db.commit()
        result = await coach.capabilities("de", await db.get(User, uid), db)
    assert all(cfg["context_window_tokens"] <= 8192 and cfg["max_output_tokens"] <= 2048 for cfg in result["tasks"].values())


@pytest.mark.parametrize("kind,identifier,field", [("openai", "o3", "reasoning_effort"), ("openai", "gpt-5", "reasoning_effort"), ("gemini", "gemini-2.5-pro", "reasoning_effort"), ("xai", "grok-4.7", "reasoning_effort"), ("ionos", "gpt-oss-120b", "reasoning_effort"), ("openrouter", "vendor/reasoning", "reasoning")])
def test_provider_reasoning_controls_follow_profile_without_an_extra_budget(kind, identifier, field):
    options = providers.request_options(kind, identifier, {}, "very_low", None)
    assert options[field] == ({"effort": "low"} if field == "reasoning" else "low")
    if kind == "openai":
        assert options["output_parameter"] == "max_completion_tokens" and options["omit_temperature"]


async def test_openai_request_uses_current_output_parameter_and_no_incompatible_temperature(data, monkeypatch):
    factory, _, _, mid = data
    await change_provider(data, "openai", "o3")
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    mock_http(monkeypatch, handler)
    async with factory() as db:
        await service.chat(db, [{"role": "user", "content": "Frage"}], {}, "de", model_id=mid, requested_max_tokens=128, quality_profile="low")
    assert bodies[0]["max_completion_tokens"] == 128
    assert "max_tokens" not in bodies[0] and "temperature" not in bodies[0]
    assert bodies[0]["reasoning_effort"] == "low"


async def test_explicit_format_rejection_is_negotiated_once_and_cached(data, monkeypatch):
    factory, _, _, mid = data
    bodies = []
    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"param": "response_format", "message": "response_format not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
    mock_http(monkeypatch, handler)
    async with factory() as db:
        for _ in range(2):
            await service.chat(db, [{"role": "user", "content": "Plan"}], {}, "de", model_id=mid, task="training_plan", response_format_schema={"type": "object"}, requested_max_tokens=128)
    assert len(bodies) == 3 and "response_format" in bodies[0]
    assert all("response_format" not in b for b in bodies[1:])


def test_portable_schema_is_compact_and_all_objects_are_closed():
    from pengucoach.training_plan.schema import generation_schema
    schema = providers.compact_plan_schema()
    Draft202012Validator.check_schema(schema)
    assert len(json.dumps(schema)) < len(json.dumps(generation_schema(2, 4))) / 2
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(schema)


@pytest.mark.parametrize("values,expected", [([False, True], False), (["low", "medium", "high"], "low"), ([True], True), (["off", "low", "full"], "off"), (["fast", "deep"], "fast")])
async def test_ollama_uses_advertised_thinking_values(values, expected):
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={"thinking": {"values": values}})))
    assert await providers.ollama_think(client, "http://ollama.test", "model", "low", {}) == expected
    assert await providers.ollama_think(client, "http://ollama.test", "model", "low", {}) == expected
    assert client.post.await_count == 1


async def test_latest_long_question_is_preserved_and_impossible_request_is_rejected_before_network(data, monkeypatch):
    factory, _, _, mid = data
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}})
    mock_http(monkeypatch, handler)
    question = "ANFANG " + "x" * 7980 + " ENDE"
    async with factory() as db:
        await service.chat(db, [{"role": "user", "content": question}], {}, "de", model_id=mid, requested_max_tokens=8000, requested_context_window_tokens=16384)
        with pytest.raises(RuntimeError, match="USER_MESSAGE_TOO_LONG_FOR_CONTEXT"):
            await service.chat(db, [{"role": "user", "content": question}], {}, "de", model_id=mid, requested_max_tokens=8000, requested_context_window_tokens=4096)
    assert len(sent) == 1 and sent[0]["messages"][-1]["content"] == question


async def test_network_failure_preserves_checkpoint_and_resume_never_repeats_valid_weeks(data, monkeypatch):
    factory, uid, _, mid = data
    contexts(monkeypatch)
    starts, fail = [], True
    async def generate(db, messages, context, locale, **kw):
        nonlocal fail
        week = context["goal"]["plan_week_start"]
        starts.append(week)
        if week == 3 and fail:
            fail = False
            # The first valid segment was committed before the next provider call.
            async with factory() as check:
                saved = (await check.scalars(select(AiRun))).one()
                assert saved.metadata_json["validated_weeks"] == 2
                assert saved.metadata_json["generation_in_progress"]
            raise httpx.RemoteProtocolError("disconnect")
        return {"content": json.dumps(valid_document()), "model_id": str(mid), "provider": "Test", "model": "Test", "max_output_tokens": kw["requested_max_tokens"], "usage": {"input_tokens": 10, "output_tokens": 100, "total_tokens": 110}, "cost_eur": .01, "truncated": False}
    monkeypatch.setattr(ai, "chat", generate)
    initial = await ai._training_plan(str(uid), {"weeks": 8, "days_per_week": 4, "max_tokens": 8000, "model_id": str(mid), "use_personal_context": False})
    assert initial["continuation"]["reason"] == "interrupted"
    assert initial["metadata"]["validated_weeks"] == 2
    result = await extend(data, initial["run_id"], 0)
    assert starts == [1, 3, 3, 5, 7]
    assert result["run_id"] == initial["run_id"] and len(result["metadata"]["structured_plan"]["sessions"]) == 32
    assert result["usage"]["input_tokens"] is None and result["cost_eur"] is None
    assert not result["metadata"]["usage_complete"]
    async with factory() as db:
        stats = admin_ai._usage_aggregate(list((await db.scalars(select(AiRun))).all()))
    assert stats["totals"]["unknown_usage_requests"] == 1 and stats["totals"]["output_tokens"] == 400


async def test_short_plan_missing_sessions_is_a_retryable_draft_not_a_completed_plan(data, monkeypatch):
    _, uid, _, mid = data
    contexts(monkeypatch)
    calls = []
    async def generate(db, messages, context, locale, **kw):
        calls.append(kw["requested_max_tokens"])
        raw = valid_document()
        if len(calls) <= 2:
            raw["sessions"] = raw["sessions"][:1]
        return {"content": json.dumps(raw), "model_id": str(mid), "provider": "Test", "model": "Test", "max_output_tokens": kw["requested_max_tokens"], "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}, "truncated": False}
    monkeypatch.setattr(ai, "chat", generate)
    initial = await ai._training_plan(str(uid), {"weeks": 2, "days_per_week": 4, "max_tokens": 3500, "model_id": str(mid), "use_personal_context": False})
    assert initial["metadata"]["draft"] and not initial["metadata"]["structured_plan_valid"]
    result = await extend(data, initial["run_id"], 0)
    assert result["metadata"]["structured_plan_valid"] and calls == [3500, 3500, 3500]


@pytest.mark.parametrize("feature", ["coach", "activity", "plan"])
async def test_compatibility_endpoints_use_same_recoverable_engine(data, monkeypatch, feature):
    factory, uid, _, mid = data
    contexts(monkeypatch)
    monkeypatch.setattr(ai, "build_activity_analysis_context", AsyncMock(return_value={}))
    monkeypatch.setattr(execution_worker, "refresh_user", AsyncMock(return_value=None))
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {"prompt_tokens": 10, "completion_tokens": 128, "total_tokens": 138}})
    mock_http(monkeypatch, handler)
    async with factory() as db:
        user = await db.get(User, uid)
        if feature == "coach":
            result = await coach.coach_chat(coach.ChatRequest(message="Frage", context_mode="none", use_personal_context=False, model_id=mid, max_tokens=128), user, db)
        elif feature == "activity":
            result = await coach.activity_analysis(coach.ActivityAnalysisRequest(activity_id=uuid.uuid4(), model_id=mid, max_tokens=128), user, db)
        else:
            result = await coach.training_plan(coach.TrainingPlanRequest(weeks=2, days_per_week=4, model_id=mid, max_tokens=128, use_personal_context=False), user, db)
        assert result["continuation"]["available"] and result["run_id"]


async def test_cloud_request_cancellation_closes_pending_http_promptly(data, monkeypatch):
    factory, uid, _, mid = data
    cancelled = False
    request_closed = asyncio.Event()
    async def handler(request):
        nonlocal cancelled
        cancelled = True
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            request_closed.set()
            raise
    mock_http(monkeypatch, handler)
    started = time.monotonic()
    with pytest.raises(service.AiGenerationCancelled):
        await ai._coach_chat(str(uid), {"message": "Frage", "model_id": str(mid), "context_mode": "none", "use_personal_context": False}, cancel_check=lambda: cancelled)
    assert time.monotonic() - started < 2 and request_closed.is_set()
    async with factory() as db:
        ledger = (await db.scalars(select(AiRun))).one()
        assert ledger.metadata_json["usage_complete"] is False and ledger.metadata_json["request_status"] == "cancelled"


def test_unknown_usage_does_not_become_zero_cost_and_claude_context_stop_is_detected():
    assert calculate_cost_eur({}, {"input_eur_per_million": 1, "output_eur_per_million": 2}) is None
    assert service.response_truncated("model_context_window_exceeded", 100, 8000)


def test_context_compaction_omits_nulls_without_inventing_values():
    context = {"goal": {"weeks": 2, "constraints": "must remain complete"}, "lookback": {"activities": [{"summary": {"name": "Ride", "hr_min": None, "power": None, "distance_m": 1234}}]}}
    original = copy.deepcopy(context)
    payload, _ = service.bounded_personal_context(context, 4000)
    compact = json.loads(payload)
    assert compact["lookback"]["activities"][0]["summary"] == {"name": "Ride", "distance_m": 1234}
    assert compact["goal"] == original["goal"] and context == original


def test_claude_effort_and_format_rejections_do_not_disable_each_other():
    options = providers.request_options("anthropic", "claude-opus-4-7", {}, "low", {"type": "object"})
    assert options["output_config"]["effort"] == "low" and options["output_config"]["format"]["type"] == "json_schema"
    response = httpx.Response(400, text="output_config.format: json_schema unsupported")
    assert providers.adapt_rejected_options(response, options, ("claude",))
    assert options == {"output_config": {"effort": "low"}}
    fresh = providers.request_options("anthropic", "claude-opus-4-7", {}, "low", {"type": "object"})
    assert providers.apply_cached_options(fresh, ("claude",)) == options


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 503])
async def test_auth_rate_and_server_errors_are_not_parameter_retried(data, monkeypatch, status):
    factory, _, _, mid = data
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "response_format unavailable"}})
    mock_http(monkeypatch, handler)
    async with factory() as db:
        with pytest.raises(service.OpenRouterError):
            await service.chat(db, [{"role": "user", "content": "Plan"}], {}, "de", model_id=mid, response_format_schema={"type": "object"})
    assert len(requests) == 1


async def test_cancellation_after_cloud_reply_retains_reported_usage(data, monkeypatch):
    factory, uid, _, mid = data
    finished = False
    def handler(request):
        nonlocal finished
        finished = True
        return httpx.Response(200, json={"choices": [{"message": {"content": "An answer"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    mock_http(monkeypatch, handler)
    with pytest.raises(service.AiGenerationCancelled):
        await ai._coach_chat(str(uid), {"message": "Frage", "model_id": str(mid), "context_mode": "none", "use_personal_context": False}, cancel_check=lambda: finished)
    async with factory() as db:
        record = (await db.scalars(select(AiRun))).one()
        assert record.metadata_json["usage"]["total_tokens"] == 30 and record.metadata_json["usage_complete"]


async def test_plan_creation_does_not_overlap_an_active_plan_continuation(data, monkeypatch):
    factory, uid, _, mid = data
    task_id = uuid.uuid4()
    async with factory() as db:
        run = AiRun(user_id=uid, task_type="training_plan", model_id=mid, content="", prompt="", metadata_json={})
        db.add(run)
        await db.flush()
        db.add(BackgroundJob(id=task_id, user_id=uid, job_type="ai_continuation", payload={"run_id": str(run.id)}))
        await db.commit()
        monkeypatch.setattr(coach, "AsyncResult", lambda *a, **kw: SimpleNamespace(ready=lambda: False, state="PROGRESS"))
        enqueue = AsyncMock()
        monkeypatch.setattr(coach.training_plan_task, "delay", enqueue)
        response = await coach.queue_training_plan(coach.TrainingPlanRequest(model_id=mid), await db.get(User, uid), db)
    assert response["task_id"] == str(task_id) and response["status"] == "already_running"
    enqueue.assert_not_called()


def test_plan_constraints_survive_final_context_guard():
    goal = {"constraints": "This exact constraint must stay. " * 40, "weeks": 2}
    payload, _ = service.bounded_personal_context({"goal": goal, "lookback": {"activities": [{"name": "a" * 95} for _ in range(100)]}}, 2000)
    assert json.loads(payload)["goal"] == goal


@pytest.mark.parametrize("kind", ["openai", "ionos", "anthropic"])
async def test_malformed_provider_reply_is_recorded_as_unknown_instead_of_a_blank_success(data, monkeypatch, kind):
    factory, uid, _, mid = data
    await change_provider(data, kind)
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=["invalid response"]))
    with pytest.raises(service.AiProviderResponseError):
        await ai._coach_chat(str(uid), {"message": "Frage", "model_id": str(mid), "context_mode": "none", "use_personal_context": False})
    async with factory() as db:
        run = (await db.scalars(select(AiRun))).one()
        assert not run.metadata_json["usage_complete"] and run.metadata_json["_usage_only"]


async def test_preflight_failure_after_a_valid_section_preserves_a_retryable_checkpoint(data, monkeypatch):
    _, uid, _, mid = data
    contexts(monkeypatch)
    calls = 0
    async def generate(db, messages, context, locale, **kw):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("CONTEXT_TOO_SMALL_FOR_INSTRUCTIONS")
        return {"content": json.dumps(valid_document()), "model_id": str(mid), "model": "Test", "provider": "Test", "max_output_tokens": 4160, "usage": {"input_tokens": 10, "output_tokens": 100, "total_tokens": 110}, "truncated": False}
    monkeypatch.setattr(ai, "chat", generate)
    result = await ai._training_plan(str(uid), {"weeks": 4, "days_per_week": 4, "max_tokens": 8000, "model_id": str(mid), "use_personal_context": False})
    assert result["continuation"]["available"] and result["metadata"]["validated_weeks"] == 2
    assert result["usage"]["total_tokens"] == 110 and len(result["metadata"]["generation_calls"]) == 1


async def test_compatibility_routes_keep_not_found_status_without_any_provider_request(data, monkeypatch):
    factory, uid, _, mid = data
    mock_http(monkeypatch, lambda request: pytest.fail("Unknown objects must not reach a provider"))
    async with factory() as db:
        user = await db.get(User, uid)
        with pytest.raises(HTTPException) as error:
            await coach.activity_analysis(coach.ActivityAnalysisRequest(activity_id=uuid.uuid4(), model_id=mid), user, db)
        assert error.value.status_code == 404 and error.value.detail == "ACTIVITY_NOT_FOUND"
        with pytest.raises(HTTPException) as error:
            await coach.coach_chat(coach.ChatRequest(message="Frage", conversation_id=uuid.uuid4(), model_id=mid), user, db)
        assert error.value.status_code == 404 and error.value.detail == "CONVERSATION_NOT_FOUND"
