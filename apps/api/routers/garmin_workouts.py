from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import AiRun, GarminConnection, GarminExerciseMapping, GarminSyncSetting, GarminWorkoutExport, User
from pengucoach.db.session import get_db
from pengucoach.garmin.gateway.workouts import (
    catalog_exercise_by_name,
    normalize_exercise_name,
    search_exercise_catalog,
    session_exportability,
    strength_exercise_validation,
    supported_workout_sports,
)
from pengucoach.training_plan.calendar import apply_session_overrides, scheduled_date, select_session_rows
from pengucoach.training_plan.structured import TrainingPlanDocument, TrainingSession
from worker.tasks.garmin_workouts import delete_plan, export_plan

router = APIRouter(prefix="/garmin/workout-export", tags=["garmin-workout-export"])


class WorkoutExportRequest(BaseModel):
    plan_run_id: uuid.UUID
    start_date: date
    session_ids: list[str] | None = Field(default=None, max_length=168)
    session_overrides: dict[str, TrainingSession] = Field(default_factory=dict, max_length=168)




class ExerciseMappingRequest(BaseModel):
    source_name: str = Field(min_length=1, max_length=160)
    garmin_name: str = Field(min_length=1, max_length=180)


def _mapping_payload(row: GarminExerciseMapping) -> dict[str, str]:
    return {
        "source_name": row.source_name,
        "source_name_normalized": row.source_name_normalized,
        "display_name": row.garmin_display_name,
        "category": row.garmin_category,
        "exercise": row.garmin_exercise,
    }


async def _load_exercise_mappings(db: AsyncSession, user_id: uuid.UUID) -> dict[str, dict[str, str]]:
    rows = (await db.scalars(select(GarminExerciseMapping).where(GarminExerciseMapping.user_id == user_id))).all()
    return {row.source_name_normalized: _mapping_payload(row) for row in rows}


@router.get("/exercise-catalog")
async def exercise_catalog(
    query: str = Query(default="", max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(safety_confirmed_user),
):
    del user  # authentication is intentional even though the catalogue is local/static
    return {"query": query, "items": search_exercise_catalog(query, limit=limit)}


@router.get("/exercise-mappings")
async def exercise_mappings(
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.scalars(select(GarminExerciseMapping).where(
        GarminExerciseMapping.user_id == user.id
    ).order_by(GarminExerciseMapping.source_name))).all()
    return {"items": [_mapping_payload(row) for row in rows]}


@router.put("/exercise-mappings")
async def save_exercise_mapping(
    payload: ExerciseMappingRequest,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    source_key = normalize_exercise_name(payload.source_name)
    if not source_key:
        raise HTTPException(status_code=422, detail="GARMIN_EXERCISE_SOURCE_NAME_INVALID")
    garmin = catalog_exercise_by_name(payload.garmin_name)
    if not garmin:
        raise HTTPException(status_code=422, detail="GARMIN_EXERCISE_CATALOG_ENTRY_INVALID")
    row = await db.scalar(select(GarminExerciseMapping).where(
        GarminExerciseMapping.user_id == user.id,
        GarminExerciseMapping.source_name_normalized == source_key,
    ))
    if not row:
        row = GarminExerciseMapping(
            user_id=user.id,
            source_name=payload.source_name.strip(),
            source_name_normalized=source_key,
            garmin_display_name=garmin["name"],
            garmin_category=garmin["category"],
            garmin_exercise=garmin["exercise"],
        )
        db.add(row)
    else:
        row.source_name = payload.source_name.strip()
        row.garmin_display_name = garmin["name"]
        row.garmin_category = garmin["category"]
        row.garmin_exercise = garmin["exercise"]
    await db.commit()
    await db.refresh(row)
    return _mapping_payload(row)


@router.delete("/exercise-mappings")
async def delete_exercise_mapping(
    source_name: str = Query(min_length=1, max_length=160),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    source_key = normalize_exercise_name(source_name)
    row = await db.scalar(select(GarminExerciseMapping).where(
        GarminExerciseMapping.user_id == user.id,
        GarminExerciseMapping.source_name_normalized == source_key,
    ))
    if row:
        await db.delete(row)
        await db.commit()
    return {"deleted": bool(row), "source_name": source_name}


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
    try:
        calendar_sessions = apply_session_overrides(list(plan.sessions), payload.session_overrides, max_week=plan.weeks)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sessions = select_session_rows(calendar_sessions, payload.session_ids)
    if payload.session_ids is not None and len({x.id for x in sessions}) != len(set(payload.session_ids)):
        raise HTTPException(status_code=422, detail="UNKNOWN_TRAINING_SESSION")

    exports = (await db.scalars(select(GarminWorkoutExport).where(
        GarminWorkoutExport.user_id == user.id,
        GarminWorkoutExport.plan_run_id == run.id,
    ))).all()
    existing = {(item.session_id, item.scheduled_date): item for item in exports}
    exercise_map = await _load_exercise_mappings(db, user.id)
    items = []
    for session in sessions:
        target_date = scheduled_date(payload.start_date, session)
        exportable, reason = session_exportability(session)
        prior = existing.get((session.id, target_date))
        strength_validation = strength_exercise_validation(session, exercise_map) if session.sport == "strength" else []
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
            "edited": session.id in payload.session_overrides,
            "strength_validation": strength_validation,
            "generic_fallback_count": sum(1 for item in strength_validation if item["generic_fallback"]),
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
    try:
        calendar_sessions = apply_session_overrides(list(plan.sessions), payload.session_overrides, max_week=plan.weeks)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sessions = select_session_rows(calendar_sessions, payload.session_ids)
    if payload.session_ids is not None and len({x.id for x in sessions}) != len(set(payload.session_ids)):
        raise HTTPException(status_code=422, detail="UNKNOWN_TRAINING_SESSION")
    if not sessions:
        raise HTTPException(status_code=422, detail="NO_TRAINING_SESSIONS_SELECTED")
    task = export_plan.apply_async(args=[str(user.id), payload.model_dump(mode="json")], queue="garmin")
    return {"task_id": task.id, "status": "queued", "sessions": len(sessions)}


@router.post("/delete-plan/{plan_run_id}/jobs")
async def queue_plan_garmin_cleanup(
    plan_run_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AiRun, plan_run_id)
    if not run or run.user_id != user.id or run.task_type != "training_plan":
        raise HTTPException(status_code=404, detail="TRAINING_PLAN_NOT_FOUND")
    exports = (await db.scalars(select(GarminWorkoutExport).where(
        GarminWorkoutExport.user_id == user.id,
        GarminWorkoutExport.plan_run_id == plan_run_id,
    ))).all()
    needs_remote = any(row.workout_id or row.scheduled_workout_id for row in exports)
    if needs_remote:
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
        if not conn or conn.status != "connected" or not conn.token_ciphertext:
            raise HTTPException(status_code=409, detail="GARMIN_NOT_CONNECTED")
    task = delete_plan.apply_async(args=[str(user.id), str(plan_run_id)], queue="garmin")
    return {"task_id": task.id, "status": "queued", "garmin_entries": sum(1 for row in exports if row.workout_id or row.scheduled_workout_id)}
