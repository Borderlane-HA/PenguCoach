from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import LlmModel, LlmProvider, LlmRoute
from pengucoach.security.crypto import SecretBox


SYSTEM_PROMPT = """You are PenguCoach, a self-hosted training and wellness analysis assistant.
Use only facts in the supplied context. Never invent health measurements. Clearly distinguish Garmin values,
PenguCoach calculated metrics and user-provided information. You are not a medical device and you do not diagnose,
treat, or provide medical clearance. If a user describes urgent or potentially serious symptoms, recommend prompt
professional medical assessment rather than giving training clearance. For nutrition, training, and health topics,
make uncertainty and missing data explicit. Reply in the requested language."""


async def _provider_model(db: AsyncSession, task: str = "coach_chat", local_only: bool = False) -> tuple[LlmProvider, LlmModel] | None:
    route = await db.get(LlmRoute, task)
    candidate_ids = []
    if route:
        candidate_ids.extend([route.primary_model_id, route.fallback_model_id])
    for model_id in [x for x in candidate_ids if x]:
        model = await db.get(LlmModel, model_id)
        if not model or not model.enabled:
            continue
        provider = await db.get(LlmProvider, model.provider_id)
        if provider and provider.enabled and (not local_only or provider.is_local):
            return provider, model
    models = (await db.scalars(select(LlmModel).where(LlmModel.enabled.is_(True)).order_by(LlmModel.display_name))).all()
    for model in models:
        provider = await db.get(LlmProvider, model.provider_id)
        if provider and provider.enabled and (not local_only or provider.is_local):
            return provider, model
    return None


def _secret(provider: LlmProvider) -> str | None:
    return SecretBox().decrypt(provider.secret_ciphertext) if provider.secret_ciphertext else None


async def chat(db: AsyncSession, messages: list[dict[str, str]], context: dict[str, Any], locale: str, task: str = "coach_chat", local_only: bool = False) -> dict[str, Any]:
    selected = await _provider_model(db, task, local_only=local_only)
    if not selected:
        raise RuntimeError("NO_ELIGIBLE_LLM_MODEL_CONFIGURED")
    provider, model = selected
    prompt_messages = [{"role": "system", "content": SYSTEM_PROMPT + f"\nResponse locale: {locale}.\nData context:\n" + json.dumps(context, ensure_ascii=False, default=str)}] + messages[-12:]
    timeout = httpx.Timeout(settings.ai_request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider.provider_type in {"openai", "openai_compatible"}:
            base = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
            headers = {"Authorization": f"Bearer {_secret(provider)}", "Content-Type": "application/json"}
            response = await client.post(base + "/chat/completions", headers=headers, json={"model": model.model_identifier, "messages": prompt_messages, "temperature": model.temperature})
            response.raise_for_status(); body = response.json(); text = body["choices"][0]["message"]["content"]
        elif provider.provider_type == "anthropic":
            base = (provider.base_url or "https://api.anthropic.com/v1").rstrip("/")
            headers = {"x-api-key": _secret(provider) or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
            system = prompt_messages[0]["content"]
            response = await client.post(base + "/messages", headers=headers, json={"model": model.model_identifier, "system": system, "max_tokens": 2048, "temperature": model.temperature, "messages": prompt_messages[1:]})
            response.raise_for_status(); body = response.json(); text = "\n".join(x.get("text", "") for x in body.get("content", []) if x.get("type") == "text")
        elif provider.provider_type == "ollama":
            base = (provider.base_url or "http://127.0.0.1:11434").rstrip("/")
            response = await client.post(base + "/api/chat", json={"model": model.model_identifier, "messages": prompt_messages, "stream": False, "options": {"temperature": model.temperature}})
            response.raise_for_status(); body = response.json(); text = body.get("message", {}).get("content", "")
        else:
            raise RuntimeError("UNSUPPORTED_LLM_PROVIDER")
    return {"content": text, "provider": provider.name, "model": model.display_name, "model_id": str(model.id), "local": provider.is_local}


async def test_provider(provider_type: str, base_url: str | None, api_key: str | None) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider_type == "ollama":
            response = await client.get((base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/tags")
            response.raise_for_status(); models = [x.get("name") for x in response.json().get("models", [])]
            return {"ok": True, "models": models}
        if provider_type in {"openai", "openai_compatible"}:
            base = (base_url or "https://api.openai.com/v1").rstrip("/")
            response = await client.get(base + "/models", headers={"Authorization": f"Bearer {api_key or ''}"})
            response.raise_for_status(); return {"ok": True, "models": [x.get("id") for x in response.json().get("data", [])][:100]}
        if provider_type == "anthropic":
            return {"ok": bool(api_key), "models": [], "note": "Anthropic key stored; model identifiers are configured manually."}
    return {"ok": False}
