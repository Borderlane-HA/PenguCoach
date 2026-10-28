"""Refresh derived local reviews without making an AI call."""
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from worker.celery_app import app


async def refresh_user(db, user):
    from pengucoach.db.models import PlanSchedule, AiRun
    from pengucoach.coach.plan_evolution import comparison_data
    from pengucoach.coach.execution import review_session
    schedules = (await db.scalars(select(PlanSchedule).where(PlanSchedule.user_id == user.id)
        .order_by(PlanSchedule.updated_at.desc()).limit(10))).all()
    count = 0
    for schedule in schedules:
        run = await db.get(AiRun, schedule.plan_run_id)
        if not run or run.user_id != user.id or not (run.metadata_json or {}).get('structured_plan'):
            continue
        comparison = await comparison_data(db, user, run, schedule)
        cutoff = (datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat()
        for session in comparison['items']:
            if session.get('activity_id') and session['date'] >= cutoff:
                await review_session(db, user, run, schedule, session['id'], compared=comparison)
                count += 1
    return count


@app.task(name='worker.tasks.execution.refresh_reviews')
def refresh_reviews(user_id=None):
    from pengucoach.common import maintenance_mode
    if user_id is None and maintenance_mode.active():
        return {'skipped': 'maintenance'}
    async def work():
        import uuid
        from pengucoach.db.session import SessionLocal
        from pengucoach.db.models import User, PlanSchedule
        async with SessionLocal() as db:
            ids = [uuid.UUID(user_id)] if user_id else (await db.scalars(select(PlanSchedule.user_id).distinct())).all()
            count = 0
            for identifier in ids:
                user = await db.get(User, identifier)
                if user:
                    count += await refresh_user(db, user)
            return {'reviewed': count}
    return asyncio.run(work())
