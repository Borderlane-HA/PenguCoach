"""Native OpenRouter contract, cloud-policy and request/response integration tests."""
import json
import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.routers import admin_ai as admin
from pengucoach.db.base import Base
from pengucoach.db.models import LlmModel, LlmProvider, LlmRoute
from pengucoach.llm import service
from pengucoach.security import crypto


@compiles(JSONB, "sqlite")
def json_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setattr(crypto.settings, "encryption_key", Fernet.generate_key().decode())
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def mock_http(monkeypatch, handler):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: client_class(
        **kwargs, transport=httpx.MockTransport(handler)))


async def stored_model(db):
    saved = await admin.create_provider(admin.ProviderIn(name="OpenRouter", provider_type="openrouter",
                                                       api_key="  secret-test-key  ", is_local=True), None, db)
    provider = await db.get(LlmProvider, uuid.UUID(saved["id"]))
    model = LlmModel(provider_id=provider.id, model_identifier="vendor/model:free", display_name="Test model",
                     context_window=16384, temperature=.2, enabled=True,
                     metadata_json={"provider_max_output_tokens": 1024})
    db.add(model)
    await db.commit()
    return provider, model


async def test_storage_api_and_every_selection_path_enforce_cloud_policy(db):
    provider, model = await stored_model(db)
    assert not provider.is_local
    assert provider.secret_ciphertext != "secret-test-key"
    assert service._secret(provider) == "secret-test-key"
    await admin.update_provider(provider.id, admin.ProviderUpdate(name="OpenRouter", is_local=True), None, db)
    assert not provider.is_local and service._secret(provider) == "secret-test-key"
    provider.is_local = True
    db.add(LlmRoute(task_type="coach_chat", primary_model_id=model.id, enabled=True))
    await db.commit()
    listed = await admin.providers(None, db)
    assert listed[0]["is_local"] is False and listed[0]["has_secret"] is True
    assert "secret-test-key" not in json.dumps(listed) and "secret_ciphertext" not in json.dumps(listed)
    assert (await admin.models(None, db))[0]["local"] is False
    assert (await service.eligible_models(db))[0]["local"] is False
    assert await service.eligible_models(db, local_only=True) == []
    for model_id in (None, model.id):
        assert await service.resolve_model(db, local_only=True, model_id=model_id) is None
        assert (await service.resolve_model(db, model_id=model_id))[1].id == model.id
    local = LlmProvider(name="Local", provider_type="ollama", is_local=True, enabled=True)
    db.add(local)
    await db.flush()
    local_model = LlmModel(provider_id=local.id, model_identifier="local", display_name="Local", enabled=True)
    db.add(local_model)
    await db.commit()
    assert (await service.resolve_model(db, local_only=True))[1].id == local_model.id


async def test_missing_key_is_rejected_without_network_and_api_errors_are_safe(db, monkeypatch):
    def unexpected(request):
        pytest.fail("A missing key must not make an external request")
    mock_http(monkeypatch, unexpected)
    payload = admin.ProviderIn(name="OpenRouter", provider_type="openrouter", api_key="  ")
    with pytest.raises(HTTPException) as error:
        await admin.create_provider(payload, None, db)
    assert error.value.detail == "OPENROUTER_API_KEY_REQUIRED"
    with pytest.raises(HTTPException) as error:
        await admin.provider_test(payload, None)
    assert error.value.detail == "OPENROUTER_API_KEY_REQUIRED"
    with pytest.raises(service.OpenRouterError, match="^OPENROUTER_API_KEY_REQUIRED$"):
        await service.test_provider("openrouter", None, None)


async def test_discovery_validates_key_before_full_text_catalog_and_imports_limits(db, monkeypatch):
    requests = []
    catalog = [{"id": f"vendor/model-{n}:free", "name": f"Model {n}", "context_length": 128000,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "top_provider": {"context_length": 64000, "max_completion_tokens": 8192},
                "pricing": {"prompt": "0.000001", "completion": "0.000002"}} for n in range(137)]
    catalog += [{"id": "audio/only", "architecture": {"output_modalities": ["audio"]}},
                {"id": "embed/only", "architecture": {"output_modalities": ["embeddings"]}},
                {"id": "old/unknown"}, {"id": "vendor/model-0:free"}, None,
                {"id": "too/small", "context_length": 512}]
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer secret-test-key"
        assert request.headers["X-OpenRouter-Title"] == "PenguCoach"
        assert "HTTP-Referer" not in request.headers
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"label": "private account", "limit": 99}})
        return httpx.Response(200, json={"data": catalog})
    mock_http(monkeypatch, handler)
    result = await service.test_provider("openrouter", None, " secret-test-key ")
    assert [str(r.url) for r in requests] == ["https://openrouter.ai/api/v1/key", "https://openrouter.ai/api/v1/models"]
    assert len(result["models"]) == 138 and result["models"][-1] == "old/unknown"
    assert "private account" not in json.dumps(result) and "pricing" not in json.dumps(result)
    item = result["model_details"][136]
    assert item == {"id": "vendor/model-136:free", "display_name": "Model 136", "context_window": 64000,
                    "max_output_tokens": 8192}
    assert result["model_details"][-1]["context_window"] is None
    provider, _ = await stored_model(db)
    added = await admin.create_model(admin.ModelIn(provider_id=provider.id, model_identifier=item["id"],
                                    display_name=item["display_name"], context_window=item["context_window"],
                                    provider_max_output_tokens=item["max_output_tokens"]), None, db)
    model = await db.get(LlmModel, uuid.UUID(added["id"]))
    assert model.context_window == 64000 and model.metadata_json == {"provider_max_output_tokens": 8192}
    duplicate = await admin.create_model(admin.ModelIn(provider_id=provider.id, model_identifier=item["id"],
                                        display_name="Duplicate"), None, db)
    assert duplicate["existing"] is True and duplicate["id"] == added["id"]


@pytest.mark.parametrize("status,body,code", [
    (401, {"error": {"message": "secret-test-key private account"}}, "OPENROUTER_INVALID_API_KEY"),
    (402, {}, "OPENROUTER_CREDITS_REQUIRED"),
    (403, {}, "OPENROUTER_ACCESS_DENIED"),
    (429, {}, "OPENROUTER_RATE_LIMITED"),
    (503, {}, "OPENROUTER_UPSTREAM_UNAVAILABLE"),
    (200, {"error": {"code": "401", "message": "secret-test-key"}}, "OPENROUTER_INVALID_API_KEY"),
    (200, {"error": {"code": "unexpected", "message": "private prompt"}}, "OPENROUTER_REQUEST_FAILED"),
    (200, [], "OPENROUTER_INVALID_RESPONSE"),
    (200, {"data": []}, "OPENROUTER_INVALID_RESPONSE"),
])
async def test_key_failures_never_fetch_public_catalog_or_expose_raw_errors(db, monkeypatch, status, body, code):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json=body)
    mock_http(monkeypatch, handler)
    provider, _ = await stored_model(db)
    with pytest.raises(HTTPException) as error:
        await admin.discover_provider_models(provider.id, None, db)
    assert error.value.detail == code and calls == ["/api/v1/key"]


@pytest.mark.parametrize("task", ["coach_chat", "activity_analysis", "training_plan"])
async def test_chat_all_tasks_preserve_model_id_budget_content_usage_and_local_only(db, monkeypatch, task):
    provider, model = await stored_model(db)
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret-test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "vendor/model:free"
        assert payload["max_tokens"] == 1024
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][-1]["content"] == "Please help"
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>hidden</think>Useful answer"},
                                                     "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 120, "completion_tokens": 50, "total_tokens": 170}})
    mock_http(monkeypatch, handler)
    result = await service.chat(db, [{"role": "user", "content": "Please help"}], {}, "en", task=task,
                                model_id=model.id, requested_max_tokens=8000)
    assert result["content"] == "Useful answer" and result["local"] is False and not result["truncated"]
    assert result["usage"] == {"input_tokens": 120, "output_tokens": 50, "total_tokens": 170}
    assert result["max_output_tokens"] == 1024 and result["model_identifier"] == "vendor/model:free"
    assert result["cost_eur"] is None
    provider.is_local = True
    await db.commit()
    with pytest.raises(RuntimeError, match="NO_ELIGIBLE_LLM_MODEL_CONFIGURED"):
        await service.chat(db, [], {}, "en", task=task, model_id=model.id, local_only=True)
    assert len(calls) == 1


@pytest.mark.parametrize("body,code", [
    ({"error": {"code": 402, "message": "private prompt"}}, "OPENROUTER_CREDITS_REQUIRED"),
    ({"choices": [{"message": {"content": "partial"}, "finish_reason": "error"}]}, "OPENROUTER_UPSTREAM_UNAVAILABLE"),
    ({"choices": [{"message": {"content": "partial"}, "finish_reason": "content_filter"}]}, "OPENROUTER_CONTENT_FILTERED"),
    ({"choices": []}, "OPENROUTER_INVALID_RESPONSE"),
])
async def test_completion_errors_are_not_accepted_as_success(db, monkeypatch, body, code):
    _, model = await stored_model(db)
    mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(service.OpenRouterError, match=f"^{code}$"):
        await service.chat(db, [], {}, "en", model_id=model.id)


async def test_length_stop_remains_visible_as_truncated(db, monkeypatch):
    _, model = await stored_model(db)
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "Partial answer"}, "finish_reason": "length"}],
        "usage": {"completion_tokens": 1024}}))
    assert (await service.chat(db, [], {}, "en", model_id=model.id))["truncated"] is True


@pytest.mark.parametrize("provider", ["openai", "ionos", "gemini", "xai", "openai_compatible"])
async def test_other_compatible_provider_discovery_does_not_require_openrouter_key_endpoint(monkeypatch, provider):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "existing-model"}]})
    mock_http(monkeypatch, handler)
    assert (await service.test_provider(provider, "https://example.test/v1", "key"))["models"] == ["existing-model"]
    assert calls == ["/v1/models"]
