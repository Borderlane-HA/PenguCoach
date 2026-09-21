import asyncio
from datetime import date, datetime, timedelta

from celery import shared_task
from redis import Redis
from sqlalchemy import select

from pengucoach.common.config import settings
from pengucoach.db.models import Activity, GarminConnection, GarminSyncSetting, User
from pengucoach.db.session import SessionLocal
from pengucoach.garmin.gateway.factory import gateway_from_connection, serialize_refreshed_token
from pengucoach.garmin.sync.service import run_incremental_sync, sync_day


ALL_HISTORY_MAX_DAYS = 365 * 25 + 7


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


def _activity_day(item: dict) -> date | None:
    value = item.get("startTimeLocal") or item.get("startTimeGMT") or item.get("beginTimestamp")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    if isinstance(value, (int, float)):
        try:
            seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _activity_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        rows = payload.get("activityList") or payload.get("activities") or []
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


async def _discover_all_history_start(gateway) -> date | None:
    """Find a safe account-history start from Garmin's oldest activity.

    Garmin has no single read-only endpoint that yields the first date for every
    wellness domain. Activity count + the oldest activity page gives us a useful
    account-specific boundary without probing tens of thousands of empty days.
    """
    total = await asyncio.to_thread(gateway.count_activities)
    if total <= 0:
        return None
    page_size = min(1000, total)
    start = max(0, total - page_size)
    payload = await asyncio.to_thread(gateway.get_activities_page, start, page_size)
    dates = [d for item in _activity_list(payload) if (d := _activity_day(item)) is not None]
    return min(dates) if dates else None


async def _historical(user_id: str, days: int):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        if not user or not conn or conn.status != "connected":
            return {"status": "not_connected"}
        setting = await db.get(GarminSyncSetting, user.id)

        # Reuse one authenticated Garmin client for the complete import. This is
        # notably faster and gentler on Garmin SSO than logging in for every day.
        gateway, raw_client = await gateway_from_connection(conn)
        requested_all = int(days) == 0
        if requested_all:
            oldest = await _discover_all_history_start(gateway)
            if oldest is None:
                return {"status": "no_activity_history", "days": 0, "scope": "all"}
            hard_floor = date.today() - timedelta(days=ALL_HISTORY_MAX_DAYS - 1)
            start = max(oldest, hard_floor)
            days = (date.today() - start).days + 1
        else:
            days = max(1, min(int(days), ALL_HISTORY_MAX_DAYS))
            start = date.today() - timedelta(days=days - 1)

        count = 0
        for offset in range(days):
            day = start + timedelta(days=offset)
            await sync_day(
                db,
                user,
                conn,
                day,
                include_activities=True,
                gateway=gateway,
                raw_client=raw_client,
            )
            await db.commit()
            count += 1
            # A deliberately conservative pace reduces the chance of SSO/API throttling.
            if count % 5 == 0:
                await asyncio.sleep(2)

        conn.token_ciphertext = serialize_refreshed_token(raw_client)
        await db.commit()

        if setting and setting.fit_download_enabled:
            pending = (await db.scalars(
                select(Activity)
                .where(Activity.user_id == user.id, Activity.fit_status == "pending")
                .order_by(Activity.started_at.desc())
                .limit(5000)
            )).all()
            from worker.tasks.fit import analyze_fit
            for index, activity in enumerate(pending):
                analyze_fit.apply_async(args=[str(user.id), str(activity.id)], queue="fit", countdown=index * 3)
        return {
            "status": "success",
            "days": count,
            "scope": "all" if requested_all else "days",
            "start_date": start.isoformat(),
            "end_date": date.today().isoformat(),
        }


@shared_task(name="worker.tasks.garmin_sync.historical_import")
def historical_import(user_id: str, days: int = 365):
    timeout = 72 * 60 * 60 if int(days) == 0 else 24 * 60 * 60
    lock = _lock(f"pengucoach:garmin-history:{user_id}", timeout=timeout)
    if not lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        return asyncio.run(_historical(user_id, days))
    finally:
        try:
            lock.release()
        except Exception:
            pass
