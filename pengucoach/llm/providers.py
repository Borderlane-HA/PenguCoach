"""Provider parameters and small, portable schemas for newly generated plans.

The stored plan model remains the source of truth. Provider grammar subsets only
help generation; every response is still checked against the application model.
"""
from __future__ import annotations

import asyncio
import copy
import re
import time

import httpx


def compact_plan_schema() -> dict:
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    string = {"type": "string"}
    integer = {"type": "integer"}
    number = {"type": "number"}
    nullable_number = {"type": ["number", "null"]}
    target = {"anyOf": [
        obj({"type": {"type": "string", "enum": ["none"]}}),
        obj({"type": {"type": "string", "enum": ["heart_rate_zone", "power_zone"]}, "zone": integer}),
        obj({"type": {"type": "string", "enum": ["power_watts"]}, "watts": number, "tolerance_pct": number}),
    ]}
    executable = {"type": "string", "enum": ["warmup", "work", "interval", "recovery", "cooldown", "rest"]}
    step = {"anyOf": [
        obj({"type": executable, "duration_seconds": integer, "target": {"$ref": "#/$defs/Target"}}),
        obj({"type": executable, "distance_meters": number, "target": {"$ref": "#/$defs/Target"}}),
        obj({"type": {"type": "string", "enum": ["repeat"]}, "repeat": integer,
             "steps": {"type": "array", "items": {"$ref": "#/$defs/Step"}}}),
    ]}
    exercise = {"anyOf": [obj({"name": string, "sets": integer, **prescription,
                               "rest_seconds": integer, "weight_kg": nullable_number}) for prescription in (
        {"reps": integer, "reps_max": {"type": ["integer", "null"]}},
        {"duration_seconds": integer}, {"reps_in_reserve": integer},
    )]}
    session = obj({
        "id": string, "week": integer, "day": integer, "name": string,
        "sport": {"type": "string", "enum": ["running", "cycling", "swimming", "walking", "hiking", "strength",
                                                "cardio", "mobility", "yoga", "pilates", "hiit", "other"]},
        "duration_min": integer, "start_time": {"type": ["string", "null"]},
        "optional": {"type": "boolean"}, "notes": string,
        "steps": {"type": "array", "items": {"$ref": "#/$defs/Step"}},
        "strength_exercises": {"type": "array", "items": {"$ref": "#/$defs/Exercise"}},
    })
    schema = obj({"title": string, "summary": string, "weeks": integer,
                  "sessions": {"type": "array", "items": {"$ref": "#/$defs/Session"}}})
    schema["$defs"] = {"Target": target, "Step": step, "Exercise": exercise, "Session": session}
    return schema


def request_options(provider_type: str, identifier: str, metadata: dict, quality: str, schema: dict | None) -> dict:
    """Use conservative documented controls; never enable a hidden extra budget."""
    name = identifier.lower().split("/")[-1]
    effort = {"very_low": "low", "low": "low", "standard": "medium", "high": "high"}.get(quality, "medium")
    options = {}
    if provider_type == "openai":
        options["output_parameter"] = "max_completion_tokens"
        if re.match(r"(?:o[134](?:-|$)|gpt-5(?:[.-]|$))", name) and "chat" not in name:
            options.update(reasoning_effort=effort, omit_temperature=True)
    elif provider_type == "gemini" and re.match(r"gemini-(?:2\.5|[3-9])", name):
        options["reasoning_effort"] = "none" if name.startswith("gemini-2.5-") and "pro" not in name and quality in {"very_low", "low"} else effort
    elif provider_type == "xai" and "non-reasoning" not in name and ("reasoning" in name or re.match(r"grok-4\.[5-9]", name)):
        options["reasoning_effort"] = effort
    elif provider_type == "openrouter":
        supported = metadata.get("supported_parameters")
        if supported is None or "reasoning" in supported or "reasoning_effort" in supported:
            efforts = metadata.get("reasoning_supported_efforts") or []
            if quality in {"very_low", "low"} and "none" in efforts and metadata.get("reasoning_mandatory") is False:
                effort = "none"
            elif efforts and effort not in efforts:
                effort = next((x for x in ("low", "medium", "high") if x in efforts), None)
            if effort:
                options["reasoning"] = {"effort": effort}
    elif provider_type in {"ionos", "openai_compatible"}:
        supported = metadata.get("supported_parameters") or []
        if "reasoning_effort" in supported or name.startswith("gpt-oss"):
            options["reasoning_effort"] = effort
    if provider_type == "anthropic" and re.match(r"claude-(?:opus-4-[5-9]|sonnet-4-[6-9]|(?:opus|sonnet|haiku|fable|mythos)-5)", name):
        options["output_config"] = {"effort": effort}
    if schema is not None:
        portable = compact_plan_schema()
        if provider_type == "anthropic":
            options.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": portable}
        elif provider_type != "ollama":
            options["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "pengucoach_training_plan", "strict": True, "schema": portable}}
    return options


# A provider's explicit parameter rejection is cached, not guessed from a failed
# generation. Cache keys contain IDs/URLs, never API keys or training content.
_rejections: dict[tuple, tuple[float, set[str]]] = {}
_thinking: dict[tuple, tuple[float, list]] = {}


def cached_rejections(key: tuple) -> set[str]:
    timestamp, rejected = _rejections.get(key, (0, set()))
    return set(rejected) if time.monotonic() - timestamp < 3600 else set()


def remember_rejection(key: tuple, field: str) -> None:
    _rejections[key] = (time.monotonic(), cached_rejections(key) | {field})
    if len(_rejections) > 512:
        _rejections.pop(next(iter(_rejections)))


def adapt_rejected_options(response: httpx.Response, payload: dict, key: tuple) -> bool:
    """Retry parameter validation errors only; never replay a generated answer."""
    if response.status_code not in {400, 422}:
        return False
    detail = response.text.lower()[:12000]
    changed = False
    if "output_config" in payload and isinstance(payload["output_config"], dict):
        # Claude can support effort while rejecting a schema, or vice versa.
        for nested in ("format", "effort"):
            if nested in payload["output_config"] and (f"output_config.{nested}" in detail or
                (nested == "format" and any(x in detail for x in ("json_schema", "json schema", "grammar")))):
                payload["output_config"].pop(nested)
                remember_rejection(key, f"output_config.{nested}")
                changed = True
        if changed:
            if not payload["output_config"]:
                payload.pop("output_config")
            return True
    for field in ("response_format", "output_config", "reasoning_effort", "reasoning", "temperature", "think"):
        if field in payload and (field in detail or (field in {"response_format", "output_config"} and
                                                  any(x in detail for x in ("json_schema", "json schema", "grammar")))):
            payload.pop(field)
            remember_rejection(key, field)
            changed = True
    return changed


async def cancellable_post(client, url, *, cancel_check=None, **kwargs):
    """Close the local HTTP request promptly. Remote cancellation is provider-owned."""
    if cancel_check is None:
        return await client.post(url, **kwargs)
    task = asyncio.create_task(client.post(url, **kwargs))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if task in done:
                return await task
            if cancel_check():
                raise asyncio.CancelledError()
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def ollama_think(client, base: str, identifier: str, quality: str, metadata: dict):
    key = (base, identifier)
    values = metadata.get("thinking_values")
    if not isinstance(values, list):
        timestamp, values = _thinking.get(key, (0, None))
        if time.monotonic() - timestamp >= 3600 or values is None:
            values = []
            try:
                response = await client.post(base + "/api/show", json={"model": identifier}, timeout=10)
                if response.is_success:
                    thinking = response.json().get("thinking") or {}
                    advertised = thinking.get("values") or []
                    values = [v for v in advertised if isinstance(v, (bool, str))] if isinstance(advertised, list) else []
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                pass
            _thinking[key] = (time.monotonic(), values)
            if len(_thinking) > 128:
                _thinking.pop(next(iter(_thinking)))
    if False in values:
        return False
    for disabled in ("none", "off", "disabled"):
        if disabled in values:
            return disabled
    for level in (["high", "medium", "low"] if quality == "high" else ["low", "medium", "high"]):
        if level in values:
            return level
    if values == [True]:
        return True  # Mandatory thinking; do not send an unsupported false value.
    if values:
        return values[0]  # Unknown named levels: send an advertised value only.
    return "low" if "gpt-oss" in identifier.lower() else False


def apply_cached_options(payload: dict, key: tuple) -> dict:
    result = copy.deepcopy(payload)
    for field in cached_rejections(key):
        if "." in field:
            parent, child = field.split(".", 1)
            if isinstance(result.get(parent), dict):
                result[parent].pop(child, None)
                if not result[parent]:
                    result.pop(parent)
        else:
            result.pop(field, None)
    return result
