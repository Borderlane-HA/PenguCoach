from __future__ import annotations

import asyncio
import copy
import math
import uuid
from datetime import date, datetime, timezone
from collections.abc import Callable
from contextlib import asynccontextmanager
import time
from typing import Any

import httpx
from sqlalchemy import select

from pengucoach.coach.companion import add_personal_context, conversation_excerpt
from pengucoach.coach.context import SOURCE_NOTICE, build_activity_analysis_context, build_coach_context, build_training_plan_context
from pengucoach.db.models import AiRun, Conversation, Message, User, UserPreference
from pengucoach.db.session import SessionLocal
from pengucoach.llm.job_control import cancel_requested, clear_cancel
from pengucoach.llm.service import AiGenerationCancelled, AiProviderResponseError, OpenRouterError, chat, task_settings, resolve_model
from pengucoach.llm.continuation import public, json_value
from pengucoach.llm.usage import quality_budget, model_pricing, calculate_cost_eur
from pengucoach.training_plan.generation import merge_plan_segments, training_plan_instruction
from pengucoach.training_plan.structured import TrainingPlanDocument, extract_structured_plan, render_plan_markdown
from pengucoach.training_plan.schema import generation_schema
from pengucoach.weather.service import build_coach_weather_context, build_training_weather_context
from worker.celery_app import app

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


@asynccontextmanager
async def _session(db_override=None):
    if db_override is not None:
        yield db_override
    else:
        async with SessionLocal() as db:
            yield db


async def _tracked_chat(db, messages, context, locale, **kwargs):
    """Record unreported/billable interruptions as unknown, never zero-cost success."""
    try:
        return await chat(db, messages, context, locale, **kwargs)
    except (httpx.HTTPError, AiGenerationCancelled, AiProviderResponseError, OpenRouterError) as exc:
        if isinstance(exc, AiGenerationCancelled) and not exc.request_sent:
            raise
        selected = await resolve_model(db, kwargs.get("task", "coach_chat"),
            local_only=kwargs.get("local_only", False), model_id=kwargs.get("model_id"))
        if selected:
            provider, model = selected
            user_id = db.info.get("ai_user_id")
            if user_id:
                reported = exc.answer if isinstance(exc, AiGenerationCancelled) and exc.answer else {}
                if isinstance(exc, AiProviderResponseError) and exc.usage:
                    reported = {"usage": exc.usage, "usage_complete": all(isinstance(exc.usage.get(k), int) for k in ("input_tokens", "output_tokens"))}
                pricing = model_pricing(model.metadata_json or {})
                details = dict(user_id=user_id, task_type=kwargs.get("task", "coach_chat"), model_id=model.id,
                    provider_name=provider.name, model_name=model.display_name, prompt="Interrupted AI request", content="",
                    max_output_tokens=kwargs.get("requested_max_tokens"), metadata_json={"usage": reported.get("usage") or {
                        "input_tokens": None, "output_tokens": None, "total_tokens": None},
                        "usage_complete": reported.get("usage_complete", False), "pricing": pricing,
                        "cost_eur": reported.get("cost_eur", calculate_cost_eur(reported.get("usage"), pricing)), "request_status": "cancelled" if isinstance(exc, AiGenerationCancelled) else "failed",
                        "_usage_only": True, "error_code": type(exc).__name__})
                await db.rollback()
                db.add(AiRun(**details))
                await db.commit()
        raise


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


from pengucoach.coach.selection import auto_context_days, context_selection


def _auto_context_days(message: str) -> int:
    return auto_context_days(message)

def _context_selection(payload: dict[str, Any]) -> dict[str, bool]:
    return context_selection(payload)

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
        chunk_index = meta.get("chunk_index")
        chunk_count = meta.get("chunk_count")
        chunk = f" · Teil {chunk_index}/{chunk_count}" if de and chunk_index and chunk_count else (f" · part {chunk_index}/{chunk_count}" if chunk_index and chunk_count else "")
        attempt = meta.get("attempt")
        if isinstance(attempt, int) and attempt > 1:
            chunk += f" · Versuch {attempt} (erneut)" if de else f" · attempt {attempt} (retry)"
        if stage == "connecting":
            message = (f"{base}{chunk} · Modell wird vorbereitet" if de else f"{base}{chunk} · preparing model")
        elif stage == "finalizing":
            message = (f"{base}{chunk} · wird abgeschlossen" if de else f"{base}{chunk} · finalizing")
        else:
            message = f"{base}{chunk}"
        task.update_state(state="PROGRESS", meta={**meta, "message": message})

    return emit


def _cancel_check(task_id: str) -> CancelCheck:
    return lambda: cancel_requested(task_id)


def _answer_metadata(answer: dict[str, Any], locale: str, quality_profile: str, **extra: Any) -> dict[str, Any]:
    return {
        "_resume": answer.get("_resume"),
        "continuation": answer.get("continuation", {"available": False, "revision": 0}),
        "empty_due_to_limit": answer.get("empty_due_to_limit", False),
        "usage": answer.get("usage", {}),
        "usage_complete": answer.get("usage_complete", True),
        "messages_truncated": answer.get("messages_truncated", False),
        "provider_timing": answer.get("provider_timing", {}),
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
        "quality_profile": quality_profile,
        "pricing": answer.get("pricing"),
        "cost_eur": answer.get("cost_eur"),
        "elapsed_seconds": answer.get("elapsed_seconds"),
        "tokens_per_second": answer.get("tokens_per_second"),
        **extra,
    }


async def _activity_analysis(
    user_id: str,
    payload: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    db_override=None,
) -> dict[str, Any]:
    async with _session(db_override) as db:
        db.info["ai_user_id"] = uuid.UUID(user_id)
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
        answer = await _tracked_chat(
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
            quality_profile=str(payload.get("quality_profile") or "standard"),
            recover_limit=True,
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
            metadata_json=_answer_metadata(answer, locale, str(payload.get("quality_profile") or "standard")),

        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return {"run_id": str(run.id), **public(answer), "lookback_days": lookback_days, "created_at": run.created_at.isoformat()}


async def _coach_chat(
    user_id: str,
    payload: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    db_override=None,
) -> dict[str, Any]:
    async with _session(db_override) as db:
        db.info["ai_user_id"] = uuid.UUID(user_id)
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        locale = str(payload.get("locale") or user.locale or "de")
        message = str(payload["message"]).strip()
        conversation_id = _u(payload.get("conversation_id"))
        conversation = await db.get(Conversation, conversation_id) if conversation_id else None
        if conversation_id and (not conversation or conversation.user_id != user.id):
            raise RuntimeError("CONVERSATION_NOT_FOUND")
        if not conversation:
            conversation = Conversation(user_id=user.id, title=message[:80])
            db.add(conversation)
            await db.flush()
        db.add(Message(conversation_id=conversation.id, role="user", content=message, created_at=datetime.now(timezone.utc)))
        await db.flush()
        rows = await conversation_excerpt(db, conversation)
        messages = [{"role": x.role, "content": x.content} for x in rows]

        context_mode = str(payload.get("context_mode") or "auto")
        if context_mode == "none":
            context_days = 0
        elif context_mode in {"3", "7", "14", "21", "28"}:
            context_days = int(context_mode)
        else:
            context_days = _auto_context_days(message)
        if context_days:
            if context_selection(payload).get("include_training", True):
                from worker.tasks.execution import refresh_user
                await refresh_user(db, user)
            context = await build_coach_context(db, user, days=context_days, **context_selection(payload))
        else:
            context = {"source_notice": SOURCE_NOTICE, "period_days": 0, "note": "No training context required for this question."}

        await add_personal_context(db, user, context, payload, conversation)
        weather_context = await build_coach_weather_context(db, user, message)
        if weather_context is not None:
            context["weather_forecast"] = weather_context
        local_only = await _privacy(db, user)
        answer = await _tracked_chat(
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
            quality_profile=str(payload.get("quality_profile") or "standard"),
            recover_limit=True,
        )
        if cancel_check and cancel_check():
            raise AiGenerationCancelled("AI_JOB_CANCELLED")
        conversation.updated_at = datetime.now(timezone.utc)
        assistant_id, run_identifier = uuid.uuid4(), uuid.uuid4()
        db.add(Message(id=assistant_id,conversation_id=conversation.id, role="assistant", content=answer["content"], created_at=datetime.now(timezone.utc), model_id=uuid.UUID(answer["model_id"]), metadata_json={**public(_answer_metadata(answer, locale, str(payload.get("quality_profile") or "standard"))), "run_id": str(run_identifier), "model": answer["model"], "evidence": answer.get("evidence", {})}))
        db.add(AiRun(
            id=run_identifier, user_id=user.id,
            task_type="coach_chat",
            model_id=uuid.UUID(answer["model_id"]),
            provider_name=answer["provider"],
            model_name=answer["model"],
            prompt=message,
            lookback_days=context_days,
            max_output_tokens=answer["max_output_tokens"],
            content=answer["content"],
            metadata_json=_answer_metadata(answer, locale, str(payload.get("quality_profile") or "standard"), conversation_id=str(conversation.id), assistant_message_id=str(assistant_id)),
        ))
        await db.commit()
        data_used = {
            "context_days": context_days,
            "activities": len(context.get("recent_activities", [])),
            "health_days": len(context.get("health_30d", [])),
            "sleep_days": len(context.get("sleep_30d", [])),
            "hrv_days": len(context.get("hrv_30d", [])),
            "weather": weather_context is not None and bool(weather_context.get("available")),
            "weather_location": weather_context.get("location") if weather_context else None,
        }
        return {"run_id": str(run_identifier), "conversation_id": str(conversation.id), **public(answer), "data_used": data_used}


async def _persist_plan(db, user, payload, answer, content, metadata, locale):
    from pengucoach.llm.continuation import total_usage
    root_id = _u(payload.get("_continue_run_id"))
    run = await db.scalar(select(AiRun).where(AiRun.id == root_id, AiRun.user_id == user.id)
        .with_for_update().execution_options(populate_existing=True)) if root_id else None
    if root_id and (not run or run.user_id != user.id or run.task_type != "training_plan"):
        raise RuntimeError("AI_RUN_NOT_FOUND")
    if run:
        old = payload.get("_persistence_base", run.metadata_json or {})
        if (run.metadata_json.get("continuation") or {}).get("revision", 0) != (old.get("continuation") or {}).get("revision", 0):
            raise RuntimeError("AI_RUN_CHANGED_RELOAD")
        new_usage = metadata.get("usage") or {}
        metadata["usage"] = total_usage(old.get("usage") or {}, metadata.get("usage") or {}) if old else metadata.get("usage", {})
        a, b = old.get("cost_eur") if old else 0, metadata.get("cost_eur")
        metadata["cost_eur"] = a+b if a is not None and b is not None else None
        metadata["continuation"]["revision"] = (old.get("continuation") or {}).get("revision", 0)
        metadata["generation_calls"] = [*(old.get("generation_calls") or []), *(metadata.get("generation_calls") or [])]
        metadata["elapsed_seconds"] = (old.get("elapsed_seconds") or 0)+(metadata.get("elapsed_seconds") or 0)
        tokens = metadata["usage"].get("output_tokens")
        metadata["tokens_per_second"] = round(tokens/metadata["elapsed_seconds"], 3) if isinstance(tokens, int) and metadata["elapsed_seconds"] > 0 else None
        if old:
            metadata["continuation_calls"] = [*(old.get("continuation_calls") or []), {"usage": new_usage, "max_output_tokens": answer.get("max_output_tokens")}]
        current = run.metadata_json or {}
        if current.get("_continuation_job"):
            metadata["_continuation_job"] = current["_continuation_job"]
        metadata["usage_complete"] = old.get("usage_complete", True) and metadata.get("usage_complete", True)
        run.content, run.metadata_json, run.max_output_tokens = content, metadata, answer["max_output_tokens"]
    else:
        run = AiRun(user_id=user.id, task_type="training_plan", model_id=uuid.UUID(answer["model_id"]),
            provider_name=answer["provider"], model_name=answer["model"], prompt=metadata.get("_request", {}).get("prompt") or "",
            lookback_days=int(payload.get("context_days") or 7), max_output_tokens=answer["max_output_tokens"],
            content=content, metadata_json=metadata)
        db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": str(run.id), **public(answer), "content": content, "metadata": public(metadata),
        "usage": metadata.get("usage"), "cost_eur": metadata.get("cost_eur"),
        "continuation": metadata.get("continuation"), "goal": metadata.get("goal"), "created_at": run.created_at.isoformat()}


async def _save_plan_draft(db, user, payload, context, answer, segments, locale, calls=None, usage=None, cost=None, validation_error=None, reason=None):
    state = {"context": context, "segments": [{**p.model_dump(mode="json"), "weeks": context["goal"]["weeks"]} for p in segments]}
    metadata = _answer_metadata(answer, locale, str(payload.get("quality_profile") or "standard"),
        goal=context["goal"], structured_plan=None, structured_plan_valid=False,
        structured_plan_error=validation_error or "TOKEN_LIMIT_DRAFT", draft=True, _request={**public(payload), "prompt": payload.get("_base_prompt") or payload.get("prompt")}, _plan_state=json_value(state))
    metadata["truncated"] = bool(answer.get("truncated"))
    reason = reason or ("invalid_plan" if validation_error and not answer.get("truncated") else "token_limit")
    metadata["generation_in_progress"] = reason == "in_progress"
    metadata["usage_complete"] = all(isinstance((usage or answer.get("usage") or {}).get(k), int) for k in ("input_tokens", "output_tokens"))
    metadata["continuation"] = {"available": reason != "in_progress", "revision": 0,
        "reason": reason, "additional_tokens": 0 if reason in {"invalid_plan", "interrupted", "in_progress"} else 8000}
    metadata["validated_weeks"] = max((s.week for p in segments for s in p.sessions), default=0)
    if usage is not None:
        metadata["usage"] = usage
        metadata["cost_eur"] = cost
    metadata["generation_calls"] = calls or []
    if calls:
        metadata["elapsed_seconds"] = sum(c.get("elapsed_seconds") or 0 for c in calls)
    completed = "\n\n".join(render_plan_markdown(p, locale) for p in segments)
    pending = str(answer.get("content") or "")
    content = completed + ("\n\n### Unvollständiger Abschnitt / Incomplete section\n```json\n"+pending+"\n```" if completed and pending else pending)
    return await _persist_plan(db, user, payload, answer, content, metadata, locale)


async def _training_plan(user_id: str, payload: dict[str, Any], *, progress_callback=None, cancel_check=None, db_override=None):
    async with _session(db_override) as db:
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise RuntimeError("USER_NOT_FOUND")
        locale = str(payload.get("locale") or user.locale or "de")
        context_days = int(payload.get("context_days") or 7)
        resume = payload.get("_resume_plan") or {}
        if resume.get("context"):
            context = copy.deepcopy(resume["context"])
            weather_context = context.get("weather_forecast")
        else:
            if _context_selection(payload).get("include_training", True):
                from worker.tasks.execution import refresh_user
                await refresh_user(db, user)
            context = await build_training_plan_context(db, user, days=context_days, **_context_selection(payload))
            await add_personal_context(db, user, context, payload)
            start_date = date.fromisoformat(str(payload["start_date"])) if payload.get("start_date") else None
            context["goal"] = {"goal_type": payload.get("goal_type", "hybrid"), "goal_text": payload.get("goal_text", ""),
                "experience": payload.get("experience", "intermediate"), "weeks": int(payload.get("weeks", 8)),
                "days_per_week": int(payload.get("days_per_week", 4)), "session_minutes": int(payload.get("session_minutes", 60)),
                "equipment": payload.get("equipment", ""), "constraints": payload.get("constraints", ""),
                "start_date": start_date.isoformat() if start_date else None, "source": "user"}
            if payload.get("race_id"):
                # alpha.85: plan backwards from a race the user picked in the plan form.
                from pengucoach.coach.races import plan_context
                from pengucoach.db.models import RaceEvent
                race = await db.get(RaceEvent, _u(payload.get("race_id")))
                if race and race.user_id == user.id:
                    context["goal"]["race"] = plan_context(race, start_date, int(payload.get("weeks", 8)))
            weather_context = await build_training_weather_context(db, user, include=payload.get("include_weather"), plan_start_date=start_date)
            if weather_context is not None:
                context["weather_forecast"] = weather_context
        local_only = await _privacy(db, user)
        config = await task_settings(db, "training_plan", locale)
        prompt = str(payload.get("prompt") or config["default_prompt"]).strip()
        payload = {**payload, "_base_prompt": prompt}
        root = await db.get(AiRun, _u(payload.get("_continue_run_id"))) if payload.get("_continue_run_id") else None
        if payload.get("_continue_run_id") and (not root or root.user_id != user.id or root.task_type != "training_plan"):
            raise RuntimeError("AI_RUN_NOT_FOUND")
        payload["_persistence_base"] = copy.deepcopy(root.metadata_json or {}) if root else {}
        g = context["goal"]
        total_weeks, days_per_week = int(g["weeks"]), int(g["days_per_week"])
        expected_sessions = total_weeks * days_per_week
        quality = str(payload.get("quality_profile") or "standard")
        requested_max = int(payload.get("max_tokens") or quality_budget("training_plan", config["max_output_tokens"], quality))
        selected = await resolve_model(db, "training_plan", local_only=local_only, model_id=_u(payload.get("model_id")))
        if not selected:
            raise RuntimeError("NO_ELIGIBLE_LLM_MODEL_CONFIGURED")
        provider, model = selected
        payload["model_id"] = str(model.id)
        plan_schema = TrainingPlanDocument.model_json_schema()
        chunk_weeks = int(resume.get("chunk_weeks") or (max(1, min(3, 10 // days_per_week)) if expected_sessions > 12 else total_weeks))
        chunk_count = math.ceil(total_weeks / chunk_weeks)
        segments = [TrainingPlanDocument.model_validate(x) for x in resume.get("segments", [])]
        initial_segment_count = len(segments)
        usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        generation_calls = []
        total_cost, elapsed_total = 0.0, 0.0
        costs_complete = True
        last_answer = {"content": "", "model_id": str(model.id), "provider": provider.name, "model": model.display_name,
            "max_output_tokens": requested_max, "continuation": {"available": False, "revision": 0}, "usage": {}}
        previous_outline = [{"week": s.week, "day": s.day, "sport": s.sport, "name": s.name, "duration_min": s.duration_min} for p in segments for s in p.sessions]
        any_adjusted, any_context_truncated = False, False

        def account_call(candidate, attempt, error, start_week, end_week, chunk_index):
            nonlocal total_cost, elapsed_total, costs_complete
            usage = candidate.get("usage") or {}
            for key in usage_totals:
                value = usage.get(key)
                if isinstance(value, int) and isinstance(usage_totals[key], int):
                    usage_totals[key] += value
                else:
                    usage_totals[key] = None
            cost = candidate.get("cost_eur")
            costs_complete = costs_complete and isinstance(cost, (int, float))
            if isinstance(cost, (int, float)):
                total_cost += cost
            elapsed_total += candidate.get("elapsed_seconds") or 0
            generation_calls.append({"chunk_index": chunk_index + 1, "chunk_count": chunk_count, "week_start": start_week,
                "week_end": end_week, "attempt": attempt, "max_output_tokens": candidate.get("max_output_tokens"),
                "usage": usage, "cost_eur": cost, "elapsed_seconds": candidate.get("elapsed_seconds"),
                "tokens_per_second": candidate.get("tokens_per_second"), "provider_timing": candidate.get("provider_timing"),
                "stop_reason": candidate.get("stop_reason"), "truncated": bool(candidate.get("truncated")),
                "context_truncated": candidate.get("context_truncated", False), "validation_valid": error is None,
                "validation_error": error, "usage_complete": all(isinstance(usage.get(k), int) for k in ("input_tokens", "output_tokens"))})

        async def save_draft(answer, error, reason=None):
            result = await _save_plan_draft(db, user, payload, context, answer, segments, locale,
                generation_calls, usage_totals, round(total_cost, 8) if costs_complete else None,
                validation_error=error, reason=reason)
            payload["_continue_run_id"] = result["run_id"]
            run = await db.get(AiRun, uuid.UUID(result["run_id"]))
            meta = dict(run.metadata_json)
            meta["_plan_state"] = {**meta["_plan_state"], "chunk_weeks": chunk_weeks}
            run.metadata_json = meta
            await db.commit()
            return result

        for chunk_index in range(len(segments), chunk_count):
            if cancel_check and cancel_check():
                if segments:
                    await save_draft({**last_answer, "content": ""}, "AI_JOB_CANCELLED", "interrupted")
                raise AiGenerationCancelled()
            start_week = chunk_index * chunk_weeks + 1
            end_week = min(total_weeks, start_week + chunk_weeks - 1)
            local_weeks = end_week - start_week + 1
            segment_sessions = local_weeks * days_per_week
            segment_context = copy.deepcopy(context)
            segment_context["goal"] = {**g, "weeks": local_weeks, "plan_total_weeks": total_weeks,
                "plan_week_start": start_week, "plan_week_end": end_week}
            if previous_outline:
                segment_context["previous_plan_segment"] = previous_outline[-12:]
            # Keep the instruction/data prefix stable for provider prefix caches.
            segment_message = (f"Generate overall weeks {start_week}-{end_week} of {total_weeks}. "
                f"Use local week numbers 1..{local_weeks}; return at least {days_per_week} actual training sessions in EACH week, "
                f"{segment_sessions} total. Follow goal and previous_plan_segment in the supplied context. "
                "Do not repeat earlier weeks. Count sessions before finishing.")
            compact_budget = requested_max if root or expected_sessions <= 12 else min(requested_max, max(3500, segment_sessions * 420 + 800))
            segment_error = None
            segment = None
            for segment_attempt in (1, 2):
                def segment_progress(meta):
                    if progress_callback:
                        progress_callback({**meta, "chunk_index": chunk_index + 1, "chunk_count": chunk_count,
                            "attempt": segment_attempt, "retry_reason": segment_error})
                retry_budget = requested_max
                instruction = training_plan_instruction(prompt)
                message = segment_message
                if segment_attempt == 2:
                    message += (f" Previous attempt was invalid: {segment_error}. Correct that error. "
                        "Return compact, complete JSON. Interval blocks use type=repeat and explicit repetitions plus timed/distance children. "
                        "Strength uses numeric reps, duration_seconds or reps_in_reserve, never conflicting targets or zero reps.")
                started = time.monotonic()
                try:
                    answer_part = await chat(db, [{"role": "user", "content": message}], segment_context, locale,
                        task="training_plan", local_only=local_only, model_id=model.id, instruction_prompt=instruction,
                        requested_max_tokens=compact_budget if segment_attempt == 1 else retry_budget,
                        requested_context_window_tokens=payload.get("context_window_tokens"), progress_callback=segment_progress,
                        cancel_check=cancel_check, response_format_schema=generation_schema(local_weeks, days_per_week, plan_schema),
                        quality_profile=quality, recover_limit=True, minimum_output_tokens=payload.get("_minimum_retry_output"))
                except (httpx.HTTPError, AiGenerationCancelled, RuntimeError) as exc:
                    if isinstance(exc, RuntimeError) and str(exc).startswith(("CONTINUATION_", "CONTEXT_TOO_SMALL", "USER_MESSAGE_TOO_LONG", "NO_ELIGIBLE_")):
                        if len(segments) > initial_segment_count:
                            return await save_draft({**last_answer, "content": ""}, str(exc), "interrupted")
                        raise
                    failed = {**last_answer, "content": "", "usage": {}, "cost_eur": None,
                        "max_output_tokens": compact_budget if segment_attempt == 1 else retry_budget,
                        "elapsed_seconds": round(time.monotonic()-started, 3), "truncated": False,
                        "stop_reason": "cancelled" if isinstance(exc, AiGenerationCancelled) else "request_failed"}
                    if isinstance(exc, AiGenerationCancelled) and exc.answer:
                        failed = {**failed, **exc.answer, "stop_reason": "cancelled"}
                    elif isinstance(exc, AiProviderResponseError) and exc.usage:
                        failed["usage"] = exc.usage
                    account_call(failed, segment_attempt, type(exc).__name__, start_week, end_week, chunk_index)
                    error_code = "AI_JOB_CANCELLED" if isinstance(exc, AiGenerationCancelled) else (
                        f"AI_HTTP_ERROR_{exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else
                        str(exc) if isinstance(exc, (OpenRouterError, AiProviderResponseError)) else "AI_REQUEST_INTERRUPTED:"+type(exc).__name__)
                    result = await save_draft(failed, error_code, "interrupted")
                    if isinstance(exc, AiGenerationCancelled):
                        raise
                    return result

                def parse_segment(candidate):
                    from pengucoach.training_plan.generation import validate_plan_completeness
                    parsed, error = extract_structured_plan(str(candidate.get("content") or ""))
                    if parsed is not None:
                        error = validate_plan_completeness(parsed, local_weeks, days_per_week)
                    return (None, error) if error else (parsed, None)

                segment, segment_error = parse_segment(answer_part)
                account_call(answer_part, segment_attempt, segment_error, start_week, end_week, chunk_index)
                last_answer = answer_part
                if segment is not None:
                    break
            if segment is None:
                return await save_draft(answer_part, f"TRAINING_PLAN_SEGMENT_INVALID:{start_week}-{end_week}:{segment_error}")
            for session in segment.sessions:
                session.week += start_week - 1
            segments.append(segment)
            payload.pop("_minimum_retry_output", None)
            previous_outline.extend({"week": s.week, "day": s.day, "sport": s.sport, "name": s.name, "duration_min": s.duration_min} for s in segment.sessions)
            any_adjusted |= bool(answer_part.get("output_budget_adjusted"))
            any_context_truncated |= bool(answer_part.get("context_truncated"))
            if chunk_index < chunk_count - 1:
                await save_draft({**answer_part, "content": ""}, "PLAN_GENERATION_IN_PROGRESS", "in_progress")

        merged = merge_plan_segments(segments, total_weeks)
        content = render_plan_markdown(merged, locale)
        answer = {**last_answer, "content": content, "usage": usage_totals,
            "usage_complete": all(isinstance(usage_totals[k], int) for k in ("input_tokens", "output_tokens")),
            "cost_eur": round(total_cost, 8) if costs_complete else None, "elapsed_seconds": round(elapsed_total, 3),
            "tokens_per_second": round(usage_totals["output_tokens"]/elapsed_total, 3) if isinstance(usage_totals["output_tokens"], int) and elapsed_total > 0 else None,
            "max_output_tokens": requested_max, "requested_max_output_tokens": requested_max,
            "output_budget_adjusted": any_adjusted, "context_truncated": any_context_truncated,
            "truncated": False, "continuation": {"available": False, "revision": 0},
            "stop_reason": "chunked_complete" if chunk_count > 1 else last_answer.get("stop_reason"), "generation_chunks": chunk_count}
        metadata = _answer_metadata(answer, locale, quality, goal=g, structured_plan=merged.model_dump(mode="json"),
            structured_plan_valid=True, structured_plan_error=None, generation_chunks=chunk_count, generation_calls=generation_calls,
            training_context={"days": context_days, "data": payload.get("context_data") or {},
                "weather": bool(weather_context and weather_context.get("available")), "weather_location": (weather_context or {}).get("location")},
            _request={**public(payload), "prompt": prompt})
        metadata.pop("_resume", None)
        return await _persist_plan(db, user, payload, answer, content, metadata, locale)



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
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        if self.request.retries < 1 and not payload.get("_no_auto_retry") and not check_cancel():
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


async def _session_analysis(user_id, payload, *, progress_callback=None, cancel_check=None):
    from pengucoach.coach.execution import review_session
    from pengucoach.db.models import PlanSchedule, TrainingReview
    async with SessionLocal() as db:
        db.info["ai_user_id"] = uuid.UUID(user_id)
        user = await db.get(User, uuid.UUID(user_id))
        run = await db.get(AiRun, uuid.UUID(payload['plan_id']))
        schedule = await db.get(PlanSchedule, uuid.UUID(payload['plan_id']))
        if not user or not run or run.user_id != user.id or not schedule or schedule.user_id != user.id:
            raise RuntimeError('PLAN_NOT_FOUND')
        data = await review_session(db, user, run, schedule, payload['session_id'])
        if not data.get('review') or data['fingerprint'] != payload['review_fingerprint']:
            raise RuntimeError('REVIEW_CHANGED_RELOAD')
        activity_id = uuid.UUID(data['session']['activity_id'])
        context = await build_activity_analysis_context(db, user, activity_id, 7)
        review = data['review']
        context['planned_training_review'] = {'planned': review['facts']['planned'], 'actual': review['facts']['activity'],
            'summary': review['summary'], 'feedback': review['facts']['feedback'], 'offset_s': review['facts']['offset_s'],
            'zone_date': review['facts']['zone_date'], 'intervals': review['goals']['steps'][:30],
            'intervals_truncated': len(review['goals']['steps']) > 30}
        locale = payload.get('locale') or user.locale or 'de'
        prompt = ('Compare the planned session with recorded execution and the user feedback. '
            'Use the measured per-step evidence, coverage, alignment, FTP and zone provenance. '
            'Separate recorded facts, interpretation and suggested next steps. Do not treat missing samples as failure, '
            'a higher average as automatic success, or one workout as proof that FTP changed. '
            'Give specific improvements and explain whether a similar future session should stay, be easier or cautiously progress. '
            'Changes are proposals requiring user approval. Never claim you changed a plan. '
            'Use sections: Goal and completion; Intervals and evidence; What went well; What to improve; Next session.')
        answer = await _tracked_chat(db, [{'role': 'user', 'content': 'Analyse this planned workout and its matched activity.'}],
            context, locale, task='activity_analysis', local_only=await _privacy(db, user),
            model_id=_u(payload.get('model_id')), instruction_prompt=prompt, requested_max_tokens=payload.get('max_tokens'),
            requested_context_window_tokens=payload.get('context_window_tokens'), progress_callback=progress_callback,
            cancel_check=cancel_check, recover_limit=True)
        if cancel_check and cancel_check():
            raise AiGenerationCancelled('AI_JOB_CANCELLED')
        await db.rollback()
        user = await db.get(User, uuid.UUID(user_id))
        run, schedule = await db.get(AiRun, uuid.UUID(payload['plan_id'])), await db.get(PlanSchedule, uuid.UUID(payload['plan_id']))
        fresh = await review_session(db, user, run, schedule, payload['session_id'])
        stale = fresh.get('fingerprint') != payload['review_fingerprint']
        meta = _answer_metadata(answer, locale, 'standard', review_fingerprint=payload['review_fingerprint'],
            planned_session={'plan_id': payload['plan_id'], 'session_id': payload['session_id']}, stale=stale)
        analysis = AiRun(user_id=user.id, task_type='activity_analysis', activity_id=activity_id,
            model_id=uuid.UUID(answer['model_id']), provider_name=answer['provider'], model_name=answer['model'],
            prompt=prompt, lookback_days=7, max_output_tokens=answer['max_output_tokens'], content=answer['content'], metadata_json=meta)
        db.add(analysis)
        await db.flush()
        cached = await db.scalar(select(TrainingReview).where(TrainingReview.user_id == user.id,
            TrainingReview.plan_run_id == run.id, TrainingReview.session_id == payload['session_id']))
        if cached and not stale:
            cached.ai_run_id = analysis.id
        await db.commit()
        return {'run_id': str(analysis.id), **public(answer), 'metadata': public(meta), 'stale': stale}


@app.task(bind=True, name='worker.tasks.ai.session_analysis')
def session_analysis(self, user_id, payload):
    return _run_task(self, payload, 'analysis', lambda progress, check: _session_analysis(
        user_id, payload, progress_callback=progress, cancel_check=check))
