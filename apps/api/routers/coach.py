import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.context import build_activity_analysis_context, build_coach_context, build_training_plan_context
from pengucoach.db.models import AiRun, Conversation, Message, User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.llm.service import chat, eligible_models, resolve_model, task_settings

router = APIRouter(prefix="/coach", tags=["coach"])
TASKS = ("coach_chat", "activity_analysis", "training_plan")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=8192)


class ActivityAnalysisRequest(BaseModel):
    activity_id: uuid.UUID
    lookback_days: Literal[0, 3, 7] = 7
    prompt: str | None = Field(default=None, max_length=16000)
    model_id: uuid.UUID | None = None
    max_tokens: int | None = Field(default=None, ge=128, le=8192)


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


@router.get("/capabilities")
async def capabilities(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    _, local_only = await _privacy(db, user)
    models = await eligible_models(db, local_only=local_only)
    tasks: dict[str, dict] = {}
    for task in TASKS:
        config = await task_settings(db, task)
        selected = await resolve_model(db, task, local_only=local_only)
        tasks[task] = {
            "default_model_id": str(selected[1].id) if selected else None,
            "default_model": selected[1].display_name if selected else None,
            "default_provider": selected[0].name if selected else None,
            "local": selected[0].is_local if selected else None,
            **config,
        }
    return {"local_only": local_only, "eligible_models": models, "tasks": tasks}


@router.post("/chat")
async def coach_chat(payload: ChatRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
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
    context = await build_coach_context(db, user)
    _, local_only = await _privacy(db, user)
    try:
        answer = await chat(
            db, messages, context, user.locale, local_only=local_only,
            model_id=payload.model_id, requested_max_tokens=payload.max_tokens,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer["content"], model_id=uuid.UUID(answer["model_id"])))
    await db.commit()
    return {
        "conversation_id": str(conversation.id),
        **answer,
        "data_used": {
            "health_days": len(context["health_30d"]),
            "sleep_days": len(context["sleep_30d"]),
            "hrv_days": len(context["hrv_30d"]),
            "activities": len(context["recent_activities"]),
        },
    }


@router.post("/activity-analysis")
async def activity_analysis(payload: ActivityAnalysisRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    try:
        context = await build_activity_analysis_context(db, user, payload.activity_id, payload.lookback_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _, local_only = await _privacy(db, user)
    config = await task_settings(db, "activity_analysis")
    prompt = (payload.prompt or config["default_prompt"]).strip()
    user_message = (
        f"Analyse activity {payload.activity_id}. Look back {payload.lookback_days} days as supplied in the context. "
        "Use the requested deep-analysis structure and conclude with a practical next-session recommendation."
    )
    try:
        answer = await chat(
            db,
            [{"role": "user", "content": user_message}],
            context,
            user.locale,
            task="activity_analysis",
            local_only=local_only,
            model_id=payload.model_id,
            instruction_prompt=prompt,
            requested_max_tokens=payload.max_tokens,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = AiRun(
        user_id=user.id,
        task_type="activity_analysis",
        activity_id=payload.activity_id,
        model_id=uuid.UUID(answer["model_id"]),
        provider_name=answer["provider"],
        model_name=answer["model"],
        prompt=prompt,
        lookback_days=payload.lookback_days,
        max_output_tokens=answer["max_output_tokens"],
        content=answer["content"],
        metadata_json={
            "usage": answer.get("usage", {}),
            "context_chars": answer.get("context_chars"),
            "context_estimated_tokens": answer.get("context_estimated_tokens"),
            "context_truncated": answer.get("context_truncated", False),
            "local": answer.get("local"),
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": str(run.id), **answer, "lookback_days": payload.lookback_days}


@router.get("/activity-analysis/{activity_id}")
async def activity_analysis_history(
    activity_id: uuid.UUID,
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.scalars(select(AiRun).where(
        AiRun.user_id == user.id,
        AiRun.activity_id == activity_id,
        AiRun.task_type == "activity_analysis",
    ).order_by(AiRun.created_at.desc()).limit(limit))).all()
    return [_run_payload(x) for x in rows]


@router.post("/training-plan")
async def training_plan(payload: TrainingPlanRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    context = await build_training_plan_context(db, user, days=28)
    context["goal"] = {
        "goal_type": payload.goal_type,
        "goal_text": payload.goal_text,
        "experience": payload.experience,
        "weeks": payload.weeks,
        "days_per_week": payload.days_per_week,
        "session_minutes": payload.session_minutes,
        "equipment": payload.equipment,
        "constraints": payload.constraints,
        "source": "user",
    }
    _, local_only = await _privacy(db, user)
    config = await task_settings(db, "training_plan")
    prompt = (payload.prompt or config["default_prompt"]).strip()
    user_message = (
        f"Create a {payload.weeks}-week training plan for goal '{payload.goal_type}', "
        f"{payload.days_per_week} training days per week and about {payload.session_minutes} minutes per session. "
        f"User goal details: {payload.goal_text or 'none supplied'}. Equipment: {payload.equipment or 'not specified'}. "
        f"Constraints: {payload.constraints or 'none supplied'}. Experience: {payload.experience}."
    )
    try:
        answer = await chat(
            db,
            [{"role": "user", "content": user_message}],
            context,
            user.locale,
            task="training_plan",
            local_only=local_only,
            model_id=payload.model_id,
            instruction_prompt=prompt,
            requested_max_tokens=payload.max_tokens,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = AiRun(
        user_id=user.id,
        task_type="training_plan",
        model_id=uuid.UUID(answer["model_id"]),
        provider_name=answer["provider"],
        model_name=answer["model"],
        prompt=prompt,
        lookback_days=28,
        max_output_tokens=answer["max_output_tokens"],
        content=answer["content"],
        metadata_json={
            "goal": context["goal"],
            "usage": answer.get("usage", {}),
            "context_chars": answer.get("context_chars"),
            "context_estimated_tokens": answer.get("context_estimated_tokens"),
            "context_truncated": answer.get("context_truncated", False),
            "local": answer.get("local"),
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": str(run.id), **answer, "goal": context["goal"]}


@router.get("/training-plans")
async def training_plan_history(
    limit: int = Query(default=10, ge=1, le=30),
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.scalars(select(AiRun).where(
        AiRun.user_id == user.id,
        AiRun.task_type == "training_plan",
    ).order_by(AiRun.created_at.desc()).limit(limit))).all()
    return [_run_payload(x) for x in rows]
