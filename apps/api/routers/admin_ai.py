import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import admin_user
from pengucoach.db.models import AiRun, LlmModel, LlmProvider, LlmRoute, User
from pengucoach.db.session import get_db
from pengucoach.llm.service import TASK_DEFAULTS, task_settings, test_provider
from pengucoach.llm.usage import calculate_cost_eur, model_pricing, period_start
from pengucoach.security.crypto import SecretBox

router = APIRouter(prefix="/admin/ai", tags=["admin-ai"])


class ProviderIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    provider_type: str = Field(pattern=r"^(ollama|openai|anthropic|openai_compatible|ionos|gemini|xai)$")
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    is_local: bool = False


class ProviderUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    is_local: bool = False


class ModelIn(BaseModel):
    provider_id: uuid.UUID
    model_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    context_window: int | None = Field(default=None, ge=1024, le=4_000_000)
    provider_max_output_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    input_cost_per_million_eur: float | None = Field(default=None, ge=0, le=100000)
    output_cost_per_million_eur: float | None = Field(default=None, ge=0, le=100000)
    enabled: bool = True


class ModelUpdate(BaseModel):
    model_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    context_window: int | None = Field(default=None, ge=1024, le=4_000_000)
    provider_max_output_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    input_cost_per_million_eur: float | None = Field(default=None, ge=0, le=100000)
    output_cost_per_million_eur: float | None = Field(default=None, ge=0, le=100000)
    enabled: bool = True


class RouteIn(BaseModel):
    primary_model_id: uuid.UUID | None = None
    fallback_model_id: uuid.UUID | None = None
    max_output_tokens: int = Field(default=3500, ge=128, le=65536)
    context_window_tokens: int = Field(default=8192, ge=2048, le=1_048_576)
    max_context_chars: int = Field(default=32000, ge=4000, le=4_000_000)
    default_prompt_de: str | None = Field(default=None, max_length=16000)
    default_prompt_en: str | None = Field(default=None, max_length=16000)
    default_prompt: str | None = Field(default=None, max_length=16000)
    enabled: bool = True


def _model_payload(x: LlmModel, provider: LlmProvider | None) -> dict:
    meta = x.metadata_json if isinstance(x.metadata_json, dict) else {}
    return {
        "id": str(x.id),
        "provider_id": str(x.provider_id),
        "provider_name": provider.name if provider else None,
        "provider_type": provider.provider_type if provider else None,
        "local": provider.is_local if provider else None,
        "model_identifier": x.model_identifier,
        "display_name": x.display_name,
        "enabled": x.enabled,
        "context_window": x.context_window,
        "provider_max_output_tokens": meta.get("provider_max_output_tokens"),
        "input_cost_per_million_eur": model_pricing(meta)["input_eur_per_million"],
        "output_cost_per_million_eur": model_pricing(meta)["output_eur_per_million"],
        "temperature": x.temperature,
    }


@router.get("/providers")
async def providers(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(LlmProvider).order_by(LlmProvider.name))).all()
    return [{
        "id": str(x.id), "name": x.name, "provider_type": x.provider_type, "base_url": x.base_url,
        "enabled": x.enabled, "is_local": x.is_local, "has_secret": bool(x.secret_ciphertext)
    } for x in rows]


@router.post("/providers")
async def create_provider(payload: ProviderIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = LlmProvider(
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        enabled=payload.enabled,
        is_local=payload.is_local or payload.provider_type == "ollama",
        secret_ciphertext=SecretBox().encrypt(payload.api_key) if payload.api_key else None,
    )
    db.add(row)
    await db.commit()
    return {"id": str(row.id)}


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: uuid.UUID, payload: ProviderUpdate, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(LlmProvider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="PROVIDER_NOT_FOUND")
    row.name = payload.name
    row.base_url = payload.base_url
    row.enabled = payload.enabled
    row.is_local = payload.is_local or row.provider_type == "ollama"
    if payload.api_key:
        row.secret_ciphertext = SecretBox().encrypt(payload.api_key)
    await db.commit()
    return {"saved": True}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: uuid.UUID, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(LlmProvider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="PROVIDER_NOT_FOUND")
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.post("/providers/test")
async def provider_test(payload: ProviderIn, _: User = Depends(admin_user)):
    try:
        return await test_provider(payload.provider_type, payload.base_url, payload.api_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PROVIDER_TEST_FAILED:{type(exc).__name__}") from exc




@router.post("/providers/{provider_id}/discover")
async def discover_provider_models(provider_id: uuid.UUID, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(LlmProvider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="PROVIDER_NOT_FOUND")
    secret = SecretBox().decrypt(row.secret_ciphertext) if row.secret_ciphertext else None
    try:
        return await test_provider(row.provider_type, row.base_url, secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PROVIDER_DISCOVERY_FAILED:{type(exc).__name__}") from exc


@router.get("/models")
async def models(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(LlmModel).order_by(LlmModel.display_name))).all()
    out = []
    for x in rows:
        provider = await db.get(LlmProvider, x.provider_id)
        out.append(_model_payload(x, provider))
    return out


@router.post("/models")
async def create_model(payload: ModelIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(LlmProvider, payload.provider_id):
        raise HTTPException(status_code=404, detail="PROVIDER_NOT_FOUND")
    existing = await db.scalar(select(LlmModel).where(
        LlmModel.provider_id == payload.provider_id,
        LlmModel.model_identifier == payload.model_identifier,
    ))
    if existing:
        return {"id": str(existing.id), "existing": True}
    row = LlmModel(
        provider_id=payload.provider_id,
        model_identifier=payload.model_identifier,
        display_name=payload.display_name,
        enabled=payload.enabled,
        context_window=payload.context_window,
        temperature=payload.temperature,
        metadata_json={
            **({"provider_max_output_tokens": payload.provider_max_output_tokens} if payload.provider_max_output_tokens else {}),
            **({"input_cost_per_million_eur": payload.input_cost_per_million_eur} if payload.input_cost_per_million_eur is not None else {}),
            **({"output_cost_per_million_eur": payload.output_cost_per_million_eur} if payload.output_cost_per_million_eur is not None else {}),
        },
    )
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "existing": False}


@router.put("/models/{model_id}")
async def update_model(model_id: uuid.UUID, payload: ModelUpdate, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(LlmModel, model_id)
    if not row:
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
    duplicate = await db.scalar(select(LlmModel).where(
        LlmModel.provider_id == row.provider_id,
        LlmModel.model_identifier == payload.model_identifier,
        LlmModel.id != row.id,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="MODEL_IDENTIFIER_ALREADY_EXISTS")
    row.model_identifier = payload.model_identifier
    row.display_name = payload.display_name
    row.enabled = payload.enabled
    row.context_window = payload.context_window
    row.temperature = payload.temperature
    meta = dict(row.metadata_json or {})
    if payload.provider_max_output_tokens:
        meta["provider_max_output_tokens"] = payload.provider_max_output_tokens
    else:
        meta.pop("provider_max_output_tokens", None)
    for key, value in (
        ("input_cost_per_million_eur", payload.input_cost_per_million_eur),
        ("output_cost_per_million_eur", payload.output_cost_per_million_eur),
    ):
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    row.metadata_json = meta
    await db.commit()
    return {"saved": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: uuid.UUID, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(LlmModel, model_id)
    if not row:
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
    await db.delete(row)
    await db.commit()
    return {"deleted": True}



def _usage_aggregate(rows: list[AiRun]) -> dict:
    total = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_eur": 0.0, "priced_requests": 0, "unpriced_requests": 0, "elapsed_seconds": 0.0, "timed_requests": 0, "timed_output_tokens": 0}
    models: dict[str, dict] = {}
    tasks: dict[str, dict] = {}
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        cost = meta.get("cost_eur")
        if cost is None:
            pricing = meta.get("pricing") if isinstance(meta.get("pricing"), dict) else None
            cost = calculate_cost_eur(usage, pricing)
        cost_value = float(cost) if cost is not None else None
        elapsed_raw = meta.get("elapsed_seconds")
        elapsed_value = float(elapsed_raw) if isinstance(elapsed_raw, (int, float)) and float(elapsed_raw) >= 0 else None
        total["requests"] += 1
        total["input_tokens"] += input_tokens
        total["output_tokens"] += output_tokens
        total["total_tokens"] += total_tokens
        if cost_value is None:
            total["unpriced_requests"] += 1
        else:
            total["priced_requests"] += 1
            total["cost_eur"] += cost_value
        if elapsed_value is not None:
            total["elapsed_seconds"] += elapsed_value
            total["timed_requests"] += 1
            total["timed_output_tokens"] += output_tokens
        model_key = str(row.model_id) if row.model_id else f"legacy:{row.provider_name}:{row.model_name}"
        model = models.setdefault(model_key, {
            "model_id": str(row.model_id) if row.model_id else None,
            "model": row.model_name or "Unknown",
            "provider": row.provider_name or "Unknown",
            "requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "cost_eur": 0.0, "priced_requests": 0, "unpriced_requests": 0, "elapsed_seconds": 0.0, "timed_requests": 0, "timed_output_tokens": 0,
        })
        task = tasks.setdefault(row.task_type, {
            "task_type": row.task_type, "requests": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "cost_eur": 0.0, "priced_requests": 0, "unpriced_requests": 0, "elapsed_seconds": 0.0, "timed_requests": 0, "timed_output_tokens": 0,
        })
        for target in (model, task):
            target["requests"] += 1
            target["input_tokens"] += input_tokens
            target["output_tokens"] += output_tokens
            target["total_tokens"] += total_tokens
            if cost_value is None:
                target["unpriced_requests"] += 1
            else:
                target["priced_requests"] += 1
                target["cost_eur"] += cost_value
            if elapsed_value is not None:
                target["elapsed_seconds"] += elapsed_value
                target["timed_requests"] += 1
                target["timed_output_tokens"] += output_tokens
    def finalize(group: dict) -> None:
        group["cost_eur"] = round(group["cost_eur"], 8)
        requests = int(group.get("requests") or 0)
        timed = int(group.get("timed_requests") or 0)
        elapsed = float(group.get("elapsed_seconds") or 0.0)
        group["avg_tokens_per_request"] = round(float(group.get("total_tokens") or 0) / requests, 1) if requests else 0.0
        group["avg_cost_per_request_eur"] = round(float(group.get("cost_eur") or 0.0) / int(group.get("priced_requests") or 1), 8) if group.get("priced_requests") else None
        group["avg_output_tokens_per_second"] = round(float(group.get("timed_output_tokens") or 0) / elapsed, 2) if timed and elapsed > 0 else None
        group["elapsed_seconds"] = round(elapsed, 3)
    finalize(total)
    for group in (*models.values(), *tasks.values()):
        finalize(group)
    return {"totals": total, "models": list(models.values()), "tasks": list(tasks.values())}


@router.get("/usage")
async def usage_stats(
    period: str = "month",
    _: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db),
):
    if period not in {"today", "week", "month", "year", "all"}:
        raise HTTPException(status_code=400, detail="INVALID_USAGE_PERIOD")
    now = datetime.now(timezone.utc)
    query = select(AiRun)
    start = period_start(period, now)
    if start is not None:
        query = query.where(AiRun.created_at >= start)
    rows = (await db.scalars(query.order_by(AiRun.created_at.desc()))).all()

    month_start = period_start("month_current", now)
    month_rows = (await db.scalars(select(AiRun).where(AiRun.created_at >= month_start))).all()
    result = _usage_aggregate(list(rows))
    month_result = _usage_aggregate(list(month_rows))
    result.update({
        "period": period,
        "from": start.isoformat() if start else None,
        "to": now.isoformat(),
        "current_month_cost_eur": month_result["totals"]["cost_eur"],
        "current_month_tokens": month_result["totals"]["total_tokens"],
    })
    return result


@router.get("/routes")
async def routes(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    out = []
    for task_type, defaults in TASK_DEFAULTS.items():
        row = await db.get(LlmRoute, task_type)
        config = await task_settings(db, task_type, "de")
        out.append({
            "task_type": task_type,
            "primary_model_id": str(row.primary_model_id) if row and row.primary_model_id else None,
            "fallback_model_id": str(row.fallback_model_id) if row and row.fallback_model_id else None,
            "enabled": row.enabled if row else True,
            **config,
            "factory_prompt_de": defaults["default_prompt_de"],
            "factory_prompt_en": defaults["default_prompt_en"],
        })
    return out


@router.put("/routes/{task_type}")
async def set_route(task_type: str, payload: RouteIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    if task_type not in TASK_DEFAULTS:
        raise HTTPException(status_code=400, detail="UNKNOWN_TASK_TYPE")
    for model_id in (payload.primary_model_id, payload.fallback_model_id):
        if model_id and not await db.get(LlmModel, model_id):
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")
    row = await db.get(LlmRoute, task_type)
    if not row:
        row = LlmRoute(task_type=task_type)
        db.add(row)
    row.primary_model_id = payload.primary_model_id
    row.fallback_model_id = payload.fallback_model_id
    row.enabled = payload.enabled
    defaults = TASK_DEFAULTS[task_type]
    legacy = (payload.default_prompt or "").strip()
    prompt_de = (payload.default_prompt_de or legacy or defaults["default_prompt_de"]).strip()
    prompt_en = (payload.default_prompt_en or legacy or defaults["default_prompt_en"]).strip()
    row.settings = {
        "max_output_tokens": payload.max_output_tokens,
        "context_window_tokens": payload.context_window_tokens,
        "max_context_chars": payload.max_context_chars,
        "default_prompt_de": prompt_de,
        "default_prompt_en": prompt_en,
    }
    await db.commit()
    return {"saved": True}
