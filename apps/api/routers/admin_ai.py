import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import admin_user
from pengucoach.db.models import LlmModel, LlmProvider, LlmRoute, User
from pengucoach.db.session import get_db
from pengucoach.llm.service import test_provider
from pengucoach.security.crypto import SecretBox

router = APIRouter(prefix="/admin/ai", tags=["admin-ai"])


class ProviderIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    provider_type: str = Field(pattern=r"^(ollama|openai|anthropic|openai_compatible)$")
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    is_local: bool = False


class ModelIn(BaseModel):
    provider_id: uuid.UUID
    model_identifier: str
    display_name: str
    context_window: int | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)


class RouteIn(BaseModel):
    primary_model_id: uuid.UUID | None = None
    fallback_model_id: uuid.UUID | None = None


@router.get("/providers")
async def providers(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(LlmProvider).order_by(LlmProvider.name))).all()
    return [{"id": str(x.id), "name": x.name, "provider_type": x.provider_type, "base_url": x.base_url, "enabled": x.enabled, "is_local": x.is_local, "has_secret": bool(x.secret_ciphertext)} for x in rows]


@router.post("/providers")
async def create_provider(payload: ProviderIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = LlmProvider(name=payload.name, provider_type=payload.provider_type, base_url=payload.base_url, enabled=payload.enabled, is_local=payload.is_local or payload.provider_type == "ollama", secret_ciphertext=SecretBox().encrypt(payload.api_key) if payload.api_key else None)
    db.add(row); await db.commit(); return {"id": str(row.id)}


@router.post("/providers/test")
async def provider_test(payload: ProviderIn, _: User = Depends(admin_user)):
    try: return await test_provider(payload.provider_type, payload.base_url, payload.api_key)
    except Exception as exc: raise HTTPException(status_code=400, detail=f"PROVIDER_TEST_FAILED:{type(exc).__name__}") from exc


@router.get("/models")
async def models(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(LlmModel).order_by(LlmModel.display_name))).all()
    return [{"id": str(x.id), "provider_id": str(x.provider_id), "model_identifier": x.model_identifier, "display_name": x.display_name, "enabled": x.enabled, "context_window": x.context_window, "temperature": x.temperature} for x in rows]


@router.post("/models")
async def create_model(payload: ModelIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(LlmProvider, payload.provider_id): raise HTTPException(status_code=404, detail="PROVIDER_NOT_FOUND")
    row = LlmModel(**payload.model_dump()); db.add(row); await db.commit(); return {"id": str(row.id)}


@router.get("/routes")
async def routes(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(LlmRoute))).all(); return [{"task_type": x.task_type, "primary_model_id": str(x.primary_model_id) if x.primary_model_id else None, "fallback_model_id": str(x.fallback_model_id) if x.fallback_model_id else None} for x in rows]


@router.put("/routes/{task_type}")
async def set_route(task_type: str, payload: RouteIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(LlmRoute, task_type)
    if not row: row = LlmRoute(task_type=task_type); db.add(row)
    row.primary_model_id = payload.primary_model_id; row.fallback_model_id = payload.fallback_model_id
    await db.commit(); return {"saved": True}
