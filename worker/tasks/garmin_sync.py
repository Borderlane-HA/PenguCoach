import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from celery import shared_task
from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
from redis import Redis
from sqlalchemy import select

from pengucoach.common.config import settings
from pengucoach.db.models import (
    Activity,
    GarminConnection,
    GarminSyncRun,
    GarminSyncSetting,
    SourceRecord,
    User,
)
from pengucoach.db.session import SessionLocal
from pengucoach.garmin.gateway.factory import gateway_from_connection, serialize_refreshed_token
from pengucoach.garmin.zones import sync_training_zones
from pengucoach.garmin.sync.service import (
    _hash_payload,
    _store_raw,
    _upsert_activities,
    run_incremental_sync,
    sync_day,
)

ALL_HISTORY_MAX_DAYS = 365 * 25 + 7
ACTIVITY_PAGE_SIZE = 100
MAX_ACTIVITY_PAGES = 5000
HISTORY_RECENT_REFRESH_DAYS = 3
ProgressCallback = Callable[[dict[str, Any]], None]


def _lock(name: str, timeout: int):
    redis = Redis.from_url(settings.redis_url)
    return redis.lock(name, timeout=timeout, blocking_timeout=0)


def _account_lock(user_id: str, timeout: int):
    # One Garmin session per account at a time. A long history import and the
    # minute scheduler must not compete with each other for Garmin requests.
    return _lock(f"pengucoach:garmin-account:{user_id}", timeout=timeout)


def _progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:
        # Progress reporting is best effort and must never break an import.
        pass


async def _sync(user_id: str):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        if not user or not conn or conn.status != "connected":
            return {"status": "not_connected"}
        result = await run_incremental_sync(db, user, conn)
        if result.get("status") == "success":
            # Zone profiles are account-level Garmin training settings. Refresh
            # them separately from day data so AI analysis/planning can use the
            # user's actual configured HR/power zones. Failures here do not make
            # an otherwise successful daily sync unusable.
            try:
                zone_gateway, _ = await gateway_from_connection(conn)
                result["training_zones"] = await sync_training_zones(db, user, zone_gateway)
                await db.commit()
            except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError):
                await db.rollback()
                result["training_zones"] = {"synced": False, "deferred": True}
            except Exception as exc:
                await db.rollback()
                result["training_zones"] = {"synced": False, "error": type(exc).__name__}
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
                    activity.fit_status = "queued"
                await db.commit()
        return result


@shared_task(name="worker.tasks.garmin_sync.sync_user")
def sync_user(user_id: str):
    lock = _account_lock(user_id, timeout=15 * 60)
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
            return datetime.fromtimestamp(seconds, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _activity_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        rows = payload.get("activityList") or payload.get("activities") or []
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


async def _fetch_activity_page(gateway, offset: int, limit: int, callback: ProgressCallback | None) -> list[dict]:
    """Fetch a Garmin activity page with bounded rate-limit retries."""
    for attempt in range(6):
        try:
            payload = await asyncio.to_thread(gateway.get_activities_page, offset, limit)
            return _activity_list(payload)
        except GarminConnectTooManyRequestsError:
            if attempt >= 5:
                raise
            wait_seconds = min(600, 30 * (2**attempt))
            _progress(
                callback,
                phase="activities",
                state="rate_limited",
                message=f"Garmin rate limit · retry in {wait_seconds}s",
                retry_in_seconds=wait_seconds,
                offset=offset,
            )
            await asyncio.sleep(wait_seconds)
    return []


async def _import_activity_catalog(
    db,
    user: User,
    gateway,
    start_date: date | None,
    callback: ProgressCallback | None,
    run: GarminSyncRun,
) -> dict[str, Any]:
    """Import the Garmin activity catalogue by offset pagination.

    The importer deliberately does not trust ``count_activities`` as a stopping
    condition. Some Garmin accounts/endpoints can expose capped counts while
    ``get_activities(start, limit)`` still has additional pages. We keep paging
    until Garmin returns an empty page, the requested date boundary is crossed,
    or a repeated page indicates the upstream stopped advancing.
    """
    offset = 0
    pages = 0
    scanned = 0
    inserted = 0
    matched = 0
    seen_ids: set[int] = set()
    oldest: date | None = None
    newest: date | None = None
    stop_reason = "empty_page"

    while pages < MAX_ACTIVITY_PAGES:
        rows = await _fetch_activity_page(gateway, offset, ACTIVITY_PAGE_SIZE, callback)
        run.requests_made += 1
        if not rows:
            stop_reason = "empty_page"
            break

        pages += 1
        scanned += len(rows)
        page_new: list[dict] = []
        page_dates: list[date] = []
        for item in rows:
            raw_id = item.get("activityId")
            try:
                activity_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            activity_date = _activity_day(item)
            if activity_date:
                page_dates.append(activity_date)
                oldest = activity_date if oldest is None else min(oldest, activity_date)
                newest = activity_date if newest is None else max(newest, activity_date)
            if activity_id in seen_ids:
                continue
            seen_ids.add(activity_id)
            if start_date is None or activity_date is None or activity_date >= start_date:
                page_new.append(item)

        if not page_new and rows and all(
            (d := _activity_day(item)) is not None and start_date is not None and d < start_date
            for item in rows
            if item.get("activityId") is not None
        ):
            stop_reason = "date_boundary"
            break

        # If the endpoint repeats a page instead of honoring the next offset,
        # stop instead of spinning forever.
        if rows and not page_new and not page_dates:
            stop_reason = "stalled_page"
            break

        if page_new:
            page_inserted, _ = await _upsert_activities(db, user, page_new)
            inserted += page_inserted
            matched += len(page_new)
            raw_day = min((_activity_day(x) for x in page_new if _activity_day(x)), default=date.today())
            await _store_raw(
                db,
                user,
                "activities_catalog",
                raw_day,
                page_new,
                external_id=f"offset:{offset}",
            )

        run.records_read = scanned
        run.records_inserted = inserted
        run.domains = {
            **(run.domains or {}),
            "activities": {
                "pages": pages,
                "scanned": scanned,
                "matched": matched,
                "inserted": inserted,
                "oldest": oldest.isoformat() if oldest else None,
                "newest": newest.isoformat() if newest else None,
            },
        }
        await db.commit()
        _progress(
            callback,
            phase="activities",
            state="running",
            message=f"Activities: {matched} imported/scanned in {pages} pages",
            pages=pages,
            scanned=scanned,
            matched=matched,
            inserted=inserted,
            oldest_date=oldest.isoformat() if oldest else None,
        )

        # Advance by what Garmin actually returned rather than the requested
        # limit. This also works if Garmin silently caps page size.
        offset += len(rows)

        # An entire page older than the requested range means later pages are
        # older as well for Garmin's reverse-chronological activity catalogue.
        if start_date is not None and page_dates and max(page_dates) < start_date:
            stop_reason = "date_boundary"
            break

        # Detect a pathological repeated page with only already-seen IDs.
        row_ids = []
        for item in rows:
            try:
                row_ids.append(int(item.get("activityId")))
            except (TypeError, ValueError):
                pass
        if row_ids and all(activity_id in seen_ids for activity_id in row_ids) and not page_new:
            stop_reason = "stalled_page"
            break

        # Gentle pacing for very large accounts; normal accounts rarely notice.
        if pages % 10 == 0:
            await asyncio.sleep(1)
    else:
        stop_reason = "safety_page_limit"

    return {
        "pages": pages,
        "scanned": scanned,
        "matched": matched,
        "inserted": inserted,
        "oldest": oldest,
        "newest": newest,
        "stop_reason": stop_reason,
    }


def _history_marker(setting: GarminSyncSetting | None) -> dict[str, Any]:
    return {
        "version": 1,
        "sync_health": True if setting is None else bool(setting.sync_health),
        "sync_body": True if setting is None else bool(setting.sync_body),
        "sync_training": True if setting is None else bool(setting.sync_training),
    }


async def _history_day_done(db, user: User, day: date, marker: dict[str, Any]) -> bool:
    # Recent days are intentionally refreshed because Garmin can finalize sleep,
    # recovery and training values after the day has ended.
    if day >= date.today() - timedelta(days=HISTORY_RECENT_REFRESH_DAYS - 1):
        return False
    digest = _hash_payload(marker)
    found = await db.scalar(select(SourceRecord.id).where(
        SourceRecord.user_id == user.id,
        SourceRecord.domain == "history_day_complete",
        SourceRecord.record_date == day,
        SourceRecord.content_hash == digest,
    ))
    return found is not None


async def _queue_pending_fit(db, user: User, callback: ProgressCallback | None) -> int:
    setting = await db.get(GarminSyncSetting, user.id)
    if not setting or not setting.fit_download_enabled:
        return 0
    pending = (await db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id, Activity.fit_status == "pending")
        .order_by(Activity.started_at.desc())
        .limit(25000)
    )).all()
    if not pending:
        return 0
    from worker.tasks.fit import analyze_fit

    queued = 0
    for index, activity in enumerate(pending):
        # Queue immediately; the FIT task itself is rate-limited and uses the
        # same per-account Garmin lock. Redis can therefore buffer very large
        # backlogs without thousands of long-lived ETA tasks in worker memory.
        analyze_fit.apply_async(
            args=[str(user.id), str(activity.id)],
            queue="fit",
        )
        activity.fit_status = "queued"
        queued += 1
        if queued % 100 == 0:
            await db.commit()
            _progress(
                callback,
                phase="fit_queue",
                state="running",
                message=f"FIT queue: {queued}/{len(pending)}",
                queued=queued,
                total=len(pending),
            )
    await db.commit()
    return queued


async def _historical(user_id: str, days: int, callback: ProgressCallback | None = None):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        if not user or not conn or conn.status != "connected":
            return {"status": "not_connected"}
        setting = await db.get(GarminSyncSetting, user.id)
        run = GarminSyncRun(user_id=user.id, sync_type="historical", status="running", domains={})
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

        requested_all = int(days) == 0
        if requested_all:
            requested_start: date | None = None
        else:
            days = max(1, min(int(days), ALL_HISTORY_MAX_DAYS))
            requested_start = date.today() - timedelta(days=days - 1)

        try:
            gateway, raw_client = await gateway_from_connection(conn)
            try:
                zones = await sync_training_zones(db, user, gateway, force=True)
                await db.commit()
                _progress(
                    callback,
                    phase="zones",
                    state="running",
                    message="Garmin training zones synchronized",
                    heart_rate_profiles=zones.get("heart_rate", {}).get("profile_count", 0),
                    power_profiles=zones.get("power", {}).get("profile_count", 0),
                )
            except GarminConnectTooManyRequestsError:
                await db.rollback()
                # A zone refresh is valuable but must not block a multi-year import.
                pass
            except Exception:
                await db.rollback()
                user = await db.get(User, user_id)
                conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
                run = await db.get(GarminSyncRun, run_id)
            _progress(
                callback,
                phase="activities",
                state="running",
                message="Reading Garmin activity catalogue…",
                requested_scope="all" if requested_all else "days",
                requested_days=0 if requested_all else days,
            )

            catalog = await _import_activity_catalog(db, user, gateway, requested_start, callback, run)
            if requested_all:
                oldest = catalog.get("oldest")
                if oldest is None:
                    run.status = "success"
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    return {
                        "status": "no_activity_history",
                        "days": 0,
                        "scope": "all",
                        "activities": {k: v for k, v in catalog.items() if not isinstance(v, date)},
                    }
                hard_floor = date.today() - timedelta(days=ALL_HISTORY_MAX_DAYS - 1)
                start = max(oldest, hard_floor)
                days = (date.today() - start).days + 1
            else:
                start = requested_start or date.today()

            # Activities are already complete at this point. Daily health/recovery
            # data is intentionally a separate phase, so a slow wellness backfill
            # cannot leave a hole in the activity catalogue.
            marker = _history_marker(setting)
            completed_days = 0
            skipped_days = 0
            requests_made = run.requests_made
            for offset in range(days):
                day = start + timedelta(days=offset)
                if await _history_day_done(db, user, day, marker):
                    skipped_days += 1
                    completed_days += 1
                    if completed_days % 25 == 0 or completed_days == days:
                        _progress(
                            callback,
                            phase="wellness",
                            state="running",
                            message=f"Daily data: {completed_days}/{days} days",
                            current_date=day.isoformat(),
                            completed_days=completed_days,
                            skipped_days=skipped_days,
                            total_days=days,
                            percent=round(completed_days / days * 100, 1),
                            activities_imported=catalog["matched"],
                        )
                    continue

                retry = 0
                while True:
                    try:
                        result = await sync_day(
                            db,
                            user,
                            conn,
                            day,
                            include_activities=False,
                            gateway=gateway,
                            raw_client=raw_client,
                        )
                        requests_made += len(result.get("domains") or {})
                        await _store_raw(db, user, "history_day_complete", day, marker)
                        await db.commit()
                        break
                    except GarminConnectTooManyRequestsError:
                        await db.rollback()
                        retry += 1
                        if retry > 5:
                            raise
                        wait_seconds = min(600, 30 * (2 ** (retry - 1)))
                        _progress(
                            callback,
                            phase="wellness",
                            state="rate_limited",
                            message=f"Garmin rate limit · retry in {wait_seconds}s",
                            current_date=day.isoformat(),
                            completed_days=completed_days,
                            total_days=days,
                            retry_in_seconds=wait_seconds,
                        )
                        await asyncio.sleep(wait_seconds)
                        # Rollback expires ORM state; reload DB rows while keeping
                        # the authenticated Garmin client/session alive.
                        user = await db.get(User, user_id)
                        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
                        run = await db.get(GarminSyncRun, run_id)

                completed_days += 1
                run.requests_made = requests_made
                if completed_days % 5 == 0 or completed_days == days:
                    run.domains = {
                        **(run.domains or {}),
                        "wellness": {
                            "completed_days": completed_days,
                            "skipped_days": skipped_days,
                            "total_days": days,
                            "current_date": day.isoformat(),
                        },
                    }
                    await db.commit()
                    _progress(
                        callback,
                        phase="wellness",
                        state="running",
                        message=f"Daily data: {completed_days}/{days} days",
                        current_date=day.isoformat(),
                        completed_days=completed_days,
                        skipped_days=skipped_days,
                        total_days=days,
                        percent=round(completed_days / days * 100, 1),
                        activities_imported=catalog["matched"],
                    )
                    # Conservative pacing for many day-specific Garmin endpoints.
                    await asyncio.sleep(1)

            conn.token_ciphertext = serialize_refreshed_token(raw_client)
            conn.last_validated_at = datetime.now(timezone.utc)
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()

            queued = await _queue_pending_fit(db, user, callback)
            result = {
                "status": "success",
                "days": days,
                "scope": "all" if requested_all else "days",
                "start_date": start.isoformat(),
                "end_date": date.today().isoformat(),
                "activities": {
                    "pages": catalog["pages"],
                    "scanned": catalog["scanned"],
                    "matched": catalog["matched"],
                    "inserted": catalog["inserted"],
                    "oldest": catalog["oldest"].isoformat() if catalog["oldest"] else None,
                    "newest": catalog["newest"].isoformat() if catalog["newest"] else None,
                    "stop_reason": catalog["stop_reason"],
                },
                "wellness": {
                    "completed_days": completed_days,
                    "skipped_days": skipped_days,
                },
                "fit_queued": queued,
            }
            _progress(
                callback,
                phase="done",
                state="success",
                message="Historical import completed",
                **result,
            )
            return result
        except GarminConnectAuthenticationError:
            await db.rollback()
            run = await db.get(GarminSyncRun, run_id)
            conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user_id))
            if conn:
                conn.status = "reauth_required"
                conn.last_error_code = "GARMIN_REAUTH_REQUIRED"
                conn.last_error_at = datetime.now(timezone.utc)
            if run:
                run.status = "failed"
                run.error_code = "GARMIN_REAUTH_REQUIRED"
                run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "reauth_required"}
        except GarminConnectTooManyRequestsError:
            await db.rollback()
            run = await db.get(GarminSyncRun, run_id)
            conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user_id))
            if conn:
                conn.last_error_code = "GARMIN_RATE_LIMITED"
                conn.last_error_at = datetime.now(timezone.utc)
            if run:
                run.status = "rate_limited"
                run.error_code = "GARMIN_RATE_LIMITED"
                run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "rate_limited", "resume_safe": True}
        except Exception as exc:
            await db.rollback()
            run = await db.get(GarminSyncRun, run_id)
            if run:
                run.status = "failed"
                run.error_code = "GARMIN_HISTORY_FAILED"
                run.error_message_safe = type(exc).__name__
                run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise


@shared_task(bind=True, name="worker.tasks.garmin_sync.historical_import")
def historical_import(self, user_id: str, days: int = 365):
    timeout = 7 * 24 * 60 * 60 if int(days) == 0 else 72 * 60 * 60
    lock = _account_lock(user_id, timeout=timeout)
    if not lock.acquire(blocking=False):
        return {"status": "already_running"}

    def callback(meta: dict[str, Any]) -> None:
        self.update_state(state="PROGRESS", meta=meta)

    try:
        return asyncio.run(_historical(user_id, days, callback=callback))
    finally:
        try:
            lock.release()
        except Exception:
            pass
