"""Plan-to-recording review, local start times and explicit adaptive approval."""
import uuid
from pengucoach.sparkyfitness.activity_time import stored_time_info
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.routers.companion import plan_owned, validate_overrides
from apps.api.routers.plan_evolution import get_schedule, apply_changes
from apps.api.routers.coach import ActivityAnalysisRequest, _run_payload
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.companion import scheduled_sessions
from pengucoach.coach.execution import adaptive_proposal, review_session
from pengucoach.coach.plan_evolution import planned_start, sport_family
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, AiRun, BackgroundJob, PlanActivityMatch, PlanSchedule
from pengucoach.db.session import get_db

router = APIRouter(prefix='/coach', tags=['training execution'])


async def scope(db, user, run_id):
    run = await plan_owned(db, user, run_id)
    schedule = await db.get(PlanSchedule, run_id)
    if not schedule or schedule.user_id != user.id:
        raise HTTPException(409, 'ACTIVATE_PLAN_CALENDAR_FIRST')
    return run, schedule


@router.get('/plans/{run_id}/sessions/{session_id}/review')
async def get_review(run_id: uuid.UUID, session_id: str, offset_s: int | None = Query(None, ge=0, le=7200),
                     user=Depends(safety_confirmed_user), db=Depends(get_db)):
    run, schedule = await scope(db, user, run_id)
    try:
        result = await review_session(db, user, run, schedule, session_id, offset=offset_s)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    result['date'] = user_today(user).isoformat()
    if result.get('analysis_id'):
        result['analysis'] = _run_payload(await db.get(AiRun, uuid.UUID(result['analysis_id'])))
    return result


class StartTimeIn(BaseModel):
    start_time: str | None = Field(None, pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    revision: int = Field(ge=0)


@router.put('/plans/{run_id}/sessions/{session_id}/start-time')
async def save_start_time(run_id: uuid.UUID, session_id: str, payload: StartTimeIn,
                          user=Depends(safety_confirmed_user), db=Depends(get_db)):
    run, schedule = await get_schedule(db, user, run_id, payload.revision, True)
    session = next((s for s in scheduled_sessions(run, schedule) if s['id'] == session_id), None)
    if not session:
        raise HTTPException(404, 'SESSION_NOT_FOUND')
    session['start_time'] = payload.start_time
    if payload.start_time and planned_start(session, user) is None:
        raise HTTPException(422, 'START_TIME_AMBIGUOUS_OR_NONEXISTENT')
    session.pop('date', None)
    schedule.overrides = validate_overrides(run, {**(schedule.overrides or {}), session_id: session})
    # Local matching metadata only; does not reschedule a Garmin workout.
    schedule.revision += 1
    await db.commit()
    return {'saved': True, 'revision': schedule.revision}


@router.get('/plans/{run_id}/sessions/{session_id}/activities')
async def candidates(run_id: uuid.UUID, session_id: str, user=Depends(safety_confirmed_user), db=Depends(get_db)):
    run, schedule = await scope(db, user, run_id)
    session = next((s for s in scheduled_sessions(run, schedule) if s['id'] == session_id), None)
    if not session:
        raise HTTPException(404, 'SESSION_NOT_FOUND')
    day = date.fromisoformat(session['date'])
    claimed = (await db.scalars(select(PlanActivityMatch).where(PlanActivityMatch.user_id == user.id, PlanActivityMatch.activity_id.is_not(None)))).all()
    reserved = {m.activity_id for m in claimed if m.plan_run_id != run_id or m.session_id != session_id}
    rows = (await db.scalars(select(Activity).where(Activity.user_id == user.id,
        Activity.started_at >= day_start(day-timedelta(days=7), user),
        Activity.started_at < day_start(day+timedelta(days=8), user),
        Activity.started_at <= datetime.now(timezone.utc)).order_by(Activity.started_at.desc()))).all()
    return {'items': [{'id': str(a.id), 'name': a.name, 'started_at': a.started_at, 'time_precision': stored_time_info(a).get('precision'), 'activity_date': stored_time_info(a).get('local_date'),
            'minutes': round(a.duration_seconds/60, 1) if a.duration_seconds is not None else None}
        for a in rows if a.id not in reserved and sport_family(a.sport_type) == sport_family(session['sport'])]}


class SessionAnalysisIn(BaseModel):
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(None, ge=128, le=65536)
    context_window_tokens: int | None = Field(None, ge=2048, le=1048576)


@router.post('/plans/{run_id}/sessions/{session_id}/analysis/jobs')
async def queue_analysis(run_id: uuid.UUID, session_id: str, payload: SessionAnalysisIn,
                         user=Depends(safety_confirmed_user), db=Depends(get_db)):
    run, schedule = await scope(db, user, run_id)
    result = await review_session(db, user, run, schedule, session_id)
    if not result['review']:
        raise HTTPException(409, 'MATCH_ACTIVITY_FIRST')
    from worker.tasks.ai import session_analysis
    body = {**payload.model_dump(mode='json'), 'plan_id': str(run_id), 'session_id': session_id,
            'review_fingerprint': result['fingerprint'], 'locale': user.locale}
    task = session_analysis.delay(str(user.id), body)
    db.add(BackgroundJob(id=uuid.UUID(task.id), user_id=user.id, job_type='session_analysis', payload=body))
    await db.commit()
    return {'task_id': task.id}


class AdaptiveIn(BaseModel):
    revision: int = Field(ge=0)
    apply: bool = False
    review_token: str | None = None
    expected_items: list[dict] | None = Field(None, max_length=1)


@router.post('/plans/{run_id}/sessions/{session_id}/adaptation')
async def adaptation(run_id: uuid.UUID, session_id: str, payload: AdaptiveIn,
                     user=Depends(safety_confirmed_user), db=Depends(get_db)):
    run, schedule = await get_schedule(db, user, run_id, payload.revision)
    result = await adaptive_proposal(db, user, run, schedule, session_id)
    if payload.apply:
        run, schedule = await get_schedule(db, user, run_id, payload.revision, True)
        if not result['items'] or payload.review_token != result.get('review_token') or payload.expected_items != result['items']:
            raise HTTPException(409, 'PROPOSAL_CHANGED_REVIEW_AGAIN')
        await apply_changes(db, user, run, schedule, result['items'], 'execution_adaptation', [result['source_fingerprint']])
    return {**result, 'applied': payload.apply, 'revision': schedule.revision}
