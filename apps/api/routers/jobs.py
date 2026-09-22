from celery.result import AsyncResult
from fastapi import APIRouter, Depends

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User
from pengucoach.llm.job_control import request_cancel
from worker.celery_app import app

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{task_id}")
async def job_status(task_id: str, _: User = Depends(safety_confirmed_user)):
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
async def cancel_job(task_id: str, _: User = Depends(safety_confirmed_user)):
    """Request cancellation without killing the worker process.

    Running Ollama jobs notice the Redis flag while streaming and stop within a
    short interval. Queued tasks are also revoked so they never start.
    """
    request_cancel(task_id)
    app.control.revoke(task_id, terminate=False)
    return {"task_id": task_id, "cancel_requested": True}
