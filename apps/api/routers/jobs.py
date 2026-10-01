from celery.result import AsyncResult
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pengucoach.db.session import get_db

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User, BackgroundJob
from pengucoach.llm.job_control import request_cancel
from worker.celery_app import app

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/active")
async def active_job(
    job_type: str = Query(min_length=1, max_length=64),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the newest still-running tracked job for this user and type.

    Celery results can expire and then look like PENDING again, so only recent
    database-backed jobs are considered. This endpoint lets browser sessions
    recover a long-running plan without relying on localStorage alone.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    rows = (
        await db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.user_id == user.id,
                BackgroundJob.job_type == job_type,
                BackgroundJob.created_at >= cutoff,
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(20)
        )
    ).all()
    for row in rows:
        if row.status in {"cancel_requested", "cancelled", "failed", "finished"}:
            continue
        result = AsyncResult(str(row.id), app=app)
        if result.ready() or result.state in {"FAILURE", "REVOKED"}:
            continue
        progress = result.info if result.state == "PROGRESS" and isinstance(result.info, dict) else None
        payload = row.payload if isinstance(row.payload, dict) else {}
        return {
            "active": True,
            "task_id": str(row.id),
            "state": result.state,
            "progress": progress,
            "summary": {
                "goal_type": payload.get("goal_type"),
                "goal_text": payload.get("goal_text"),
                "weeks": payload.get("weeks"),
                "days_per_week": payload.get("days_per_week"),
                "session_minutes": payload.get("session_minutes"),
                "start_date": payload.get("start_date"),
                "model_id": payload.get("model_id"),
            },
            "created_at": row.created_at,
        }
    return {"active": False, "task_id": None, "state": None, "progress": None, "summary": None}


@router.get("/{task_id}")
async def job_status(task_id: str, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    await _check_owner(task_id, user, db)
    result = AsyncResult(task_id, app=app)
    value = None
    progress = None
    error = None
    if result.successful() and isinstance(result.result, (dict, list, str, int, float, bool, type(None))):
        value = result.result
    elif result.state == "PROGRESS" and isinstance(result.info, dict):
        progress = result.info
    elif result.failed():
        error = f"{type(result.result).__name__}: {result.result}" if result.result else "AI_JOB_FAILED"
    elif result.state == "REVOKED":
        error = "AI_JOB_CANCELLED"
    return {
        "id": task_id,
        "state": result.state,
        "ready": result.ready(),
        "successful": result.successful(),
        "result": value,
        "progress": progress,
        "error": error,
    }


@router.post("/{task_id}/cancel")
async def cancel_job(task_id: str, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    """Request cancellation without killing the worker process.

    Running Ollama jobs notice the Redis flag while streaming and stop within a
    short interval. Queued tasks are also revoked so they never start.
    """
    await _check_owner(task_id, user, db)
    request_cancel(task_id)
    app.control.revoke(task_id, terminate=False)
    try:
        identifier = uuid.UUID(task_id)
        row = await db.get(BackgroundJob, identifier)
        if row and row.user_id == user.id:
            row.status = "cancel_requested"
            row.finished_at = datetime.now(timezone.utc)
            await db.commit()
    except ValueError:
        pass
    return {"task_id": task_id, "cancel_requested": True}


async def _check_owner(task_id, user, db):
    try:
        identifier = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(404, "JOB_NOT_FOUND")
    row = await db.get(BackgroundJob, identifier)
    if row and row.user_id and row.user_id != user.id:
        raise HTTPException(404, "JOB_NOT_FOUND")
