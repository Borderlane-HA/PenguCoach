from __future__ import annotations

import asyncio
import uuid

import httpx
from typing import Any

from celery import states
from sqlalchemy import select

from pengucoach.coach.context import SOURCE_NOTICE, build_activity_analysis_context, build_coach_context, build_training_plan_context
from pengucoach.db.models import AiRun, Conversation, Message, User, UserPreference
from pengucoach.db.session import SessionLocal
from pengucoach.llm.service import chat, task_settings
from pengucoach.training_plan.generation import normalize_training_plan_answer, training_plan_instruction
from worker.celery_app import app


def _u(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _analysis_scope_message(activity_id: uuid.UUID, days: int, locale: str) -> str:
    de = locale.startswith("de")
    labels = {
        0: ("nur diesem Training", "this training session only"),
        1: ("dem Kontext dieses Tages", "this day\'s context"),
        3: ("dem 3-Tage-Kontext", "the 3-day context"),
        7: ("dem 7-Tage-Kontext inklusive 3-Tage-Vergleich", "the 7-day context including the 3-day comparison"),
    }
    label = labels.get(days, labels[7])[0 if de else 1]
    return (f"Analysiere die Aktivität {activity_id} mit {label}." if de else f"Analyse activity {activity_id} using {label}.")


async def _privacy(db, user: User) -> bool:
    pref = await db.get(UserPreference, user.id)
    return True if not pref else (pref.local_ai_only or not pref.cloud_health_ai_allowed)


def _auto_context_days(message: str) -> int:
    text = message.lower()
    training_terms = (
        "training", "trainings", "workout", "lauf", "running", "run ", "rennrad", "rad", "cycling", "bike",
        "herz", "heart", "hrv", "puls", "power", "leistung", "pace", "schlaf", "sleep", "recovery",
        "erholung", "belastung", "load", "fitness", "vo2", "kadenz", "cadence", "garmin", "fit ",
        "muskel", "strength", "kraft", "ausdauer", "endurance", "form", "training plan", "trainingsplan",
    )
    return 28 if any(term in text for term in training_terms) else 0


async def _activity_analysis(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        locale = str(payload.get("locale") or user.locale or "de")
        activity_id = uuid.UUID(str(payload["activity_id"]))
        lookback_days = int(payload.get("lookback_days", 7))
        context = await build_activity_analysis_context(db, user, activity_id, lookback_days)
        local_only = await _privacy(db, user)
        config = await task_settings(db, "activity_analysis", locale)
        prompt = str(payload.get("prompt") or config["default_prompt"]).strip()
        user_message = _analysis_scope_message(activity_id, lookback_days, locale)
        answer = await chat(
            db,
            [{"role": "user", "content": user_message}],
            context,
            locale,
            task="activity_analysis",
            local_only=local_only,
            model_id=_u(payload.get("model_id")),
            instruction_prompt=prompt,
            requested_max_tokens=payload.get("max_tokens"),
            requested_context_window_tokens=payload.get("context_window_tokens"),
        )
        run = AiRun(
            user_id=user.id,
            task_type="activity_analysis",
            activity_id=activity_id,
            model_id=uuid.UUID(answer["model_id"]),
            provider_name=answer["provider"],
            model_name=answer["model"],
            prompt=prompt,
            lookback_days=lookback_days,
            max_output_tokens=answer["max_output_tokens"],
            content=answer["content"],
            metadata_json={
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
            },
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return {"run_id": str(run.id), **answer, "lookback_days": lookback_days, "created_at": run.created_at.isoformat()}


async def _coach_chat(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        locale = str(payload.get("locale") or user.locale or "de")
        message = str(payload["message"]).strip()
        conversation_id = _u(payload.get("conversation_id"))
        conversation = await db.get(Conversation, conversation_id) if conversation_id else None
        if conversation and conversation.user_id != user.id:
            raise RuntimeError("CONVERSATION_NOT_FOUND")
        if not conversation:
            conversation = Conversation(user_id=user.id, title=message[:80])
            db.add(conversation)
            await db.flush()
        db.add(Message(conversation_id=conversation.id, role="user", content=message))
        await db.flush()
        rows = (await db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at))).all()
        messages = [{"role": x.role, "content": x.content} for x in rows]

        context_mode = str(payload.get("context_mode") or "auto")
        if context_mode == "none":
            context_days = 0
        elif context_mode in {"7", "28"}:
            context_days = int(context_mode)
        else:
            context_days = _auto_context_days(message)
        if context_days:
            context = await build_coach_context(db, user, days=context_days)
        else:
            context = {"source_notice": SOURCE_NOTICE, "period_days": 0, "note": "No training context required for this question."}

        local_only = await _privacy(db, user)
        answer = await chat(
            db,
            messages,
            context,
            locale,
            task="coach_chat",
            local_only=local_only,
            model_id=_u(payload.get("model_id")),
            requested_max_tokens=payload.get("max_tokens"),
            requested_context_window_tokens=payload.get("context_window_tokens"),
        )
        db.add(Message(conversation_id=conversation.id, role="assistant", content=answer["content"], model_id=uuid.UUID(answer["model_id"])))
        await db.commit()
        data_used = {
            "context_days": context_days,
            "activities": len(context.get("recent_activities", [])),
            "health_days": len(context.get("health_30d", [])),
            "sleep_days": len(context.get("sleep_30d", [])),
            "hrv_days": len(context.get("hrv_30d", [])),
        }
        return {"conversation_id": str(conversation.id), **answer, "data_used": data_used}


async def _training_plan(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        locale = str(payload.get("locale") or user.locale or "de")
        context = await build_training_plan_context(db, user, days=28)
        context["goal"] = {
            "goal_type": payload.get("goal_type", "hybrid"),
            "goal_text": payload.get("goal_text", ""),
            "experience": payload.get("experience", "intermediate"),
            "weeks": int(payload.get("weeks", 8)),
            "days_per_week": int(payload.get("days_per_week", 4)),
            "session_minutes": int(payload.get("session_minutes", 60)),
            "equipment": payload.get("equipment", ""),
            "constraints": payload.get("constraints", ""),
            "source": "user",
        }
        local_only = await _privacy(db, user)
        config = await task_settings(db, "training_plan", locale)
        prompt = str(payload.get("prompt") or config["default_prompt"]).strip()
        g = context["goal"]
        if locale.startswith("de"):
            user_message = (
                f"Erstelle einen {g['weeks']}-Wochen-Trainingsplan für '{g['goal_type']}', "
                f"{g['days_per_week']} Trainingstage pro Woche, etwa {g['session_minutes']} Minuten pro Einheit. "
                f"Ziel: {g['goal_text'] or 'keine Zusatzangabe'}. Equipment: {g['equipment'] or 'nicht angegeben'}. "
                f"Einschränkungen: {g['constraints'] or 'keine'}. Erfahrung: {g['experience']}."
            )
        else:
            user_message = (
                f"Create a {g['weeks']}-week training plan for goal '{g['goal_type']}', "
                f"{g['days_per_week']} training days per week and about {g['session_minutes']} minutes per session. "
                f"Goal details: {g['goal_text'] or 'none supplied'}. Equipment: {g['equipment'] or 'not specified'}. "
                f"Constraints: {g['constraints'] or 'none supplied'}. Experience: {g['experience']}."
            )
        answer = await chat(
            db,
            [{"role": "user", "content": user_message}],
            context,
            locale,
            task="training_plan",
            local_only=local_only,
            model_id=_u(payload.get("model_id")),
            instruction_prompt=training_plan_instruction(prompt),
            requested_max_tokens=payload.get("max_tokens"),
            requested_context_window_tokens=payload.get("context_window_tokens"),
        )
        content, plan_meta = normalize_training_plan_answer(answer, locale)
        metadata = {
            "goal": context["goal"],
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
            **plan_meta,
        }
        run = AiRun(
            user_id=user.id,
            task_type="training_plan",
            model_id=uuid.UUID(answer["model_id"]),
            provider_name=answer["provider"],
            model_name=answer["model"],
            prompt=prompt,
            lookback_days=28,
            max_output_tokens=answer["max_output_tokens"],
            content=content,
            metadata_json=metadata,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return {
            "run_id": str(run.id),
            **answer,
            "content": content,
            "metadata": metadata,
            "goal": context["goal"],
            "created_at": run.created_at.isoformat(),
        }


@app.task(bind=True, name="worker.tasks.ai.activity_analysis")
def activity_analysis(self, user_id: str, payload: dict[str, Any]):
    self.update_state(state="PROGRESS", meta={"stage": "analysis", "message": "AI analysis is running"})
    return asyncio.run(_activity_analysis(user_id, payload))


@app.task(bind=True, name="worker.tasks.ai.coach_chat")
def coach_chat(self, user_id: str, payload: dict[str, Any]):
    self.update_state(state="PROGRESS", meta={"stage": "generation", "message": "Coach is generating a response"})
    return asyncio.run(_coach_chat(user_id, payload))


@app.task(bind=True, name="worker.tasks.ai.training_plan")
def training_plan(self, user_id: str, payload: dict[str, Any]):
    self.update_state(state="PROGRESS", meta={"stage": "planning", "message": "Training plan is being generated"})
    try:
        return asyncio.run(_training_plan(user_id, payload))
    except httpx.HTTPError as exc:
        # A local/OpenAI-compatible model endpoint can transiently reset or time
        # out during a long structured generation. Retry once; structured-format
        # validation errors do not raise here and therefore are never retried.
        if self.request.retries < 1:
            self.update_state(state="PROGRESS", meta={"stage": "planning_retry", "message": "AI endpoint interrupted · retrying once"})
            raise self.retry(exc=exc, countdown=5, max_retries=1)
        raise
