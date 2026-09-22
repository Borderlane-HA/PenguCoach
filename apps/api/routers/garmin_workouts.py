from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import AiRun, GarminConnection, GarminSyncSetting, GarminWorkoutExport, User
from pengucoach.db.session import get_db
from pengucoach.garmin.gateway.workouts import session_exportability, supported_workout_sports
from pengucoach.training_plan.calendar import scheduled_date, selected_sessions
from pengucoach.training_plan.structured import TrainingPlanDocument
from worker.tasks.garmin_workouts import export_plan

router = APIRouter(prefix="/garmin/workout-export", tags=["garmin-workout-export"])


class WorkoutExportRequest(BaseModel):
    plan_run_id: uuid.UUID
    start_date: date
    session_ids: list[str] | None = Field(default=None, max_length=168)


def _validate_start(start_date: date) -> None:
    if start_date.isoweekday() != 1:
        raise HTTPException(status_code=422, detail="PLAN_START_DATE_MUST_BE_MONDAY")


async def _load_plan(db: AsyncSession, user: User, run_id: uuid.UUID) -> tuple[AiRun, TrainingPlanDocument]:
    run = await db.get(AiRun, run_id)
    if not run or run.user_id != user.id or run.task_type != "training_plan":
        raise HTTPException(status_code=404, detail="TRAINING_PLAN_NOT_FOUND")
    raw = (run.metadata_json or {}).get("structured_plan")
    if not raw:
        raise HTTPException(status_code=409, detail="TRAINING_PLAN_NOT_STRUCTURED")
    try:
        return run, TrainingPlanDocument.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="TRAINING_PLAN_STRUCTURE_INVALID") from exc


@router.get("/status")
async def workout_export_status(
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    settings = await db.get(GarminSyncSetting, user.id)
    return {
        "connected": bool(conn and conn.status == "connected" and conn.token_ciphertext),
        "enabled": bool(settings and settings.workout_export_enabled),
        "data_sync_read_only": True,
        "supported_sports": supported_workout_sports(),
    }


@router.post("/preview")
async def preview_workout_export(
    payload: WorkoutExportRequest,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_start(payload.start_date)
    run, plan = await _load_plan(db, user, payload.plan_run_id)
    sessions = selected_sessions(plan, payload.session_ids)
    if payload.session_ids is not None and len({x.id for x in sessions}) != len(set(payload.session_ids)):
        raise HTTPException(status_code=422, detail="UNKNOWN_TRAINING_SESSION")

    exports = (await db.scalars(select(GarminWorkoutExport).where(
        GarminWorkoutExport.user_id == user.id,
        GarminWorkoutExport.plan_run_id == run.id,
    ))).all()
    existing = {(item.session_id, item.scheduled_date): item for item in exports}
    items = []
    for session in sessions:
        target_date = scheduled_date(payload.start_date, session)
        exportable, reason = session_exportability(session)
        prior = existing.get((session.id, target_date))
        items.append({
            "session_id": session.id,
            "week": session.week,
            "day": session.day,
            "date": target_date,
            "name": session.name,
            "sport": session.sport,
            "duration_min": session.duration_min,
            "optional": session.optional,
            "exportable": exportable,
            "reason": reason,
            "export_status": prior.status if prior else None,
            "workout_id": prior.workout_id if prior else None,
            "error": prior.error_message_safe if prior and prior.status == "error" else None,
        })
    return {
        "plan_run_id": str(run.id),
        "title": plan.title,
        "start_date": payload.start_date,
        "total": len(items),
        "exportable": sum(1 for item in items if item["exportable"]),
        "already_exported": sum(1 for item in items if item["export_status"] == "exported"),
        "items": items,
    }


@router.post("/jobs")
async def queue_workout_export(
    payload: WorkoutExportRequest,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_start(payload.start_date)
    settings = await db.get(GarminSyncSetting, user.id)
    if not settings or not settings.workout_export_enabled:
        raise HTTPException(status_code=409, detail="GARMIN_WORKOUT_EXPORT_DISABLED")
    conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
    if not conn or conn.status != "connected" or not conn.token_ciphertext:
        raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    _, plan = await _load_plan(db, user, payload.plan_run_id)
    sessions = selected_sessions(plan, payload.session_ids)
    if payload.session_ids is not None and len({x.id for x in sessions}) != len(set(payload.session_ids)):
        raise HTTPException(status_code=422, detail="UNKNOWN_TRAINING_SESSION")
    if not sessions:
        raise HTTPException(status_code=422, detail="NO_TRAINING_SESSIONS_SELECTED")
    task = export_plan.apply_async(args=[str(user.id), payload.model_dump(mode="json")], queue="garmin")
    return {"task_id": task.id, "status": "queued", "sessions": len(sessions)}
