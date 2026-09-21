import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.context import SOURCE_NOTICE, build_activity_analysis_context, build_coach_context, build_training_plan_context
from pengucoach.db.models import AiRun, Conversation, Message, User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.llm.service import chat, eligible_models, resolve_model, task_settings
from worker.tasks.ai import activity_analysis as activity_analysis_task
from worker.tasks.ai import coach_chat as coach_chat_task
from worker.tasks.ai import training_plan as training_plan_task

router = APIRouter(prefix="/coach", tags=["coach"])
TASKS = ("coach_chat", "activity_analysis", "training_plan")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=8192)
    context_window_tokens: int | None = Field(default=None, ge=2048, le=262144)
    context_mode: Literal["auto", "none", "7", "28"] = "auto"
    locale: Literal["de", "en"] | None = None


class ActivityAnalysisRequest(BaseModel):
    activity_id: uuid.UUID
    lookback_days: Literal[0, 3, 7] = 7
    prompt: str | None = Field(default=None, max_length=16000)
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=8192)
    context_window_tokens: int | None = Field(default=None, ge=2048, le=262144)
    locale: Literal["de", "en"] | None = None


class TrainingPlanRequest(BaseModel):
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
    max_tokens: int | None = Field(default=None, ge=128, le=8192)
    context_window_tokens: int | None = Field(default=None, ge=2048, le=262144)
    locale: Literal["de", "en"] | None = None


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
        "metadata": row.metadata_json,
        "created_at": row.created_at,
    }


def _answer_metadata(answer: dict, *, locale: str, goal: dict | None = None) -> dict:
    value = {
        "usage": answer.get("usage", {}),
        "context_chars": answer.get("context_chars"),
        "context_estimated_tokens": answer.get("context_estimated_tokens"),
        "context_window_tokens": answer.get("context_window_tokens"),
        "context_budget_tokens": answer.get("context_budget_tokens"),
        "context_truncated": answer.get("context_truncated", False),
        "stop_reason": answer.get("stop_reason"),
        "truncated": answer.get("truncated", False),
        "local": answer.get("local"),
        "locale": locale,
    }
    if goal is not None:
        value["goal"] = goal
    return value


def _auto_context_days(message: str) -> int:
    text = message.lower()
    terms = (
        "training", "workout", "lauf", "running", "rennrad", "rad", "cycling", "bike", "herz", "heart",
        "hrv", "puls", "power", "leistung", "pace", "schlaf", "sleep", "recovery", "erholung", "belastung",
        "load", "fitness", "vo2", "kadenz", "cadence", "garmin", "muskel", "strength", "kraft", "ausdauer",
        "endurance", "form", "trainingsplan", "training plan",
    )
    return 28 if any(term in text for term in terms) else 0


@router.get("/capabilities")
async def capabilities(
    locale: Literal["de", "en"] | None = Query(default=None),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    _, local_only = await _privacy(db, user)
    models = await eligible_models(db, local_only=local_only)
    tasks: dict[str, dict] = {}
    selected_locale = locale or user.locale
    for task in TASKS:
        config = await task_settings(db, task, selected_locale)
        selected = await resolve_model(db, task, local_only=local_only)
        tasks[task] = {
            "default_model_id": str(selected[1].id) if selected else None,
            "default_model": selected[1].display_name if selected else None,
            "default_provider": selected[0].name if selected else None,
            "local": selected[0].is_local if selected else None,
            **config,
        }
    return {"local_only": local_only, "eligible_models": models, "tasks": tasks}


# Background endpoints are used by alpha.5 UI so long local-model generations survive reloads and proxy timeouts.
@router.post("/chat/jobs")
async def queue_coach_chat(payload: ChatRequest, user: User = Depends(safety_confirmed_user)):
    task = coach_chat_task.delay(str(user.id), payload.model_dump(mode="json"))
    return {"task_id": task.id, "status": "queued"}


@router.post("/activity-analysis/jobs")
async def queue_activity_analysis(payload: ActivityAnalysisRequest, user: User = Depends(safety_confirmed_user)):
    task = activity_analysis_task.delay(str(user.id), payload.model_dump(mode="json"))
    return {"task_id": task.id, "status": "queued"}


@router.post("/training-plan/jobs")
async def queue_training_plan(payload: TrainingPlanRequest, user: User = Depends(safety_confirmed_user)):
    task = training_plan_task.delay(str(user.id), payload.model_dump(mode="json"))
    return {"task_id": task.id, "status": "queued"}


# Synchronous compatibility endpoints remain available for API clients.
@router.post("/chat")
async def coach_chat(payload: ChatRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    locale = payload.locale or user.locale
    conversation = await db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if conversation and conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    if not conversation:
        conversation = Conversation(user_id=user.id, title=payload.message[:80])
        db.add(conversation)
        await db.flush()
    db.add(Message(conversation_id=conversation.id, role="user", content=payload.message))
    await db.flush()
    rows = (await db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at))).all()
    messages = [{"role": x.role, "content": x.content} for x in rows]
    if payload.context_mode == "none":
        context_days = 0
    elif payload.context_mode in {"7", "28"}:
        context_days = int(payload.context_mode)
    else:
        context_days = _auto_context_days(payload.message)
    context = await build_coach_context(db, user, context_days) if context_days else {
        "source_notice": SOURCE_NOTICE, "period_days": 0, "note": "No training context required for this question."
    }
    _, local_only = await _privacy(db, user)
    try:
        answer = await chat(
            db, messages, context, locale, local_only=local_only,
            model_id=payload.model_id, requested_max_tokens=payload.max_tokens,
            requested_context_window_tokens=payload.context_window_tokens,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer["content"], model_id=uuid.UUID(answer["model_id"])))
    await db.commit()
    return {
        "conversation_id": str(conversation.id), **answer,
        "data_used": {
            "context_days": context_days,
            "health_days": len(context.get("health_30d", [])),
            "sleep_days": len(context.get("sleep_30d", [])),
            "hrv_days": len(context.get("hrv_30d", [])),
            "activities": len(context.get("recent_activities", [])),
        },
    }


@router.post("/activity-analysis")
async def activity_analysis(payload: ActivityAnalysisRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    locale = payload.locale or user.locale
    try:
        context = await build_activity_analysis_context(db, user, payload.activity_id, payload.lookback_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _, local_only = await _privacy(db, user)
    config = await task_settings(db, "activity_analysis", locale)
    prompt = (payload.prompt or config["default_prompt"]).strip()
    user_message = (
        f"Analysiere Aktivität {payload.activity_id} mit {payload.lookback_days} Tagen Rückblick." if str(locale).startswith("de") else
        f"Analyse activity {payload.activity_id} with {payload.lookback_days} days of lookback context."
    )
    try:
        answer = await chat(
            db, [{"role": "user", "content": user_message}], context, locale,
            task="activity_analysis", local_only=local_only, model_id=payload.model_id,
            instruction_prompt=prompt, requested_max_tokens=payload.max_tokens,
            requested_context_window_tokens=payload.context_window_tokens,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = AiRun(
        user_id=user.id, task_type="activity_analysis", activity_id=payload.activity_id,
        model_id=uuid.UUID(answer["model_id"]), provider_name=answer["provider"], model_name=answer["model"],
        prompt=prompt, lookback_days=payload.lookback_days, max_output_tokens=answer["max_output_tokens"],
        content=answer["content"], metadata_json=_answer_metadata(answer, locale=str(locale)),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": str(run.id), **answer, "lookback_days": payload.lookback_days, "created_at": run.created_at}


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


@router.post("/training-plan")
async def training_plan(payload: TrainingPlanRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    locale = payload.locale or user.locale
    context = await build_training_plan_context(db, user, days=28)
    context["goal"] = {
        "goal_type": payload.goal_type, "goal_text": payload.goal_text, "experience": payload.experience,
        "weeks": payload.weeks, "days_per_week": payload.days_per_week, "session_minutes": payload.session_minutes,
        "equipment": payload.equipment, "constraints": payload.constraints, "source": "user",
    }
    _, local_only = await _privacy(db, user)
    config = await task_settings(db, "training_plan", locale)
    prompt = (payload.prompt or config["default_prompt"]).strip()
    user_message = (
        f"Erstelle einen {payload.weeks}-Wochen-Trainingsplan für {payload.goal_type}." if str(locale).startswith("de") else
        f"Create a {payload.weeks}-week training plan for {payload.goal_type}."
    )
    try:
        answer = await chat(
            db, [{"role": "user", "content": user_message}], context, locale,
            task="training_plan", local_only=local_only, model_id=payload.model_id,
            instruction_prompt=prompt, requested_max_tokens=payload.max_tokens,
            requested_context_window_tokens=payload.context_window_tokens,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = AiRun(
        user_id=user.id, task_type="training_plan", model_id=uuid.UUID(answer["model_id"]),
        provider_name=answer["provider"], model_name=answer["model"], prompt=prompt, lookback_days=28,
        max_output_tokens=answer["max_output_tokens"], content=answer["content"],
        metadata_json=_answer_metadata(answer, locale=str(locale), goal=context["goal"]),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": str(run.id), **answer, "goal": context["goal"], "created_at": run.created_at}


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
