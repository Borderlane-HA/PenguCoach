import asyncio
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import select

from pengucoach.db.models import GarminConnection, GarminSyncSetting, SparkyFitnessConnection
from pengucoach.db.session import SessionLocal
from worker.tasks.garmin_sync import sync_user as sync_garmin_user
from worker.tasks.sparkyfitness_sync import sync_user as sync_sparkyfitness_user


async def _schedule():
    now = datetime.now(timezone.utc); queued = 0
    async with SessionLocal() as db:
        rows = (await db.execute(select(GarminConnection, GarminSyncSetting).join(GarminSyncSetting, GarminSyncSetting.user_id == GarminConnection.user_id).where(GarminConnection.status == "connected", GarminSyncSetting.enabled.is_(True)))).all()
        for conn, setting in rows:
            if conn.cooldown_until and conn.cooldown_until > now: continue
            if conn.next_sync_at and conn.next_sync_at > now: continue
            # Reserve the slot immediately so the scheduler cannot enqueue duplicates.
            conn.next_sync_at = now + timedelta(minutes=10)
            await db.flush()
            sync_garmin_user.apply_async(args=[str(conn.user_id)], queue="garmin"); queued += 1
        await db.commit()
    return {"queued": queued}


@shared_task(name="worker.tasks.scheduler.schedule_due_garmin_syncs")
def schedule_due_garmin_syncs(): return asyncio.run(_schedule())


async def _schedule_sparkyfitness():
    now = datetime.now(timezone.utc); queued = 0
    async with SessionLocal() as db:
        rows = (await db.scalars(select(SparkyFitnessConnection).where(
            SparkyFitnessConnection.status == "connected",
            SparkyFitnessConnection.auto_sync_enabled.is_(True),
        ))).all()
        for conn in rows:
            if conn.next_sync_at and conn.next_sync_at > now:
                continue
            interval = max(15, int(conn.sync_interval_minutes or 30))
            # Reserve the slot before enqueueing to prevent duplicate jobs from beat.
            conn.next_sync_at = now + timedelta(minutes=interval)
            await db.flush()
            sync_sparkyfitness_user.apply_async(args=[str(conn.user_id), True], queue="maintenance")
            queued += 1
        await db.commit()
    return {"queued": queued}


@shared_task(name="worker.tasks.scheduler.schedule_due_sparkyfitness_syncs")
def schedule_due_sparkyfitness_syncs(): return asyncio.run(_schedule_sparkyfitness())
