import asyncio
import uuid

from celery import shared_task
from garminconnect import GarminConnectTooManyRequestsError
from redis import Redis
from sqlalchemy import select

from pengucoach.common.config import settings
from pengucoach.db.models import Activity, GarminConnection, GarminSyncSetting, User
from pengucoach.db.session import SessionLocal
from pengucoach.fit.service import download_and_analyze_fit


async def _run(user_id: str, activity_id: str):
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        activity = await db.get(Activity, uuid.UUID(activity_id))
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        setting = await db.get(GarminSyncSetting, user.id) if user else None
        if not user or not activity or activity.user_id != user.id or not conn or conn.status != "connected":
            return {"status": "not_available"}
        if activity.fit_status == "parsed":
            return {"status": "already_parsed", "activity_id": str(activity.id)}
        try:
            analyze = setting.fit_analysis_enabled if setting else True
            return await download_and_analyze_fit(db, user, activity, conn, analyze=analyze)
        except GarminConnectTooManyRequestsError:
            # A large historical backfill can legitimately hit Garmin's throttle.
            # Keep the activity queued and let the Celery task retry later instead
            # of turning a temporary rate limit into a permanent failed activity.
            await db.rollback()
            raise
        except Exception as exc:
            activity.fit_status = "failed"
            await db.commit()
            return {"status": "failed", "error": type(exc).__name__}


@shared_task(bind=True, name="worker.tasks.fit.analyze_fit", rate_limit="30/m")
def analyze_fit(self, user_id: str, activity_id: str):
    """Download/analyse one FIT with account-wide pacing and retry protection.

    The broker can safely hold thousands of historical FIT jobs. Workers consume
    them at a controlled rate instead of keeping thousands of ETA/countdown tasks
    in worker memory.
    """
    redis = Redis.from_url(settings.redis_url)
    account_lock = redis.lock(
        f"pengucoach:garmin-account:{user_id}",
        timeout=15 * 60,
        blocking_timeout=0,
    )
    if not account_lock.acquire(blocking=False):
        raise self.retry(countdown=30, max_retries=120)

    activity_lock = redis.lock(
        f"pengucoach:fit:{activity_id}",
        timeout=45 * 60,
        blocking_timeout=0,
    )
    if not activity_lock.acquire(blocking=False):
        try:
            account_lock.release()
        except Exception:
            pass
        return {"status": "already_running", "activity_id": activity_id}

    try:
        try:
            return asyncio.run(_run(user_id, activity_id))
        except GarminConnectTooManyRequestsError as exc:
            retries = int(getattr(self.request, "retries", 0) or 0)
            wait_seconds = min(600, 30 * (2 ** min(retries, 4)))
            raise self.retry(exc=exc, countdown=wait_seconds, max_retries=20)
    finally:
        try:
            activity_lock.release()
        except Exception:
            pass
        try:
            account_lock.release()
        except Exception:
            pass
