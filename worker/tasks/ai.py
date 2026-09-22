from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select

from pengucoach.coach.context import SOURCE_NOTICE, build_activity_analysis_context, build_coach_context, build_training_plan_context
from pengucoach.db.models import AiRun, Conversation, Message, User, UserPreference
from pengucoach.db.session import SessionLocal
from pengucoach.llm.job_control import cancel_requested, clear_cancel
from pengucoach.llm.service import AiGenerationCancelled, chat, task_settings
from pengucoach.training_plan.generation import normalize_training_plan_answer, training_plan_instruction
from worker.celery_app import app

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


def _u(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _analysis_scope_message(activity_id: uuid.UUID, days: int, locale: str) -> str:
    de = locale.startswith("de")
    labels = {
        0: ("nur diesem Training", "this training session only"),
        1: ("dem Kontext dieses Tages", "this day's context"),
        3: ("dem 3-Tage-Kontext", "the 3-day context"),
        7: ("dem 7-Tage-Kontext inklusive 3-Tage-Vergleich", "the 7-day context including the 3-day comparison"),
    }
    label = labels.get(days, labels[7])[0 if de else 1]
    return f"Analysiere die Aktivität {activity_id} mit {label}." if de else f"Analyse activity {activity_id} using {label}."


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


def _context_selection(payload: dict[str, Any]) -> dict[str, bool]:
    raw = payload.get("context_data") if isinstance(payload.get("context_data"), dict) else {}
    return {
        "include_training": bool(raw.get("training", True)),
        "include_zones": bool(raw.get("zones", True)),
        "include_sleep_hrv": bool(raw.get("sleep_hrv", True)),
        "include_recovery": bool(raw.get("recovery", True)),
        "include_daily_activity": bool(raw.get("daily_activity", False)),
    }


def _progress_callback(task, payload: dict[str, Any], kind: str) -> ProgressCallback:
    de = str(payload.get("locale") or "de").startswith("de")
    labels = {
        "analysis": ("KI-Analyse wird erstellt", "AI analysis is being generated"),
        "coach": ("Coach erstellt die Antwort", "Coach is generating the response"),
        "plan": ("Trainingsplan wird erstellt", "Training plan is being generated"),
    }
    base = labels[kind][0 if de else 1]

    def emit(meta: dict[str, Any]) -> None:
        stage = str(meta.get("stage") or "generation")
        if stage == "connecting":
            message = f"{base} · Modell wird vorbereitet" if de else f"{base} · preparing model"
        elif stage == "finalizing":
            message = f"{base} · wird abgeschlossen" if de else f"{base} · finalizing"
        else:
            message = base
        task.update_state(state="PROGRESS", meta={**meta, "message": message})

    return emit


def _cancel_check(task_id: str) -> CancelCheck:
    return lambda: cancel_requested(task_id)


async def _activity_analysis(
    user_id: str,
    payload: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
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
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        if cancel_check and cancel_check():
            raise AiGenerationCancelled("AI_JOB_CANCELLED")
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


async def _coach_chat(
    user_id: str,
    payload: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
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
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        if cancel_check and cancel_check():
            raise AiGenerationCancelled("AI_JOB_CANCELLED")
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


async def _training_plan(
    user_id: str,
    payload: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        locale = str(payload.get("locale") or user.locale or "de")
        context_days = int(payload.get("context_days") or 7)
        context_data = payload.get("context_data") if isinstance(payload.get("context_data"), dict) else {}
        context = await build_training_plan_context(db, user, days=context_days, **_context_selection(payload))
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
                f"Einschränkungen: {g['constraints'] or 'keine'}. Erfahrung: {g['experience']}. "
                f"Nutze ausschließlich den ausgewählten Trainingskontext der letzten {context_days} Tage."
            )
        else:
            user_message = (
                f"Create a {g['weeks']}-week training plan for goal '{g['goal_type']}', "
                f"{g['days_per_week']} training days per week and about {g['session_minutes']} minutes per session. "
                f"Goal details: {g['goal_text'] or 'none supplied'}. Equipment: {g['equipment'] or 'not specified'}. "
                f"Constraints: {g['constraints'] or 'none supplied'}. Experience: {g['experience']}. "
                f"Use only the selected training context from the last {context_days} days."
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
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        if cancel_check and cancel_check():
            raise AiGenerationCancelled("AI_JOB_CANCELLED")
        content, plan_meta = normalize_training_plan_answer(answer, locale)
        metadata = {
            "goal": context["goal"],
            "training_context": {"days": context_days, "data": context_data},
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
            lookback_days=context_days,
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


def _run_task(self, payload: dict[str, Any], kind: str, coro_factory):
    task_id = str(self.request.id)
    progress = _progress_callback(self, payload, kind)
    check_cancel = _cancel_check(task_id)
    progress({"stage": "queued", "output_tokens_estimate": 0, "output_tokens_exact": None})
    try:
        return asyncio.run(coro_factory(progress, check_cancel))
    except AiGenerationCancelled:
        return {"cancelled": True, "reason": "AI_JOB_CANCELLED"}
    except httpx.ReadTimeout as exc:
        raise RuntimeError(
            "AI_TIMEOUT: Das Modell hat zu lange keine Daten geliefert. Bei Ollama wird die Ausgabe gestreamt; "
            "prüfe Modell/Server, wenn dieser Fehler erneut auftritt."
        ) from exc
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
        if self.request.retries < 1 and not check_cancel():
            progress({"stage": "retry", "message": "AI endpoint interrupted · retrying once", "output_tokens_estimate": 0})
            raise self.retry(exc=exc, countdown=5, max_retries=1)
        raise RuntimeError(f"AI_CONNECTION_ERROR: {type(exc).__name__}: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        detail = exc.response.text[:300] if exc.response is not None else str(exc)
        raise RuntimeError(f"AI_HTTP_ERROR {code}: {detail}") from exc
    finally:
        clear_cancel(task_id)


@app.task(bind=True, name="worker.tasks.ai.activity_analysis")
def activity_analysis(self, user_id: str, payload: dict[str, Any]):
    return _run_task(
        self,
        payload,
        "analysis",
        lambda progress, check: _activity_analysis(
            user_id, payload, progress_callback=progress, cancel_check=check
        ),
    )


@app.task(bind=True, name="worker.tasks.ai.coach_chat")
def coach_chat(self, user_id: str, payload: dict[str, Any]):
    return _run_task(
        self,
        payload,
        "coach",
        lambda progress, check: _coach_chat(
            user_id, payload, progress_callback=progress, cancel_check=check
        ),
    )


@app.task(bind=True, name="worker.tasks.ai.training_plan")
def training_plan(self, user_id: str, payload: dict[str, Any]):
    return _run_task(
        self,
        payload,
        "plan",
        lambda progress, check: _training_plan(
            user_id, payload, progress_callback=progress, cancel_check=check
        ),
    )
