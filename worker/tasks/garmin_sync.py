import asyncio
from datetime import date, timedelta

from celery import shared_task
from redis import Redis
from sqlalchemy import select

from pengucoach.common.config import settings
from pengucoach.db.models import Activity, GarminConnection, GarminSyncSetting, User
from pengucoach.db.session import SessionLocal
from pengucoach.garmin.sync.service import run_incremental_sync, sync_day


def _lock(name: str, timeout: int):
    redis = Redis.from_url(settings.redis_url)
    return redis.lock(name, timeout=timeout, blocking_timeout=0)


async def _sync(user_id: str):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        if not user or not conn or conn.status != "connected":
            return {"status": "not_connected"}
        result = await run_incremental_sync(db, user, conn)
        if result.get("status") == "success":
            setting = await db.get(GarminSyncSetting, user.id)
            if setting and setting.fit_download_enabled:
                pending = (await db.scalars(
                    select(Activity)
                    .where(Activity.user_id == user.id, Activity.fit_status == "pending")
                    .order_by(Activity.started_at.desc())
                    .limit(5)
                )).all()
                from worker.tasks.fit import analyze_fit
                for activity in pending:
                    analyze_fit.apply_async(args=[str(user.id), str(activity.id)], queue="fit")
        return result


@shared_task(name="worker.tasks.garmin_sync.sync_user")
def sync_user(user_id: str):
    lock = _lock(f"pengucoach:garmin-sync:{user_id}", timeout=15 * 60)
    if not lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        return asyncio.run(_sync(user_id))
    finally:
        try:
            lock.release()
        except Exception:
            pass


async def _historical(user_id: str, days: int):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        if not user or not conn or conn.status != "connected":
            return {"status": "not_connected"}
        setting = await db.get(GarminSyncSetting, user.id)
        days = max(1, min(int(days), 3650))
        count = 0
        start = date.today() - timedelta(days=days - 1)
        for offset in range(days):
            day = start + timedelta(days=offset)
            await sync_day(db, user, conn, day, include_activities=True)
            await db.commit()
            count += 1
            # A deliberately conservative pace reduces the chance of SSO/API throttling.
            if count % 5 == 0:
                await asyncio.sleep(2)
        if setting and setting.fit_download_enabled:
            pending = (await db.scalars(
                select(Activity)
                .where(Activity.user_id == user.id, Activity.fit_status == "pending")
                .order_by(Activity.started_at.desc())
                .limit(1000)
            )).all()
            from worker.tasks.fit import analyze_fit
            for index, activity in enumerate(pending):
                analyze_fit.apply_async(args=[str(user.id), str(activity.id)], queue="fit", countdown=index * 3)
        return {"status": "success", "days": count}


@shared_task(name="worker.tasks.garmin_sync.historical_import")
def historical_import(user_id: str, days: int = 365):
    lock = _lock(f"pengucoach:garmin-history:{user_id}", timeout=24 * 60 * 60)
    if not lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        return asyncio.run(_historical(user_id, days))
    finally:
        try:
            lock.release()
        except Exception:
            pass
