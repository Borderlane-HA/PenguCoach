import asyncio
import uuid

from celery import shared_task
from sqlalchemy import select

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
        try:
            analyze = setting.fit_analysis_enabled if setting else True
            return await download_and_analyze_fit(db, user, activity, conn, analyze=analyze)
        except Exception as exc:
            activity.fit_status = "failed"
            await db.commit()
            return {"status": "failed", "error": type(exc).__name__}


@shared_task(name="worker.tasks.fit.analyze_fit")
def analyze_fit(user_id: str, activity_id: str):
    return asyncio.run(_run(user_id, activity_id))
