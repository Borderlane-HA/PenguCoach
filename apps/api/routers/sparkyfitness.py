from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import SourceRecord, SparkyFitnessConnection, User
from pengucoach.db.session import get_db
from pengucoach.security.crypto import SecretBox
from pengucoach.sparkyfitness.client import SparkyFitnessClient, SparkyFitnessError, normalize_base_url
from pengucoach.sparkyfitness.sync import delete_local_sparkyfitness_data
from worker.tasks.sparkyfitness_sync import sync_user as sync_sparkyfitness_user

router = APIRouter(prefix="/sparkyfitness", tags=["sparkyfitness"])


class ConnectRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=2048)
    api_key: str = Field(min_length=8, max_length=4096)
    sync_days: int = Field(default=30, ge=0, le=36525)
    auto_sync_enabled: bool = True
    sync_interval_minutes: int = Field(default=30, ge=15, le=1440)
    sync_sleep: bool = True
    sync_daily_health: bool = True
    sync_activities: bool = True


class SettingsRequest(BaseModel):
    sync_days: int = Field(default=30, ge=0, le=36525)
    auto_sync_enabled: bool = True
    sync_interval_minutes: int = Field(default=30, ge=15, le=1440)
    sync_sleep: bool = True
    sync_daily_health: bool = True
    sync_activities: bool = True


async def _connection(db: AsyncSession, user: User) -> SparkyFitnessConnection | None:
    return await db.scalar(select(SparkyFitnessConnection).where(SparkyFitnessConnection.user_id == user.id))


@router.get("/status")
async def status(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await _connection(db, user)
    counts = dict((await db.execute(select(SourceRecord.domain, func.count(SourceRecord.id)).where(
        SourceRecord.user_id == user.id,
        SourceRecord.source == "sparkyfitness",
    ).group_by(SourceRecord.domain))).all())
    range_rows = (await db.execute(select(
        SourceRecord.domain, func.min(SourceRecord.record_date), func.max(SourceRecord.record_date)
    ).where(
        SourceRecord.user_id == user.id, SourceRecord.source == "sparkyfitness"
    ).group_by(SourceRecord.domain))).all()
    ranges = {domain: {
        "oldest": oldest.isoformat() if oldest else None,
        "newest": newest.isoformat() if newest else None,
    } for domain, oldest, newest in range_rows}
    if not conn:
        return {
            "connected": False,
            "status": "disconnected",
            "read_only": True,
            "counts": counts,
            "ranges": ranges,
            "settings": {"sync_days": 30, "auto_sync_enabled": True, "sync_interval_minutes": 30, "sync_sleep": True, "sync_daily_health": True, "sync_activities": True},
        }
    return {
        "connected": conn.status == "connected",
        "status": conn.status,
        "read_only": True,
        "base_url": conn.base_url,
        "capabilities": conn.capabilities or {},
        "counts": counts,
        "ranges": ranges,
        "last_validated_at": conn.last_validated_at,
        "last_successful_sync_at": conn.last_successful_sync_at,
        "next_sync_at": conn.next_sync_at,
        "last_error_code": conn.last_error_code,
        "last_sync_summary": conn.last_sync_summary or {},
        "settings": {
            "sync_days": conn.sync_days,
            "auto_sync_enabled": conn.auto_sync_enabled,
            "sync_interval_minutes": conn.sync_interval_minutes,
            "sync_sleep": conn.sync_sleep,
            "sync_daily_health": conn.sync_daily_health,
            "sync_activities": conn.sync_activities,
        },
    }


@router.post("/connect")
async def connect(payload: ConnectRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    try:
        base_url = normalize_base_url(payload.base_url)
        client = SparkyFitnessClient(base_url, payload.api_key)
        capabilities = (await client.capabilities()).as_dict()
        if not capabilities.get("identity"):
            raise SparkyFitnessError("SPARKYFITNESS_AUTH_OR_PERMISSION_DENIED")
    except (ValueError, SparkyFitnessError) as exc:
        detail = exc.code if isinstance(exc, SparkyFitnessError) else str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc

    row = await _connection(db, user)
    if not row:
        row = SparkyFitnessConnection(
            user_id=user.id,
            base_url=base_url,
            api_key_ciphertext=SecretBox().encrypt(payload.api_key),
        )
        db.add(row)
    else:
        row.base_url = base_url
        row.api_key_ciphertext = SecretBox().encrypt(payload.api_key)
    row.status = "connected"
    row.sync_days = payload.sync_days
    row.auto_sync_enabled = payload.auto_sync_enabled
    row.sync_interval_minutes = payload.sync_interval_minutes
    row.next_sync_at = datetime.now(timezone.utc) + timedelta(minutes=payload.sync_interval_minutes) if payload.auto_sync_enabled else None
    row.sync_sleep = payload.sync_sleep
    row.sync_daily_health = payload.sync_daily_health
    row.sync_activities = payload.sync_activities
    row.capabilities = capabilities
    row.last_validated_at = datetime.now(timezone.utc)
    row.last_error_code = None
    await db.commit()
    return {"connected": True, "base_url": base_url, "capabilities": capabilities, "read_only": True}


@router.post("/test")
async def test_connection(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await _connection(db, user)
    if not row:
        raise HTTPException(status_code=409, detail="SPARKYFITNESS_NOT_CONNECTED")
    try:
        client = SparkyFitnessClient(row.base_url, SecretBox().decrypt(row.api_key_ciphertext))
        capabilities = (await client.capabilities()).as_dict()
        if not capabilities.get("identity"):
            raise SparkyFitnessError("SPARKYFITNESS_AUTH_OR_PERMISSION_DENIED")
        row.status = "connected"
        row.capabilities = capabilities
        row.last_validated_at = datetime.now(timezone.utc)
        row.last_error_code = None
        await db.commit()
        return {"ok": True, "capabilities": capabilities}
    except Exception as exc:
        row.status = "error"
        row.last_error_code = exc.code if isinstance(exc, SparkyFitnessError) else type(exc).__name__
        row.last_error_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=400, detail=row.last_error_code) from exc


@router.put("/settings")
async def update_settings(payload: SettingsRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await _connection(db, user)
    if not row:
        raise HTTPException(status_code=409, detail="SPARKYFITNESS_NOT_CONNECTED")
    prior_enabled = row.auto_sync_enabled
    prior_interval = row.sync_interval_minutes
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    if not row.auto_sync_enabled:
        row.next_sync_at = None
    elif not prior_enabled or prior_interval != row.sync_interval_minutes or row.next_sync_at is None:
        row.next_sync_at = datetime.now(timezone.utc) + timedelta(minutes=row.sync_interval_minutes)
    await db.commit()
    return payload.model_dump()


@router.post("/sync/now")
async def sync_now(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await _connection(db, user)
    if not row or row.status != "connected":
        raise HTTPException(status_code=409, detail="SPARKYFITNESS_NOT_CONNECTED")
    task = sync_sparkyfitness_user.apply_async(args=[str(user.id)], queue="maintenance")
    return {"queued": True, "task_id": task.id}


@router.post("/disconnect")
async def disconnect(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await _connection(db, user)
    if row:
        await db.delete(row)
        await db.commit()
    return {"disconnected": True, "local_data_preserved": True}


@router.delete("/local-data")
async def delete_local_data(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    """Delete only PenguCoach's locally imported SparkyFitness data.

    The remote SparkyFitness installation is never modified; the connection and
    API key stay configured so the user can immediately run a clean re-sync.
    """
    result = await delete_local_sparkyfitness_data(db, user.id)
    return {"deleted": True, "connection_preserved": True, "remote_untouched": True, **result}
