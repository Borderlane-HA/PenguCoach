from typing import Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.common.config import settings
from pengucoach.db.models import Activity, GarminConnection, GarminSyncRun, GarminSyncSetting, User
from pengucoach.db.session import get_db
from pengucoach.garmin.auth.service import garmin_auth_service
from pengucoach.garmin.zones import training_zone_snapshot
from worker.celery_app import app
from worker.tasks.garmin_sync import activity_catalog_import, clear_history_import_control, current_history_import_task, force_clear_history_import_state, historical_import, set_history_import_control, sync_user

router = APIRouter(prefix="/garmin", tags=["garmin"])


class GarminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class GarminMfaRequest(BaseModel):
    challenge_id: str
    code: str = Field(min_length=4, max_length=16)


class SyncSettingsRequest(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(default=30, ge=15, le=1440)
    fit_download_enabled: bool = True
    fit_analysis_enabled: bool = True
    historical_days: int = Field(default=365, ge=0, le=9132)
    sync_health: bool = True
    sync_activities: bool = True
    sync_body: bool = True
    sync_training: bool = True
    workout_export_enabled: bool = False


class ImportRequest(BaseModel):
    days: int = Field(default=365, ge=0, le=9132)
    mode: Literal["optimized", "full"] = "optimized"


class ImportControlRequest(BaseModel):
    action: Literal["pause", "cancel"]
    task_id: str | None = Field(default=None, max_length=128)


def _discover_history_task_id(user_id: str) -> str | None:
    """Best-effort fallback for an import started before task-id tracking existed."""
    try:
        inspector = app.control.inspect(timeout=1.0)
        for getter in (inspector.active, inspector.reserved, inspector.scheduled):
            workers = getter() or {}
            for tasks in workers.values():
                for item in tasks or []:
                    request = item.get("request") if isinstance(item, dict) else None
                    candidate = request if isinstance(request, dict) else item
                    if not isinstance(candidate, dict):
                        continue
                    if candidate.get("name") not in {"worker.tasks.garmin_sync.historical_import", "worker.tasks.garmin_sync.activity_catalog_import"}:
                        continue
                    args = candidate.get("args")
                    args_repr = candidate.get("argsrepr")
                    if (isinstance(args, (list, tuple)) and args and str(args[0]) == user_id) or user_id in str(args_repr or args or ""):
                        task_id = candidate.get("id")
                        if task_id:
                            return str(task_id)
    except Exception:
        # Cancellation must still clear stale DB/Redis state even when no worker
        # answers Celery inspection (for example directly after a restart).
        return None
    return None


@router.get("/status")
async def garmin_status(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    sync = await db.get(GarminSyncSetting, user.id)
    activity_count = int((await db.scalar(select(func.count(Activity.id)).where(Activity.user_id == user.id))) or 0)
    last_catalog = await db.scalar(select(GarminSyncRun).where(
        GarminSyncRun.user_id == user.id,
        GarminSyncRun.sync_type.in_(["historical", "activity_catalog"]),
    ).order_by(GarminSyncRun.started_at.desc()).limit(1))
    catalog_meta = None
    if last_catalog and isinstance(last_catalog.domains, dict):
        value = last_catalog.domains.get("activities")
        if isinstance(value, dict):
            catalog_meta = {**value, "status": last_catalog.status, "finished_at": last_catalog.finished_at}
    if not conn:
        return {"connected": False, "status": "disconnected", "read_only": True, "activity_count": activity_count, "activity_catalog": catalog_meta, "settings": {"interval_minutes": settings.garmin_default_interval_minutes}}
    return {"connected": conn.status == "connected", "status": conn.status, "display_name": conn.garmin_display_name, "last_validated_at": conn.last_validated_at, "last_successful_sync_at": conn.last_successful_sync_at, "next_sync_at": conn.next_sync_at, "cooldown_until": conn.cooldown_until, "last_error_code": conn.last_error_code, "read_only": True, "activity_count": activity_count, "activity_catalog": catalog_meta, "settings": {"enabled": sync.enabled, "interval_minutes": sync.interval_minutes, "fit_download_enabled": sync.fit_download_enabled, "fit_analysis_enabled": sync.fit_analysis_enabled, "historical_days": sync.historical_days, "sync_health": sync.sync_health, "sync_activities": sync.sync_activities, "sync_body": sync.sync_body, "sync_training": sync.sync_training, "workout_export_enabled": sync.workout_export_enabled} if sync else None}


@router.post("/auth/start")
async def start_garmin_login(payload: GarminLoginRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    try:
        return await garmin_auth_service.start(db, user, str(payload.email), payload.password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="GARMIN_AUTH_FAILED") from exc


@router.post("/auth/mfa")
async def complete_garmin_mfa(payload: GarminMfaRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    try:
        return await garmin_auth_service.complete_mfa(db, user, payload.challenge_id, payload.code)
    except KeyError as exc:
        raise HTTPException(status_code=410, detail="GARMIN_MFA_CHALLENGE_EXPIRED") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="GARMIN_MFA_FAILED") from exc


@router.post("/disconnect")
async def disconnect(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await garmin_auth_service.disconnect(db, user); return {"disconnected": True, "local_data_preserved": True}


@router.get("/sync/settings")
async def get_sync_settings(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(GarminSyncSetting, user.id)
    if not row:
        row = GarminSyncSetting(user_id=user.id, interval_minutes=settings.garmin_default_interval_minutes); db.add(row); await db.commit()
    return {"enabled": row.enabled, "interval_minutes": row.interval_minutes, "fit_download_enabled": row.fit_download_enabled, "fit_analysis_enabled": row.fit_analysis_enabled, "historical_days": row.historical_days, "sync_health": row.sync_health, "sync_activities": row.sync_activities, "sync_body": row.sync_body, "sync_training": row.sync_training, "workout_export_enabled": row.workout_export_enabled}


@router.put("/sync/settings")
async def put_sync_settings(payload: SyncSettingsRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(GarminSyncSetting, user.id)
    if not row:
        row = GarminSyncSetting(user_id=user.id); db.add(row)
    for field, value in payload.model_dump().items(): setattr(row, field, value)
    await db.commit(); return payload.model_dump()


@router.post("/sync/now")
async def sync_now(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not conn or conn.status != "connected": raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    task = sync_user.apply_async(args=[str(user.id)], queue="garmin")
    return {"queued": True, "task_id": task.id}


@router.post("/import")
async def start_import(payload: ImportRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not conn or conn.status != "connected": raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    clear_history_import_control(str(user.id))
    task = historical_import.apply_async(args=[str(user.id), payload.days, payload.mode], queue="garmin")
    return {"queued": True, "task_id": task.id, "days": payload.days, "mode": payload.mode, "scope": "all" if payload.days == 0 else "days"}


@router.post("/import/activities")
async def start_activity_catalog_import(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not conn or conn.status != "connected":
        raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    clear_history_import_control(str(user.id))
    task = activity_catalog_import.apply_async(args=[str(user.id)], queue="garmin")
    return {"queued": True, "task_id": task.id, "scope": "activities_only"}


@router.post("/import/control")
async def control_import(
    payload: ImportControlRequest,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(user.id)
    set_history_import_control(user_id, payload.action)
    if payload.action == "cancel":
        # Cooperative cancellation is still signalled first, but a history
        # request can be stuck inside an upstream Garmin call. Revoke the exact
        # Celery task as a hard fallback and clear the lock that a terminated
        # child process cannot release in its finally block.
        task_id = payload.task_id or current_history_import_task(user_id) or _discover_history_task_id(user_id)
        if task_id:
            app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        rows = (await db.scalars(select(GarminSyncRun).where(
            GarminSyncRun.user_id == user.id,
            GarminSyncRun.sync_type.in_(["historical", "activity_catalog"]),
            GarminSyncRun.status == "running",
        ).order_by(GarminSyncRun.started_at.desc()).limit(5))).all()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.status = "cancelled"
            row.finished_at = now
            row.error_code = None
        await db.commit()
        force_clear_history_import_state(user_id)
        return {"accepted": True, "action": "cancel", "resume_safe": True, "hard_stop": bool(task_id), "task_id": task_id}
    return {"accepted": True, "action": "pause", "resume_safe": True, "hard_stop": False}


@router.get("/zones")
async def training_zones(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    snapshot = await training_zone_snapshot(db, user.id)
    snapshot["connected"] = bool(conn and conn.status == "connected")
    return snapshot


@router.get("/sync/history")
async def sync_history(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(GarminSyncRun).where(GarminSyncRun.user_id == user.id).order_by(GarminSyncRun.started_at.desc()).limit(50))).all()
    return [{"id": str(x.id), "type": x.sync_type, "started_at": x.started_at, "finished_at": x.finished_at, "status": x.status, "records_read": x.records_read, "records_inserted": x.records_inserted, "error_code": x.error_code} for x in rows]
