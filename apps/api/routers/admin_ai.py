import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import admin_user
from pengucoach.db.models import LlmModel, LlmProvider, LlmRoute, User
from pengucoach.db.session import get_db
from pengucoach.llm.service import TASK_DEFAULTS, task_settings, test_provider
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
    enabled: bool = True


class ModelUpdate(BaseModel):
    model_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    context_window: int | None = Field(default=None, ge=1024, le=4_000_000)
    provider_max_output_tokens: int | None = Field(default=None, ge=128, le=1_000_000)
    temperature: float = Field(default=0.2, ge=0, le=2)
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
        metadata_json={"provider_max_output_tokens": payload.provider_max_output_tokens} if payload.provider_max_output_tokens else {},
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
