"""Explicit, user-owned +8000-token continuation jobs."""
import uuid
from typing import Literal
from datetime import datetime, timedelta, timezone

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.routers.coach import _privacy, _run_payload
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import AiRun, BackgroundJob, Message
from pengucoach.db.session import get_db
from pengucoach.llm.service import resolve_model
from worker.celery_app import app as celery_app

router = APIRouter(prefix='/coach', tags=['AI continuation'])


class ContinueIn(BaseModel):
    revision: int = Field(ge=0)
    additional_tokens: Literal[0, 8000] = 8000


async def owned_run(db, user, identifier, lock=False):
    query = select(AiRun).where(AiRun.id == identifier, AiRun.user_id == user.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = await db.scalar(query)
    if not run:
        raise HTTPException(404, 'AI_RUN_NOT_FOUND')
    return run


@router.get('/runs/{run_id}')
async def get_run(run_id: uuid.UUID, user=Depends(safety_confirmed_user), db=Depends(get_db)):
    return _run_payload(await owned_run(db, user, run_id))


@router.post('/runs/{run_id}/continue')
async def continue_run(run_id: uuid.UUID, payload: ContinueIn, user=Depends(safety_confirmed_user), db=Depends(get_db)):
    run = await owned_run(db, user, run_id)
    previous = run.metadata_json or {}
    planned = previous.get('planned_session')
    if planned:
        from apps.api.routers.execution import scope
        from pengucoach.coach.execution import review_session
        plan, schedule = await scope(db, user, uuid.UUID(planned['plan_id']))
        current = await review_session(db, user, plan, schedule, planned['session_id'])
        if current.get('fingerprint') != previous.get('review_fingerprint'):
            raise HTTPException(409, 'REVIEW_CHANGED_RELOAD')
    run = await owned_run(db, user, run_id, True)
    meta = dict(run.metadata_json or {})
    state = meta.get('continuation') or {}
    format_retry = run.task_type == 'training_plan' and state.get('reason') == 'invalid_plan'
    if payload.additional_tokens != (0 if format_retry else 8000):
        raise HTTPException(409, 'AI_RUN_CHANGED_RELOAD')
    claim = meta.get('_continuation_job')
    if claim:
        result = AsyncResult(claim['task_id'], app=celery_app)
        created = datetime.fromisoformat(claim['created_at'])
        if not result.ready() and result.state not in {'FAILURE', 'REVOKED'} and created > datetime.now(timezone.utc)-timedelta(hours=12):
            return {'task_id': claim['task_id'], 'already_running': True}
    if state.get('revision', 0) != payload.revision:
        raise HTTPException(409, 'AI_RUN_CHANGED_RELOAD')
    if not state.get('available') or not (meta.get('_resume') or meta.get('_plan_state')):
        raise HTTPException(409, 'AI_RUN_NOT_CONTINUABLE')
    _, local_only = await _privacy(db, user)
    if run.model_id is None:
        raise HTTPException(409, 'NO_ELIGIBLE_LLM_MODEL_CONFIGURED')
    selected = await resolve_model(db, run.task_type, local_only=local_only, model_id=run.model_id)
    if not selected:
        raise HTTPException(409, 'NO_ELIGIBLE_LLM_MODEL_CONFIGURED')
    if meta.get('assistant_message_id'):
        target = await db.get(Message, uuid.UUID(meta['assistant_message_id']))
        latest = await db.scalar(select(Message).where(Message.conversation_id == uuid.UUID(meta['conversation_id']))
            .order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
        if not target or not latest or latest.id != target.id:
            raise HTTPException(409, 'CONVERSATION_CHANGED_RELOAD')
    maximum = min(65536, (selected[1].metadata_json or {}).get('provider_max_output_tokens') or 65536)
    if not format_retry and (not run.content or run.task_type == 'training_plan') and (run.max_output_tokens or 0) >= maximum:
        raise HTTPException(409, 'CONTINUATION_MODEL_LIMIT')
    job_id = str(uuid.uuid4())
    meta['continuation'] = {**state, 'revision': payload.revision+1}
    meta['_continuation_job'] = {'task_id': job_id, 'created_at': datetime.now(timezone.utc).isoformat()}
    run.metadata_json = meta
    db.add(BackgroundJob(id=uuid.UUID(job_id), user_id=user.id, job_type='ai_continuation',
        payload={'run_id': str(run.id), 'revision': payload.revision+1, 'additional_tokens': payload.additional_tokens}))
    await db.commit()
    from worker.tasks.continuation import continue_ai
    try:
        continue_ai.apply_async(args=[str(user.id), {'run_id': str(run_id), 'revision': payload.revision+1}], task_id=job_id)
    except Exception:
        run = await owned_run(db, user, run_id, True)
        current = dict(run.metadata_json or {})
        if (current.get('_continuation_job') or {}).get('task_id') == job_id:
            current.pop('_continuation_job', None)
            run.metadata_json = current
        row = await db.get(BackgroundJob, uuid.UUID(job_id))
        row.status = 'failed'
        await db.commit()
        raise HTTPException(503, 'AI_QUEUE_UNAVAILABLE') from None
    return {'task_id': job_id, 'revision': payload.revision+1}
