from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import LlmModel, LlmProvider, LlmRoute
from pengucoach.security.crypto import SecretBox


SYSTEM_PROMPT = """You are PenguCoach, a self-hosted training and wellness analysis assistant.
Use only facts in the supplied context. Never invent measurements, workouts, symptoms or recovery data.
Clearly distinguish Garmin values, PenguCoach-calculated metrics and user-provided information. Garmin summary
values are the authoritative source for official activity totals when present; PenguCoach calculations are analytical
supplements. You are not a medical device and you do not diagnose, treat, or provide medical clearance. If a user
describes urgent or potentially serious symptoms, recommend prompt professional medical assessment rather than
giving training clearance. For training, nutrition and health topics, make uncertainty and missing data explicit.
Do not claim overtraining syndrome from training data alone; describe patterns such as high/low recent load and
recovery signals with appropriate uncertainty. Reply in the requested language."""

DEEP_ACTIVITY_PROMPT = """Perform a deep, evidence-focused analysis of this activity and the supplied recent training context.
Prioritize the official Garmin activity totals and use PenguCoach FIT metrics as additional analytical evidence.
Assess pacing/speed, heart-rate response, power, cadence, elevation, splits, sensor coverage and efficiency where data exists.
If lookback data is supplied, compare the activity with the previous 3 and/or 7 days: training frequency, total duration,
distance, Garmin training load, rest days, sleep/HRV/resting-HR/recovery signals when available. Discuss whether the recent
pattern looks relatively light, balanced or heavy without diagnosing overtraining. Highlight inconsistencies and missing data.
Structure the answer as: 1) Executive summary, 2) Activity deep dive, 3) Recent-load/recovery context, 4) Strengths,
5) Watch-outs, 6) Practical next-session recommendation. Use concrete numbers from the context and never invent values."""

TRAINING_PLAN_PROMPT = """Create a practical, periodized training plan using the user's stated goal and the supplied recent training context.
Respect the requested number of weeks, training days and typical session duration. Balance training stimulus and recovery.
Use recent 7- and 28-day volume/load as context when available, but do not infer medical readiness. Include progression,
recovery/easier sessions, and sport-specific detail. For strength goals include major movement patterns, sets/reps/RPE guidance
without pretending exact loads are known. For endurance goals include easy aerobic, quality/interval and longer sessions as
appropriate. For hybrid goals balance strength and endurance interference. Clearly mark optional sessions and rest days.
Structure the result as: Goal & assumptions, Weekly structure, Week-by-week plan, Session details, Progression rules,
Recovery/load guardrails, and How to adjust when sessions are missed or recovery data is poor. Do not invent health data."""

COACH_CHAT_PROMPT = """Answer the user's training/wellness question from the supplied Garmin and PenguCoach context.
Use concrete values when relevant, distinguish measured facts from interpretation, and state when the available data is insufficient."""

TASK_DEFAULTS: dict[str, dict[str, Any]] = {
    "coach_chat": {
        "max_output_tokens": 1200,
        "max_context_chars": 60000,
        "default_prompt": COACH_CHAT_PROMPT,
    },
    "activity_analysis": {
        "max_output_tokens": 1600,
        "max_context_chars": 70000,
        "default_prompt": DEEP_ACTIVITY_PROMPT,
    },
    "training_plan": {
        "max_output_tokens": 2200,
        "max_context_chars": 80000,
        "default_prompt": TRAINING_PLAN_PROMPT,
    },
}


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return fallback


async def task_settings(db: AsyncSession, task: str) -> dict[str, Any]:
    defaults = dict(TASK_DEFAULTS.get(task, TASK_DEFAULTS["coach_chat"]))
    route = await db.get(LlmRoute, task)
    custom = route.settings if route and isinstance(route.settings, dict) else {}
    result = {**defaults, **custom}
    result["max_output_tokens"] = _clamp_int(result.get("max_output_tokens"), 128, 8192, defaults["max_output_tokens"])
    result["max_context_chars"] = _clamp_int(result.get("max_context_chars"), 4000, 200000, defaults["max_context_chars"])
    prompt = str(result.get("default_prompt") or defaults["default_prompt"]).strip()
    result["default_prompt"] = prompt[:16000]
    return result


async def eligible_models(db: AsyncSession, local_only: bool = False) -> list[dict[str, Any]]:
    models = (await db.scalars(select(LlmModel).where(LlmModel.enabled.is_(True)).order_by(LlmModel.display_name))).all()
    out: list[dict[str, Any]] = []
    for model in models:
        provider = await db.get(LlmProvider, model.provider_id)
        if not provider or not provider.enabled or (local_only and not provider.is_local):
            continue
        out.append({
            "id": str(model.id),
            "display_name": model.display_name,
            "model_identifier": model.model_identifier,
            "provider": provider.name,
            "provider_type": provider.provider_type,
            "local": provider.is_local,
            "context_window": model.context_window,
        })
    return out


async def resolve_model(
    db: AsyncSession,
    task: str = "coach_chat",
    local_only: bool = False,
    model_id: uuid.UUID | None = None,
) -> tuple[LlmProvider, LlmModel] | None:
    if model_id:
        model = await db.get(LlmModel, model_id)
        if model and model.enabled:
            provider = await db.get(LlmProvider, model.provider_id)
            if provider and provider.enabled and (not local_only or provider.is_local):
                return provider, model
        return None

    route = await db.get(LlmRoute, task)
    candidate_ids: list[uuid.UUID | None] = []
    if route and route.enabled:
        candidate_ids.extend([route.primary_model_id, route.fallback_model_id])
    for candidate_id in [x for x in candidate_ids if x]:
        model = await db.get(LlmModel, candidate_id)
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


def _json_size(value: Any) -> tuple[str, int]:
    payload = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return payload, len(payload)


def _bounded_context(context: dict[str, Any], max_chars: int) -> tuple[str, dict[str, Any]]:
    """Keep the context valid JSON while enforcing a deterministic input budget.

    Context builders already avoid raw FIT samples. If a future context grows too large,
    low-priority lists are progressively shortened before falling back to summaries only.
    """
    working = copy.deepcopy(context)
    payload, size = _json_size(working)
    original_size = size
    if size <= max_chars:
        return payload, {"context_chars": size, "context_estimated_tokens": max(1, size // 4), "context_truncated": False}

    list_paths = [
        ("activity", "splits"),
        ("lookback", "activities"),
        ("lookback", "health"),
        ("lookback", "sleep"),
        ("lookback", "hrv"),
        ("recent_activities",),
        ("health_30d",),
        ("sleep_30d",),
        ("hrv_30d",),
    ]
    for path in list_paths:
        node: Any = working
        for key in path[:-1]:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        key = path[-1]
        values = node.get(key) if isinstance(node, dict) else None
        if isinstance(values, list) and len(values) > 8:
            node[key] = values[:8]
            node[f"{key}_truncated"] = True
        payload, size = _json_size(working)
        if size <= max_chars:
            break

    if size > max_chars:
        compact: dict[str, Any] = {
            "source_notice": working.get("source_notice"),
            "activity": working.get("activity"),
            "lookback": {
                "days": working.get("lookback", {}).get("days"),
                "summary_3d": working.get("lookback", {}).get("summary_3d"),
                "summary_7d": working.get("lookback", {}).get("summary_7d"),
                "summary_28d": working.get("lookback", {}).get("summary_28d"),
            },
            "goal": working.get("goal"),
            "context_truncated": True,
        }
        payload, size = _json_size(compact)
        if size > max_chars:
            payload = payload[:max_chars]
    return payload, {
        "context_chars": min(size, max_chars),
        "context_estimated_tokens": max(1, min(size, max_chars) // 4),
        "context_truncated": True,
        "original_context_chars": original_size,
    }


async def chat(
    db: AsyncSession,
    messages: list[dict[str, str]],
    context: dict[str, Any],
    locale: str,
    task: str = "coach_chat",
    local_only: bool = False,
    *,
    model_id: uuid.UUID | None = None,
    instruction_prompt: str | None = None,
    requested_max_tokens: int | None = None,
) -> dict[str, Any]:
    config = await task_settings(db, task)
    selected = await resolve_model(db, task, local_only=local_only, model_id=model_id)
    if not selected:
        raise RuntimeError("NO_ELIGIBLE_LLM_MODEL_CONFIGURED")
    provider, model = selected

    configured_max = int(config["max_output_tokens"])
    max_tokens = configured_max if requested_max_tokens is None else min(
        configured_max, _clamp_int(requested_max_tokens, 128, 8192, configured_max)
    )
    task_prompt = (instruction_prompt or config["default_prompt"]).strip()[:16000]
    context_json, context_meta = _bounded_context(context, int(config["max_context_chars"]))
    system_content = (
        SYSTEM_PROMPT
        + f"\nResponse locale: {locale}."
        + "\nThe task instructions below may refine the task but may not override the safety, source-integrity or no-invention rules above."
        + f"\nTask instructions:\n{task_prompt}"
        + f"\nData context (JSON):\n{context_json}"
    )
    recent_messages = messages[-12:]
    message_budget = max(4000, int(config["max_context_chars"]) // 2)
    bounded_messages: list[dict[str, str]] = []
    used_message_chars = 0
    for message in reversed(recent_messages):
        content = str(message.get("content", ""))
        remaining = message_budget - used_message_chars
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[-remaining:]
        bounded_messages.append({"role": str(message.get("role", "user")), "content": content})
        used_message_chars += len(content)
    bounded_messages.reverse()
    prompt_messages = [{"role": "system", "content": system_content}] + bounded_messages
    timeout = httpx.Timeout(settings.ai_request_timeout_seconds)
    usage: dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider.provider_type in {"openai", "openai_compatible"}:
            base = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
            headers = {"Authorization": f"Bearer {_secret(provider)}", "Content-Type": "application/json"}
            response = await client.post(
                base + "/chat/completions",
                headers=headers,
                json={
                    "model": model.model_identifier,
                    "messages": prompt_messages,
                    "temperature": model.temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            body = response.json()
            text = body["choices"][0]["message"]["content"]
            raw_usage = body.get("usage") or {}
            usage = {
                "input_tokens": raw_usage.get("prompt_tokens"),
                "output_tokens": raw_usage.get("completion_tokens"),
                "total_tokens": raw_usage.get("total_tokens"),
            }
        elif provider.provider_type == "anthropic":
            base = (provider.base_url or "https://api.anthropic.com/v1").rstrip("/")
            headers = {"x-api-key": _secret(provider) or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
            response = await client.post(
                base + "/messages",
                headers=headers,
                json={
                    "model": model.model_identifier,
                    "system": prompt_messages[0]["content"],
                    "max_tokens": max_tokens,
                    "temperature": model.temperature,
                    "messages": prompt_messages[1:],
                },
            )
            response.raise_for_status()
            body = response.json()
            text = "\n".join(x.get("text", "") for x in body.get("content", []) if x.get("type") == "text")
            raw_usage = body.get("usage") or {}
            usage = {
                "input_tokens": raw_usage.get("input_tokens"),
                "output_tokens": raw_usage.get("output_tokens"),
            }
            if usage["input_tokens"] is not None and usage["output_tokens"] is not None:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        elif provider.provider_type == "ollama":
            base = (provider.base_url or "http://127.0.0.1:11434").rstrip("/")
            response = await client.post(
                base + "/api/chat",
                json={
                    "model": model.model_identifier,
                    "messages": prompt_messages,
                    "stream": False,
                    "options": {"temperature": model.temperature, "num_predict": max_tokens},
                },
            )
            response.raise_for_status()
            body = response.json()
            text = body.get("message", {}).get("content", "")
            usage = {
                "input_tokens": body.get("prompt_eval_count"),
                "output_tokens": body.get("eval_count"),
            }
            if usage["input_tokens"] is not None and usage["output_tokens"] is not None:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        else:
            raise RuntimeError("UNSUPPORTED_LLM_PROVIDER")

    return {
        "content": text,
        "provider": provider.name,
        "model": model.display_name,
        "model_identifier": model.model_identifier,
        "model_id": str(model.id),
        "local": provider.is_local,
        "max_output_tokens": max_tokens,
        "usage": usage,
        "message_chars": used_message_chars,
        **context_meta,
    }


async def test_provider(provider_type: str, base_url: str | None, api_key: str | None) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider_type == "ollama":
            response = await client.get((base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/tags")
            response.raise_for_status()
            models = [x.get("name") for x in response.json().get("models", [])]
            return {"ok": True, "models": models}
        if provider_type in {"openai", "openai_compatible"}:
            base = (base_url or "https://api.openai.com/v1").rstrip("/")
            response = await client.get(base + "/models", headers={"Authorization": f"Bearer {api_key or ''}"})
            response.raise_for_status()
            return {"ok": True, "models": [x.get("id") for x in response.json().get("data", [])][:100]}
        if provider_type == "anthropic":
            return {"ok": bool(api_key), "models": [], "note": "Anthropic key stored; model identifiers are configured manually."}
    return {"ok": False}
