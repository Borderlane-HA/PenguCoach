from celery.result import AsyncResult
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pengucoach.db.session import get_db

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User, BackgroundJob
from pengucoach.llm.job_control import request_cancel
from worker.celery_app import app

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
    return {"task_id": task_id, "cancel_requested": True}


async def _check_owner(task_id, user, db):
    try:
        identifier = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(404, "JOB_NOT_FOUND")
    row = await db.get(BackgroundJob, identifier)
    if row and row.user_id and row.user_id != user.id:
        raise HTTPException(404, "JOB_NOT_FOUND")
