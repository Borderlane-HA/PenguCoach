from celery.result import AsyncResult
from fastapi import APIRouter, Depends

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User
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
        error = str(result.result)
    return {
        "id": task_id,
        "state": result.state,
        "ready": result.ready(),
        "successful": result.successful(),
        "result": value,
        "progress": progress,
        "error": error,
    }
