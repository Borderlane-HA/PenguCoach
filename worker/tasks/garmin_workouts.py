from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any, Callable

from sqlalchemy import select

from pengucoach.db.models import AiRun, GarminConnection, GarminSyncSetting, GarminWorkoutExport, User
from pengucoach.db.session import SessionLocal
from pengucoach.garmin.gateway.factory import serialize_refreshed_token, workout_gateway_from_connection
from pengucoach.garmin.gateway.workouts import session_exportability
from pengucoach.training_plan.calendar import scheduled_date, selected_sessions
from pengucoach.training_plan.structured import TrainingPlanDocument
from worker.celery_app import app


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return f"{type(exc).__name__}: {text[:500]}" if text else type(exc).__name__


def _id_from(value: Any, *keys: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        candidate = value.get(key)
        if candidate is not None and str(candidate).strip():
            return str(candidate)
    return None


async def _export_plan(
    user_id: str,
    payload: dict[str, Any],
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    async with SessionLocal() as db:
        uid = uuid.UUID(user_id)
        user = await db.get(User, uid)
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        settings = await db.get(GarminSyncSetting, uid)
        if not settings or not settings.workout_export_enabled:
            raise RuntimeError("GARMIN_WORKOUT_EXPORT_DISABLED")
        connection = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == uid))
        if not connection or connection.status != "connected" or not connection.token_ciphertext:
            raise RuntimeError("GARMIN_NOT_CONNECTED")

        run_id = uuid.UUID(str(payload["plan_run_id"]))
        run = await db.get(AiRun, run_id)
        if not run or run.user_id != uid or run.task_type != "training_plan":
            raise RuntimeError("TRAINING_PLAN_NOT_FOUND")
        raw_plan = (run.metadata_json or {}).get("structured_plan")
        if not raw_plan:
            raise RuntimeError("TRAINING_PLAN_NOT_STRUCTURED")
        plan = TrainingPlanDocument.model_validate(raw_plan)
        start_date = date.fromisoformat(str(payload["start_date"]))
        if start_date.isoweekday() != 1:
            raise RuntimeError("PLAN_START_DATE_MUST_BE_MONDAY")
        requested_ids = payload.get("session_ids")
        sessions = selected_sessions(plan, requested_ids)
        if requested_ids is not None and len({x.id for x in sessions}) != len(set(requested_ids)):
            raise RuntimeError("UNKNOWN_TRAINING_SESSION")
        if not sessions:
            raise RuntimeError("NO_TRAINING_SESSIONS_SELECTED")

        gateway, raw_client = await workout_gateway_from_connection(connection)
        results: list[dict[str, Any]] = []
        exported = skipped = failed = unsupported = 0
        total = len(sessions)

        for index, session in enumerate(sessions, start=1):
            target_date = scheduled_date(start_date, session)
            if progress:
                progress({
                    "stage": "garmin_workout_export",
                    "message": f"Exporting {index}/{total}: {session.name}",
                    "current": index,
                    "total": total,
                    "session_id": session.id,
                })

            exportable, reason = session_exportability(session)
            if not exportable:
                unsupported += 1
                results.append({"session_id": session.id, "date": target_date.isoformat(), "status": "unsupported", "reason": reason})
                continue

            ledger = await db.scalar(select(GarminWorkoutExport).where(
                GarminWorkoutExport.user_id == uid,
                GarminWorkoutExport.plan_run_id == run_id,
                GarminWorkoutExport.session_id == session.id,
                GarminWorkoutExport.scheduled_date == target_date,
            ))
            if ledger and ledger.status == "exported" and ledger.workout_id:
                skipped += 1
                results.append({
                    "session_id": session.id,
                    "date": target_date.isoformat(),
                    "status": "already_exported",
                    "workout_id": ledger.workout_id,
                    "scheduled_workout_id": ledger.scheduled_workout_id,
                })
                continue
            if not ledger:
                ledger = GarminWorkoutExport(
                    user_id=uid,
                    plan_run_id=run_id,
                    session_id=session.id,
                    scheduled_date=target_date,
                    status="pending",
                )
                db.add(ledger)
            else:
                ledger.status = "pending"
                ledger.error_message_safe = None
            await db.commit()

            workout_id: str | None = None
            try:
                upload = await asyncio.to_thread(gateway.upload_session, session)
                workout_id = _id_from(upload, "workoutId", "id")
                if not workout_id:
                    raise RuntimeError("GARMIN_WORKOUT_ID_MISSING")
                schedule = await asyncio.to_thread(gateway.schedule_workout, workout_id, target_date)
                schedule_id = _id_from(schedule, "workoutScheduleId", "scheduledWorkoutId", "id")
                ledger.workout_id = workout_id
                ledger.scheduled_workout_id = schedule_id
                ledger.status = "exported"
                ledger.error_message_safe = None
                await db.commit()
                exported += 1
                results.append({
                    "session_id": session.id,
                    "date": target_date.isoformat(),
                    "status": "exported",
                    "workout_id": workout_id,
                    "scheduled_workout_id": schedule_id,
                })
            except Exception as exc:
                # If template creation succeeded but calendar scheduling failed,
                # clean up the orphaned template before recording the error.
                if workout_id:
                    try:
                        await asyncio.to_thread(gateway.delete_workout, workout_id)
                    except Exception:
                        pass
                failed += 1
                ledger.workout_id = None
                ledger.scheduled_workout_id = None
                ledger.status = "error"
                ledger.error_message_safe = _safe_error(exc)
                await db.commit()
                results.append({
                    "session_id": session.id,
                    "date": target_date.isoformat(),
                    "status": "error",
                    "error": ledger.error_message_safe,
                })
            await asyncio.sleep(0.2)

        connection.token_ciphertext = serialize_refreshed_token(raw_client)
        await db.commit()
        return {
            "plan_run_id": str(run_id),
            "start_date": start_date.isoformat(),
            "total": total,
            "exported": exported,
            "already_exported": skipped,
            "unsupported": unsupported,
            "failed": failed,
            "results": results,
        }


@app.task(bind=True, name="worker.tasks.garmin_workouts.export_plan")
def export_plan(self, user_id: str, payload: dict[str, Any]):
    self.update_state(state="PROGRESS", meta={"stage": "garmin_workout_export", "message": "Preparing Garmin workout export"})
    return asyncio.run(_export_plan(user_id, payload, progress=lambda value: self.update_state(state="PROGRESS", meta=value)))


async def _delete_plan_from_garmin(
    user_id: str,
    plan_run_id: str,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Remove PenguCoach-created calendar schedules/templates, then delete the local plan.

    Cleanup is deliberately independent from the workout-export opt-in. A user
    who later disables export must still be able to remove content that
    PenguCoach previously created in Garmin.
    """
    async with SessionLocal() as db:
        uid = uuid.UUID(user_id)
        run_id = uuid.UUID(plan_run_id)
        run = await db.get(AiRun, run_id)
        if not run or run.user_id != uid or run.task_type != "training_plan":
            raise RuntimeError("TRAINING_PLAN_NOT_FOUND")

        exports = (await db.scalars(select(GarminWorkoutExport).where(
            GarminWorkoutExport.user_id == uid,
            GarminWorkoutExport.plan_run_id == run_id,
        ).order_by(GarminWorkoutExport.scheduled_date, GarminWorkoutExport.session_id))).all()
        remote = [row for row in exports if row.workout_id or row.scheduled_workout_id]
        if not remote:
            await db.delete(run)
            await db.commit()
            return {"plan_run_id": str(run_id), "deleted": True, "garmin_deleted": 0, "failed": 0}

        connection = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == uid))
        if not connection or connection.status != "connected" or not connection.token_ciphertext:
            raise RuntimeError("GARMIN_NOT_CONNECTED")
        gateway, raw_client = await workout_gateway_from_connection(connection)

        deleted = failed = 0
        errors: list[dict[str, Any]] = []
        total = len(remote)
        for index, ledger in enumerate(remote, start=1):
            if progress:
                progress({
                    "stage": "garmin_workout_delete",
                    "message": f"Removing Garmin workout {index}/{total}",
                    "current": index,
                    "total": total,
                    "session_id": ledger.session_id,
                    "date": ledger.scheduled_date.isoformat(),
                })
            try:
                # Unschedule first; deleting the reusable template is a separate
                # operation in Garmin Connect and is attempted only afterwards.
                if ledger.scheduled_workout_id:
                    await asyncio.to_thread(gateway.unschedule_workout, ledger.scheduled_workout_id)
                    ledger.scheduled_workout_id = None
                    await db.commit()
                if ledger.workout_id:
                    await asyncio.to_thread(gateway.delete_workout, ledger.workout_id)
                    ledger.workout_id = None
                    await db.commit()
                ledger.status = "deleted"
                ledger.error_message_safe = None
                await db.commit()
                deleted += 1
            except Exception as exc:
                failed += 1
                ledger.status = "error"
                ledger.error_message_safe = _safe_error(exc)
                await db.commit()
                errors.append({
                    "session_id": ledger.session_id,
                    "date": ledger.scheduled_date.isoformat(),
                    "error": ledger.error_message_safe,
                })

        connection.token_ciphertext = serialize_refreshed_token(raw_client)
        await db.commit()
        if failed:
            # Keep the plan and export ledger so the failed remote cleanup can be retried.
            return {
                "plan_run_id": str(run_id),
                "deleted": False,
                "garmin_deleted": deleted,
                "failed": failed,
                "errors": errors,
                "retry_safe": True,
            }

        run = await db.get(AiRun, run_id)
        if run:
            await db.delete(run)
        await db.commit()
        return {"plan_run_id": str(run_id), "deleted": True, "garmin_deleted": deleted, "failed": 0}


@app.task(bind=True, name="worker.tasks.garmin_workouts.delete_plan")
def delete_plan(self, user_id: str, plan_run_id: str):
    self.update_state(state="PROGRESS", meta={"stage": "garmin_workout_delete", "message": "Preparing Garmin workout cleanup"})
    return asyncio.run(_delete_plan_from_garmin(
        user_id,
        plan_run_id,
        progress=lambda value: self.update_state(state="PROGRESS", meta=value),
    ))
