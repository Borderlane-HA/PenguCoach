import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.context import build_training_plan_context
from pengucoach.db.models import AiRun, BackgroundJob, Conversation, GarminWorkoutExport, User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.llm.service import eligible_models, resolve_model, task_settings, provider_is_local
from pengucoach.llm.usage import normalize_quality, quality_options, quality_budget
from worker.tasks.ai import activity_analysis as activity_analysis_task
from worker.tasks.ai import coach_chat as coach_chat_task
from worker.tasks.ai import training_plan as training_plan_task
from worker.celery_app import app as celery_app

router = APIRouter(prefix="/coach", tags=["coach"])
from pengucoach.coach.selection import ContextSelection, auto_context_days

TASKS = ("coach_chat", "activity_analysis", "training_plan")


def _analysis_scope_message(activity_id: uuid.UUID, days: int, locale: str) -> str:
    de = str(locale).startswith("de")
    labels = {
        0: ("nur diesem Training", "this training session only"),
        1: ("dem Kontext dieses Tages", "this day\'s context"),
        3: ("dem 3-Tage-Kontext", "the 3-day context"),
        7: ("dem 7-Tage-Kontext inklusive 3-Tage-Vergleich", "the 7-day context including the 3-day comparison"),
    }
    label = labels.get(days, labels[7])[0 if de else 1]
    return (f"Analysiere Aktivität {activity_id} mit {label}." if de else f"Analyse activity {activity_id} using {label}.")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    use_personal_context: bool = True
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=65536)
    context_window_tokens: int | None = Field(default=None, ge=2048, le=1048576)
    context_data: ContextSelection = Field(default_factory=ContextSelection)
    context_mode: Literal["auto", "none", "3", "7", "14", "21", "28"] = "auto"
    locale: Literal["de", "en"] | None = None
    quality_profile: Literal["very_low", "low", "standard", "high"] = "standard"


class ActivityAnalysisRequest(BaseModel):
    activity_id: uuid.UUID
    lookback_days: Literal[0, 1, 3, 7] = 7
    prompt: str | None = Field(default=None, max_length=16000)
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=65536)
    context_window_tokens: int | None = Field(default=None, ge=2048, le=1048576)
    locale: Literal["de", "en"] | None = None
    quality_profile: Literal["very_low", "low", "standard", "high"] = "standard"


TrainingContextSelection = ContextSelection

class TrainingPlanRequest(BaseModel):
    use_personal_context: bool = True
    goal_type: Literal[
        "muscle_gain", "cardio_endurance", "hybrid", "cycling_endurance", "running_5k",
        "running_10k", "half_marathon", "marathon", "strength", "general_fitness", "mobility", "custom"
    ] = "hybrid"
    goal_text: str = Field(default="", max_length=1500)
    experience: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    weeks: int = Field(default=8, ge=1, le=24)
    days_per_week: int = Field(default=4, ge=1, le=7)
    session_minutes: int = Field(default=60, ge=15, le=240)
    equipment: str = Field(default="", max_length=1500)
    constraints: str = Field(default="", max_length=2500)
    prompt: str | None = Field(default=None, max_length=16000)
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=65536)
    context_window_tokens: int | None = Field(default=None, ge=2048, le=1048576)
    context_days: Literal[3, 7, 14, 21, 28] = 7
    context_data: TrainingContextSelection = Field(default_factory=TrainingContextSelection)
    locale: Literal["de", "en"] | None = None
    quality_profile: Literal["very_low", "low", "standard", "high"] = "standard"
    start_date: date | None = None
    include_weather: bool | None = None

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, value: date | None) -> date | None:
        if value is not None and value.weekday() != 0:
            raise ValueError("PLAN_START_MUST_BE_MONDAY")
        return value


async def _privacy(db: AsyncSession, user: User) -> tuple[UserPreference | None, bool]:
    pref = await db.get(UserPreference, user.id)
    local_only = True if not pref else (pref.local_ai_only or not pref.cloud_health_ai_allowed)
    return pref, local_only


def _run_payload(row: AiRun) -> dict:
    return {
        "id": str(row.id),
        "task_type": row.task_type,
        "activity_id": str(row.activity_id) if row.activity_id else None,
        "model_id": str(row.model_id) if row.model_id else None,
        "provider": row.provider_name,
        "model": row.model_name,
        "prompt": row.prompt,
        "lookback_days": row.lookback_days,
        "max_output_tokens": row.max_output_tokens,
        "content": row.content,
        "metadata": {k: v for k, v in (row.metadata_json or {}).items() if not k.startswith("_")},
        "created_at": row.created_at,
    }


def _answer_metadata(answer: dict, *, locale: str, goal: dict | None = None) -> dict:
    value = {
        "usage": answer.get("usage", {}),
        "context_chars": answer.get("context_chars"),
        "context_estimated_tokens": answer.get("context_estimated_tokens"),
        "context_window_tokens": answer.get("context_window_tokens"),
        "context_budget_tokens": answer.get("context_budget_tokens"),
        "requested_max_output_tokens": answer.get("requested_max_output_tokens"),
        "output_budget_adjusted": answer.get("output_budget_adjusted", False),
        "context_truncated": answer.get("context_truncated", False),
        "stop_reason": answer.get("stop_reason"),
        "truncated": answer.get("truncated", False),
        "local": answer.get("local"),
        "locale": locale,
        "quality_profile": answer.get("quality_profile", "standard"),
        "pricing": answer.get("pricing"),
        "cost_eur": answer.get("cost_eur"),
        "elapsed_seconds": answer.get("elapsed_seconds"),
        "tokens_per_second": answer.get("tokens_per_second"),
    }
    if goal is not None:
        value["goal"] = goal
    return value


def _auto_context_days(message: str) -> int:
    return auto_context_days(message)

@router.get("/capabilities")
async def capabilities(
    locale: Literal["de", "en"] | None = Query(default=None),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    pref, local_only = await _privacy(db, user)
    models = await eligible_models(db, local_only=local_only)
    cfg = dict(pref.dashboard_config or {}) if pref else {}
    saved_profiles = cfg.get("ai_quality_profiles") if isinstance(cfg.get("ai_quality_profiles"), dict) else {}
    tasks: dict[str, dict] = {}
    selected_locale = locale or user.locale
    for task in TASKS:
        config = await task_settings(db, task, selected_locale)
        selected = await resolve_model(db, task, local_only=local_only)
        tasks[task] = {
            "default_model_id": str(selected[1].id) if selected else None,
            "default_model": selected[1].display_name if selected else None,
            "default_provider": selected[0].name if selected else None,
            "local": provider_is_local(selected[0]) if selected else None,
            **config,
            "context_window_tokens": min(int(config["context_window_tokens"]), selected[1].context_window or 1048576) if selected else int(config["context_window_tokens"]),
            "standard_max_output_tokens": int(config["max_output_tokens"]),
            "max_output_tokens": min(quality_budget(task, int(config["max_output_tokens"]), saved_profiles.get(task, "standard")),
                (selected[1].metadata_json or {}).get("provider_max_output_tokens") or 65536) if selected else quality_budget(task, int(config["max_output_tokens"]), saved_profiles.get(task, "standard")),
            "quality_profile": normalize_quality(saved_profiles.get(task, "standard")),
            "quality_profiles": quality_options(task, int(config["max_output_tokens"])),
        }
    return {"local_only": local_only, "eligible_models": models, "tasks": tasks, "monthly_budget_eur": cfg.get("ai_monthly_budget_eur")}


# Background endpoints are used by alpha.5 UI so long local-model generations survive reloads and proxy timeouts.
@router.post("/chat/jobs")
async def queue_coach_chat(payload: ChatRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    if payload.conversation_id:
        conversation = await db.get(Conversation, payload.conversation_id)
        if not conversation or conversation.user_id != user.id:
            raise HTTPException(404, "CONVERSATION_NOT_FOUND")
    else:
        conversation = Conversation(user_id=user.id, title=payload.message[:80])
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        payload.conversation_id = conversation.id
    task = coach_chat_task.delay(str(user.id), payload.model_dump(mode="json"))
    db.add(BackgroundJob(id=uuid.UUID(task.id), user_id=user.id, job_type="coach_chat", payload={"conversation_id": str(conversation.id)}))
    await db.commit()
    return {"task_id": task.id, "status": "queued", "conversation_id": str(conversation.id)}


@router.post("/activity-analysis/jobs")
async def queue_activity_analysis(payload: ActivityAnalysisRequest, user: User = Depends(safety_confirmed_user)):
    task = activity_analysis_task.delay(str(user.id), payload.model_dump(mode="json"))
    return {"task_id": task.id, "status": "queued"}


@router.post("/training-plan/jobs")
async def queue_training_plan(
    payload: TrainingPlanRequest,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    # Prevent accidental duplicate plans when a user reloads the page, opens a
    # second tab/browser window, or clicks create again while Celery is still
    # working. Only recent tracked jobs are considered because expired Celery
    # results otherwise look like PENDING again.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    recent = (
        await db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.user_id == user.id,
                BackgroundJob.job_type.in_(["training_plan", "ai_continuation"]),
                BackgroundJob.created_at >= cutoff,
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(20)
        )
    ).all()
    for row in recent:
        if row.job_type == "ai_continuation":
            current = await db.get(AiRun, uuid.UUID(row.payload["run_id"]))
            if not current or current.task_type != "training_plan":
                continue
        if row.status in {"cancel_requested", "cancelled", "failed", "finished"}:
            continue
        existing = AsyncResult(str(row.id), app=celery_app)
        if not existing.ready() and existing.state not in {"FAILURE", "REVOKED"}:
            existing_payload = row.payload if isinstance(row.payload, dict) else {}
            return {
                "task_id": str(row.id),
                "status": "already_running",
                "resumed": True,
                "summary": {key: existing_payload.get(key) for key in ("goal_type", "goal_text", "weeks", "days_per_week", "session_minutes", "start_date", "model_id")},
            }

    payload_json = payload.model_dump(mode="json")
    task = training_plan_task.delay(str(user.id), payload_json)
    db.add(BackgroundJob(id=uuid.UUID(task.id), user_id=user.id, job_type="training_plan", payload=payload_json))
    await db.commit()
    return {
        "task_id": task.id,
        "status": "queued",
        "resumed": False,
        "summary": {key: payload_json.get(key) for key in ("goal_type", "goal_text", "weeks", "days_per_week", "session_minutes", "start_date", "model_id")},
    }


# Synchronous compatibility endpoints remain available for API clients.
@router.post("/chat")
async def coach_chat(payload: ChatRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    from worker.tasks.ai import _coach_chat
    try:
        return await _coach_chat(str(user.id), {**payload.model_dump(mode="json"), "locale": payload.locale or user.locale}, db_override=db)
    except RuntimeError as exc:
        raise HTTPException(status_code=404 if str(exc) == "CONVERSATION_NOT_FOUND" else 409, detail=str(exc)) from exc


@router.post("/activity-analysis")
async def activity_analysis(payload: ActivityAnalysisRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    from worker.tasks.ai import _activity_analysis
    try:
        return await _activity_analysis(str(user.id), {**payload.model_dump(mode="json"), "locale": payload.locale or user.locale}, db_override=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/activity-analysis/{activity_id}")
async def activity_analysis_history(
    activity_id: uuid.UUID,
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.scalars(select(AiRun).where(
        AiRun.user_id == user.id, AiRun.activity_id == activity_id, AiRun.task_type == "activity_analysis",
    ).order_by(AiRun.created_at.desc()).limit(limit))).all()
    return [_run_payload(x) for x in rows]


@router.delete("/ai-runs/{run_id}")
async def delete_ai_run(
    run_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a stored AI analysis owned by the current user.

    Training plans use their dedicated delete endpoints because exported Garmin
    calendar entries may need explicit cleanup before the local run disappears.
    """
    run = await db.get(AiRun, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="AI_RUN_NOT_FOUND")
    if run.task_type == "training_plan":
        raise HTTPException(status_code=409, detail="USE_TRAINING_PLAN_DELETE")
    await db.delete(run)
    await db.commit()
    return {"deleted": True, "run_id": str(run_id)}


@router.post("/training-plan")
async def training_plan(payload: TrainingPlanRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    from worker.tasks.ai import _training_plan
    try:
        return await _training_plan(str(user.id), {**payload.model_dump(mode="json"), "locale": payload.locale or user.locale}, db_override=db)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/training-plans")
async def training_plan_history(
    limit: int = Query(default=10, ge=1, le=30),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.scalars(select(AiRun).where(
        AiRun.user_id == user.id, AiRun.task_type == "training_plan",
    ).order_by(AiRun.created_at.desc()).limit(limit))).all()
    return [_run_payload(x) for x in rows]


@router.get("/training-plans/{run_id}/delete-info")
async def training_plan_delete_info(
    run_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AiRun, run_id)
    if not run or run.user_id != user.id or run.task_type != "training_plan":
        raise HTTPException(status_code=404, detail="TRAINING_PLAN_NOT_FOUND")
    exports = (await db.scalars(select(GarminWorkoutExport).where(
        GarminWorkoutExport.user_id == user.id,
        GarminWorkoutExport.plan_run_id == run.id,
    ))).all()
    remote = [row for row in exports if row.workout_id or row.scheduled_workout_id]
    return {
        "plan_run_id": str(run.id),
        "garmin_exports": len(exports),
        "garmin_exported": len(remote),
        "has_garmin_calendar_entries": any(bool(row.scheduled_workout_id) for row in remote),
    }


@router.delete("/training-plans/{run_id}")
async def delete_training_plan_local(
    run_id: uuid.UUID,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the local plan only. Garmin entries are intentionally untouched.

    The Garmin export ledger cascades with the AI run, so the UI asks the user
    first whether remote calendar/workout cleanup is desired.
    """
    run = await db.get(AiRun, run_id)
    if not run or run.user_id != user.id or run.task_type != "training_plan":
        raise HTTPException(status_code=404, detail="TRAINING_PLAN_NOT_FOUND")
    from pengucoach.coach.execution import remove_plan_analyses
    await remove_plan_analyses(db, user.id, run.id)
    await db.delete(run)
    await db.commit()
    return {"deleted": True, "plan_run_id": str(run_id), "garmin_untouched": True}


@router.get("/context-preview")
async def context_preview(
    days: int = Query(default=7, ge=1, le=28),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    """Counts/provenance only. No model call, credentials or raw provider payloads."""
    context = await build_training_plan_context(db, user, days)
    lookback = context["lookback"]
    categories = {}
    def describe(key, rows, fields=None):
        selected = [r for r in rows if fields is None or any(r.get(f) is not None for f in fields)]
        origins = set()
        for r in selected:
            sources = r.get("sources") or {}
            if fields is not None:
                origins.update(sources.get(f, r.get("source", "unknown")) for f in fields if r.get(f) is not None)
            else:
                origins.update(sources.values() or [r.get("source", "unknown")])
        categories[key] = {"count": len(selected), "sources": sorted(x for x in origins if x)}
    describe("training", [a["summary"] for a in lookback.get("activities", [])])
    categories["training"]["count"] = lookback.get("summary_period", {}).get("activity_count", 0)
    daily = lookback.get("daily_health", [])
    describe("recovery", daily, ("resting_hr_bpm", "stress_avg", "body_battery_high", "training_readiness"))
    describe("daily_activity", daily, ("steps", "distance_m", "active_calories_kcal"))
    describe("hydration", daily, ("hydration_ml", "hydration_goal_ml"))
    describe("sleep_hrv", lookback.get("sleep", []) + lookback.get("hrv", []))
    body = (lookback.get("body_profile") or {}).get("latest")
    describe("body", [body] if body else [])
    zones = context.get("training_zones") or {}
    categories["zones"] = {"count": sum(int((zones.get(k) or {}).get("profile_count", 0)) for k in ("heart_rate", "power")), "sources": ["garmin"] if zones.get("available") or zones.get("synced") else []}
    return {"days": lookback["days"], "categories": categories}
