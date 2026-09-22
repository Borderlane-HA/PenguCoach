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
    GarminRequestTimeout,
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
HISTORY_FULL_DETAIL_DAYS = 90
HISTORY_CONTROL_TTL_SECONDS = 7 * 24 * 60 * 60
ProgressCallback = Callable[[dict[str, Any]], None]


def _lock(name: str, timeout: int):
    redis = Redis.from_url(settings.redis_url)
    return redis.lock(name, timeout=timeout, blocking_timeout=0)


def _account_lock_key(user_id: str) -> str:
    return f"pengucoach:garmin-account:{user_id}"


def _account_lock(user_id: str, timeout: int):
    # One Garmin session per account at a time. A long history import and the
    # minute scheduler must not compete with each other for Garmin requests.
    return _lock(_account_lock_key(user_id), timeout=timeout)


def _history_task_key(user_id: str) -> str:
    return f"pengucoach:garmin-history-task:{user_id}"


def current_history_import_task(user_id: str) -> str | None:
    raw = Redis.from_url(settings.redis_url).get(_history_task_key(user_id))
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def _set_current_history_import_task(user_id: str, task_id: str) -> None:
    Redis.from_url(settings.redis_url).setex(_history_task_key(user_id), HISTORY_CONTROL_TTL_SECONDS, task_id)


def _clear_current_history_import_task(user_id: str, task_id: str | None = None) -> None:
    redis = Redis.from_url(settings.redis_url)
    key = _history_task_key(user_id)
    if task_id is None:
        redis.delete(key)
        return
    raw = redis.get(key)
    current = raw.decode("utf-8") if isinstance(raw, bytes) else (str(raw) if raw is not None else None)
    if current == task_id:
        redis.delete(key)


def force_clear_history_import_state(user_id: str) -> None:
    """Clear cooperative-control and stale account-lock keys after a hard revoke.

    Hard cancellation kills the Celery child and therefore its ``finally`` block
    may never get a chance to release the Redis lock. The API calls this only
    after revoking the specific history task requested by the same user.
    """
    redis = Redis.from_url(settings.redis_url)
    redis.delete(_history_control_key(user_id), _account_lock_key(user_id), _history_task_key(user_id))


class HistoryImportInterrupted(RuntimeError):
    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"GARMIN_HISTORY_{action.upper()}")


def _history_control_key(user_id: str) -> str:
    return f"pengucoach:garmin-history-control:{user_id}"


def set_history_import_control(user_id: str, action: str) -> None:
    if action not in {"pause", "cancel"}:
        raise ValueError("INVALID_HISTORY_CONTROL")
    Redis.from_url(settings.redis_url).setex(_history_control_key(user_id), HISTORY_CONTROL_TTL_SECONDS, action)


def clear_history_import_control(user_id: str) -> None:
    Redis.from_url(settings.redis_url).delete(_history_control_key(user_id))


def _check_history_import_control(user_id: str) -> None:
    try:
        raw = Redis.from_url(settings.redis_url).get(_history_control_key(user_id))
    except Exception:
        # Progress-control polling must not make an otherwise valid import fail.
        return
    if not raw:
        return
    action = raw.decode() if isinstance(raw, bytes) else str(raw)
    if action in {"pause", "cancel"}:
        raise HistoryImportInterrupted(action)


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


async def _fetch_activity_page(
    gateway,
    offset: int,
    limit: int,
    callback: ProgressCallback | None,
    control_user_id: str | None = None,
) -> list[dict]:
    """Fetch a Garmin activity page with bounded rate-limit retries."""
    for attempt in range(6):
        if control_user_id:
            _check_history_import_control(control_user_id)
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
            if control_user_id:
                _check_history_import_control(control_user_id)
            await asyncio.sleep(wait_seconds)
            if control_user_id:
                _check_history_import_control(control_user_id)
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
        _check_history_import_control(str(user.id))
        rows = await _fetch_activity_page(gateway, offset, ACTIVITY_PAGE_SIZE, callback, str(user.id))
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
    # Keep this payload byte-for-byte compatible with alpha.15 so already
    # completed full-detail days remain resume-safe after upgrading.
    return {
        "version": 1,
        "sync_health": True if setting is None else bool(setting.sync_health),
        "sync_body": True if setting is None else bool(setting.sync_body),
        "sync_training": True if setting is None else bool(setting.sync_training),
    }


def _history_core_marker(setting: GarminSyncSetting | None) -> dict[str, Any]:
    return {**_history_marker(setting), "detail_level": "core"}


async def _history_day_done(
    db,
    user: User,
    day: date,
    full_marker: dict[str, Any],
    detail_level: str = "full",
    core_marker: dict[str, Any] | None = None,
) -> bool:
    # Recent days are intentionally refreshed because Garmin can finalize sleep,
    # recovery and training values after the day has ended.
    if day >= date.today() - timedelta(days=HISTORY_RECENT_REFRESH_DAYS - 1):
        return False
    full_digest = _hash_payload(full_marker)
    full = await db.scalar(select(SourceRecord.id).where(
        SourceRecord.user_id == user.id,
        SourceRecord.domain == "history_day_complete",
        SourceRecord.record_date == day,
        SourceRecord.content_hash == full_digest,
    ))
    if full is not None or detail_level == "full":
        return full is not None
    core_digest = _hash_payload(core_marker or _history_core_marker(None))
    core = await db.scalar(select(SourceRecord.id).where(
        SourceRecord.user_id == user.id,
        SourceRecord.domain == "history_day_core_complete",
        SourceRecord.record_date == day,
        SourceRecord.content_hash == core_digest,
    ))
    return core is not None


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


async def _historical(user_id: str, days: int, mode: str = "optimized", callback: ProgressCallback | None = None, task_id: str | None = None):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id)) if user else None
        if not user or not conn or conn.status != "connected":
            return {"status": "not_connected"}
        setting = await db.get(GarminSyncSetting, user.id)
        mode = "full" if mode == "full" else "optimized"
        run = GarminSyncRun(user_id=user.id, sync_type="historical", status="running", domains={"mode": mode, "task_id": task_id})
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
                import_mode=mode,
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
            core_marker = _history_core_marker(setting)
            completed_days = 0
            skipped_days = 0
            requests_made = run.requests_made
            full_detail_start = date.today() - timedelta(days=HISTORY_FULL_DETAIL_DAYS - 1)
            for offset in range(days):
                _check_history_import_control(str(user.id))
                day = start + timedelta(days=offset)
                detail_level = "full" if mode == "full" or day >= full_detail_start else "core"
                if await _history_day_done(db, user, day, marker, detail_level, core_marker):
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
                            detail_level=detail_level,
                            import_mode=mode,
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
                            detail_level=detail_level,
                        )
                        requests_made += len(result.get("domains") or {})
                        marker_domain = "history_day_complete" if detail_level == "full" else "history_day_core_complete"
                        marker_payload = marker if detail_level == "full" else core_marker
                        await _store_raw(db, user, marker_domain, day, marker_payload)
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
                        # Pause/cancel is checked before a long retry sleep as well.
                        _check_history_import_control(str(user.id))
                        await asyncio.sleep(wait_seconds)
                        _check_history_import_control(str(user.id))
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
                            "mode": mode,
                            "detail_level": detail_level,
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
                        detail_level=detail_level,
                        import_mode=mode,
                    )
                    # Optimized historical mode uses fewer endpoints for old days;
                    # pace less aggressively while still yielding periodically.
                    if mode == "full" or completed_days % 25 == 0:
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
                    "mode": mode,
                    "full_detail_days": HISTORY_FULL_DETAIL_DAYS if mode == "optimized" else days,
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
        except HistoryImportInterrupted as interrupted:
            await db.rollback()
            run = await db.get(GarminSyncRun, run_id)
            conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user_id))
            if conn and "raw_client" in locals():
                try:
                    conn.token_ciphertext = serialize_refreshed_token(raw_client)
                except Exception:
                    pass
            if run:
                run.status = "paused" if interrupted.action == "pause" else "cancelled"
                run.finished_at = datetime.now(timezone.utc)
                run.error_code = None
            await db.commit()
            clear_history_import_control(str(user_id))
            result = {
                "status": "paused" if interrupted.action == "pause" else "cancelled",
                "resume_safe": True,
                "mode": mode,
            }
            _progress(callback, phase="stopped", state=result["status"], message=f"Historical import {result['status']}", **result)
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
        except GarminRequestTimeout as exc:
            await db.rollback()
            run = await db.get(GarminSyncRun, run_id)
            conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user_id))
            if conn:
                conn.last_error_code = "GARMIN_REQUEST_TIMEOUT"
                conn.last_error_at = datetime.now(timezone.utc)
            if run:
                run.status = "request_timeout"
                run.error_code = "GARMIN_REQUEST_TIMEOUT"
                run.error_message_safe = f"{exc.domain}:{exc.seconds}s"
                run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return {
                "status": "request_timeout",
                "resume_safe": True,
                "domain": exc.domain,
                "timeout_seconds": exc.seconds,
                "mode": mode,
            }
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
def historical_import(self, user_id: str, days: int = 365, mode: str = "optimized"):
    timeout = 7 * 24 * 60 * 60 if int(days) == 0 else 72 * 60 * 60
    lock = _account_lock(user_id, timeout=timeout)
    if not lock.acquire(blocking=False):
        return {"status": "already_running"}

    task_id = str(self.request.id)
    _set_current_history_import_task(user_id, task_id)

    def callback(meta: dict[str, Any]) -> None:
        self.update_state(state="PROGRESS", meta=meta)

    try:
        return asyncio.run(_historical(user_id, days, mode=mode, callback=callback, task_id=task_id))
    finally:
        _clear_current_history_import_task(user_id, task_id)
        try:
            lock.release()
        except Exception:
            pass
