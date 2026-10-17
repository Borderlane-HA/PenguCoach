from __future__ import annotations

import asyncio
import copy
import math
import uuid
from datetime import date, datetime, timezone
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select

from pengucoach.coach.companion import add_personal_context, conversation_excerpt
from pengucoach.coach.context import SOURCE_NOTICE, build_activity_analysis_context, build_coach_context, build_training_plan_context
from pengucoach.db.models import AiRun, Conversation, Message, User, UserPreference
from pengucoach.db.session import SessionLocal
from pengucoach.llm.job_control import cancel_requested, clear_cancel
from pengucoach.llm.service import AiGenerationCancelled, chat, task_settings
from pengucoach.llm.continuation import public, json_value
from pengucoach.training_plan.generation import merge_plan_segments, normalize_training_plan_answer, training_plan_instruction
from pengucoach.training_plan.structured import TrainingPlanDocument, extract_structured_plan, render_plan_markdown
from pengucoach.weather.service import build_coach_weather_context, build_training_weather_context
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
) -> dict[str, Any]:
    async with SessionLocal() as db:
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
    run = await db.get(AiRun, root_id) if root_id else None
    if root_id and (not run or run.user_id != user.id or run.task_type != "training_plan"):
        raise RuntimeError("AI_RUN_NOT_FOUND")
    if run:
        old = run.metadata_json or {}
        metadata["usage"] = total_usage(old.get("usage") or {}, metadata.get("usage") or {})
        a, b = old.get("cost_eur"), metadata.get("cost_eur")
        metadata["cost_eur"] = a+b if a is not None and b is not None else None
        metadata["continuation"]["revision"] = (old.get("continuation") or {}).get("revision", 0)
        metadata["generation_calls"] = [*(old.get("generation_calls") or []), *(metadata.get("generation_calls") or [])]
        metadata["elapsed_seconds"] = (old.get("elapsed_seconds") or 0)+(metadata.get("elapsed_seconds") or 0)
        tokens = metadata["usage"].get("output_tokens")
        metadata["tokens_per_second"] = round(tokens/metadata["elapsed_seconds"], 3) if isinstance(tokens, int) and metadata["elapsed_seconds"] > 0 else None
        metadata["continuation_calls"] = [*(old.get("continuation_calls") or []), {"usage": answer.get("usage"), "max_output_tokens": answer.get("max_output_tokens")}]
        if old.get("_continuation_job"):
            metadata["_continuation_job"] = old["_continuation_job"]
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


async def _save_plan_draft(db, user, payload, context, answer, segments, locale, calls=None, usage=None, cost=None):
    state = {"context": context, "segments": [{**p.model_dump(mode="json"), "weeks": context["goal"]["weeks"]} for p in segments]}
    metadata = _answer_metadata(answer, locale, str(payload.get("quality_profile") or "standard"),
        goal=context["goal"], structured_plan=None, structured_plan_valid=False,
        structured_plan_error="TOKEN_LIMIT_DRAFT", draft=True, _request={**public(payload), "prompt": payload.get("_base_prompt") or payload.get("prompt")}, _plan_state=json_value(state))
    metadata["truncated"] = True
    metadata["continuation"] = {"available": True, "revision": 0, "additional_tokens": 8000}
    if usage is not None:
        metadata["usage"] = usage
        metadata["cost_eur"] = cost
    metadata["generation_calls"] = calls or []
    completed = "\n\n".join(render_plan_markdown(p, locale) for p in segments)
    pending = str(answer.get("content") or "")
    content = completed + ("\n\n### Unvollständiger Abschnitt / Incomplete section\n```json\n"+pending+"\n```" if completed and pending else pending)
    return await _persist_plan(db, user, payload, {**answer, "truncated": True}, content, metadata, locale)


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
        if _context_selection(payload).get("include_training", True):
            from worker.tasks.execution import refresh_user
            await refresh_user(db, user)
        context = await build_training_plan_context(db, user, days=context_days, **_context_selection(payload))
        await add_personal_context(db, user, context, payload)
        start_date = date.fromisoformat(str(payload["start_date"])) if payload.get("start_date") else None
        context["goal"] = {
            "goal_type": payload.get("goal_type", "hybrid"),
            "goal_text": payload.get("goal_text", ""),
            "experience": payload.get("experience", "intermediate"),
            "weeks": int(payload.get("weeks", 8)),
            "days_per_week": int(payload.get("days_per_week", 4)),
            "session_minutes": int(payload.get("session_minutes", 60)),
            "equipment": payload.get("equipment", ""),
            "constraints": payload.get("constraints", ""),
            "start_date": start_date.isoformat() if start_date else None,
            "source": "user",
        }
        weather_context = await build_training_weather_context(
            db, user, include=payload.get("include_weather"), plan_start_date=start_date
        )
        if weather_context is not None:
            context["weather_forecast"] = weather_context
        if payload.get("_resume_plan", {}).get("context"):
            context = payload["_resume_plan"]["context"]
        local_only = await _privacy(db, user)
        config = await task_settings(db, "training_plan", locale)
        prompt = str(payload.get("prompt") or config["default_prompt"]).strip()
        payload = {**payload, "_base_prompt": prompt}
        g = context["goal"]
        total_weeks = int(g["weeks"])
        days_per_week = int(g["days_per_week"])
        expected_sessions = max(1, total_weeks * days_per_week)
        requested_max = int(payload.get("max_tokens") or config["max_output_tokens"])
        plan_schema = TrainingPlanDocument.model_json_schema()

        def base_message(weeks: int) -> str:
            if locale.startswith("de"):
                return (
                    f"Erstelle einen {weeks}-Wochen-Trainingsplan für '{g['goal_type']}', "
                    f"{days_per_week} Trainingstage pro Woche, etwa {g['session_minutes']} Minuten pro Einheit. "
                    f"Ziel: {g['goal_text'] or 'keine Zusatzangabe'}. Equipment: {g['equipment'] or 'nicht angegeben'}. "
                    f"Einschränkungen: {g['constraints'] or 'keine'}. Erfahrung: {g['experience']}. "
                    f"Nutze ausschließlich den ausgewählten Trainingskontext der letzten {context_days} Tage. "
                    f"Planstart: {g.get('start_date') or 'nicht festgelegt'}."
                )
            return (
                f"Create a {weeks}-week training plan for goal '{g['goal_type']}', "
                f"{days_per_week} training days per week and about {g['session_minutes']} minutes per session. "
                f"Goal details: {g['goal_text'] or 'none supplied'}. Equipment: {g['equipment'] or 'not specified'}. "
                f"Constraints: {g['constraints'] or 'none supplied'}. Experience: {g['experience']}. "
                f"Use only the selected training context from the last {context_days} days. "
                f"Plan start: {g.get('start_date') or 'not set'}."
            )

        # Large structured plans are generated in small week segments. This keeps
        # local models from spending the entire output budget on a single huge JSON
        # document. PenguCoach validates every segment and merges it deterministically.
        chunked = expected_sessions > 12
        if not chunked:
            answer = await chat(
                db,
                [{"role": "user", "content": base_message(total_weeks)}],
                context,
                locale,
                task="training_plan",
                local_only=local_only,
                model_id=_u(payload.get("model_id")),
                instruction_prompt=training_plan_instruction(prompt),
                requested_max_tokens=requested_max,
                requested_context_window_tokens=payload.get("context_window_tokens"),
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                response_format_schema=plan_schema,
                quality_profile=str(payload.get("quality_profile") or "standard"),
            recover_limit=True,
                minimum_output_tokens=payload.get("_minimum_retry_output"),
            )
            if cancel_check and cancel_check():
                raise AiGenerationCancelled("AI_JOB_CANCELLED")
            content, plan_meta = normalize_training_plan_answer(answer, locale)
            if answer.get("truncated") and not plan_meta.get("structured_plan_valid"):
                return await _save_plan_draft(db, user, payload, context, answer, [], locale)
            if plan_meta.get("structured_plan_valid"):
                answer["continuation"] = {"available": False, "revision": 0}
            generation_chunks = 1
        else:
            chunk_weeks = max(1, min(3, 10 // max(1, days_per_week)))
            chunk_count = math.ceil(total_weeks / chunk_weeks)
            segments = [TrainingPlanDocument.model_validate(x) for x in payload.get("_resume_plan", {}).get("segments", [])]
            usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            generation_calls: list[dict[str, Any]] = []
            total_cost_eur = 0.0
            total_elapsed_seconds = 0.0
            timed_output_tokens = 0
            priced_calls = 0
            last_answer: dict[str, Any] | None = None
            previous_outline: list[dict[str, Any]] = [{"week": s.week, "day": s.day, "sport": s.sport, "name": s.name, "duration_min": s.duration_min} for p in segments for s in p.sessions]
            any_budget_adjusted = False
            any_context_truncated = False

            for chunk_index in range(chunk_count):
                if chunk_index < len(payload.get("_resume_plan", {}).get("segments", [])):
                    continue
                if cancel_check and cancel_check():
                    raise AiGenerationCancelled("AI_JOB_CANCELLED")
                start_week = chunk_index * chunk_weeks + 1
                end_week = min(total_weeks, start_week + chunk_weeks - 1)
                local_weeks = end_week - start_week + 1
                segment_context = copy.deepcopy(context)
                segment_goal = dict(g)
                segment_goal.update({
                    "weeks": local_weeks,
                    "plan_total_weeks": total_weeks,
                    "plan_week_start": start_week,
                    "plan_week_end": end_week,
                })
                segment_context["goal"] = segment_goal
                if previous_outline:
                    segment_context["previous_plan_segment"] = previous_outline[-12:]
                segment_instruction = training_plan_instruction(prompt) + (
                    f"\n\nSEGMENT GENERATION: This is overall weeks {start_week}-{end_week} of a {total_weeks}-week plan. "
                    f"Return only these {local_weeks} weeks. In the JSON use local week numbers 1..{local_weeks}; "
                    "PenguCoach will remap them to the absolute calendar weeks. Preserve sensible progression from the "
                    "previous_plan_segment context when supplied. Do not repeat earlier weeks."
                )
                if locale.startswith("de"):
                    segment_message = base_message(local_weeks) + (
                        f" Erzeuge jetzt ausschließlich den Abschnitt für Gesamtwoche {start_week} bis {end_week} von {total_weeks}. "
                        f"Im JSON nummerierst du diese Abschnittswochen lokal von 1 bis {local_weeks}."
                    )
                else:
                    segment_message = base_message(local_weeks) + (
                        f" Generate only the segment for overall weeks {start_week} through {end_week} of {total_weeks}. "
                        f"Number these segment weeks locally from 1 through {local_weeks} in the JSON."
                    )
                segment_sessions = max(1, local_weeks * days_per_week)
                # Max. Antwort is a per-call ceiling, not a total budget shared
                # across all plan chunks. Give each segment enough room for a
                # complete structured document; if that compact attempt still
                # fails, the retry below uses the user's full per-call budget.
                compact_budget = requested_max if payload.get("_continue_run_id") else min(requested_max, max(3500, segment_sessions * 420 + 800))

                def segment_progress(meta: dict[str, Any], *, ci=chunk_index + 1, cc=chunk_count) -> None:
                    if progress_callback:
                        progress_callback({**meta, "chunk_index": ci, "chunk_count": cc})

                answer_part = await chat(
                    db,
                    [{"role": "user", "content": segment_message}],
                    segment_context,
                    locale,
                    task="training_plan",
                    local_only=local_only,
                    model_id=_u(payload.get("model_id")),
                    instruction_prompt=segment_instruction,
                    requested_max_tokens=compact_budget,
                    requested_context_window_tokens=payload.get("context_window_tokens"),
                    progress_callback=segment_progress,
                    cancel_check=cancel_check,
                    response_format_schema=plan_schema,
                    quality_profile=str(payload.get("quality_profile") or "standard"),
            recover_limit=True,
                minimum_output_tokens=payload.get("_minimum_retry_output"),
                )
                def account_call(candidate: dict[str, Any], attempt: int) -> None:
                    nonlocal total_cost_eur, total_elapsed_seconds, timed_output_tokens, priced_calls
                    call_usage = candidate.get("usage") if isinstance(candidate.get("usage"), dict) else {}
                    for key in usage_totals:
                        value = call_usage.get(key)
                        if isinstance(value, int):
                            usage_totals[key] += value
                    call_cost = candidate.get("cost_eur")
                    if call_cost is not None:
                        total_cost_eur += float(call_cost)
                        priced_calls += 1
                    elapsed = candidate.get("elapsed_seconds")
                    if isinstance(elapsed, (int, float)) and float(elapsed) >= 0:
                        total_elapsed_seconds += float(elapsed)
                        if isinstance(call_usage.get("output_tokens"), int):
                            timed_output_tokens += int(call_usage["output_tokens"])
                    generation_calls.append({
                        "chunk_index": chunk_index + 1,
                        "chunk_count": chunk_count,
                        "week_start": start_week,
                        "week_end": end_week,
                        "attempt": attempt,
                        "max_output_tokens": candidate.get("max_output_tokens"),
                        "usage": call_usage,
                        "cost_eur": call_cost,
                        "elapsed_seconds": candidate.get("elapsed_seconds"),
                        "tokens_per_second": candidate.get("tokens_per_second"),
                        "stop_reason": candidate.get("stop_reason"),
                        "truncated": bool(candidate.get("truncated")),
                    })

                account_call(answer_part, 1)
                def parse_segment(candidate: dict[str, Any]):
                    parsed, parsed_error = extract_structured_plan(str(candidate.get("content") or ""))
                    if parsed is not None and parsed.weeks != local_weeks:
                        return None, f"SEGMENT_WEEK_COUNT:{parsed.weeks}!={local_weeks}"
                    if parsed is not None and len(parsed.sessions) < segment_sessions:
                        return None, f"SEGMENT_SESSION_COUNT:{len(parsed.sessions)}<{segment_sessions}"
                    return parsed, parsed_error

                # Parse before treating an exact token-cap finish as a failure: a
                # model can land exactly on its cap after already closing valid JSON.
                segment, segment_error = parse_segment(answer_part)
                # Retry only when the plan is incomplete/invalid. A valid schema
                # document is accepted even if Ollama reports a length boundary.
                needs_retry = segment is None
                if needs_retry and compact_budget < requested_max:
                    retry_budget = requested_max
                    answer_part = await chat(
                        db,
                        [{"role": "user", "content": segment_message}],
                        segment_context,
                        locale,
                        task="training_plan",
                        local_only=local_only,
                        model_id=_u(payload.get("model_id")),
                        instruction_prompt=(
                            segment_instruction
                            + "\nThe previous attempt was incomplete or invalid. Return only one compact, complete JSON object; "
                              "shorten wording aggressively before omitting any requested session."
                        ),
                        requested_max_tokens=retry_budget,
                        requested_context_window_tokens=payload.get("context_window_tokens"),
                        progress_callback=segment_progress,
                        cancel_check=cancel_check,
                        response_format_schema=plan_schema,
                        quality_profile=str(payload.get("quality_profile") or "standard"),
            recover_limit=True,
                minimum_output_tokens=payload.get("_minimum_retry_output"),
                    )
                    account_call(answer_part, 2)
                    segment, segment_error = parse_segment(answer_part)
                if segment is None:
                    if answer_part.get("truncated"):
                        return await _save_plan_draft(db, user, payload, context, answer_part, segments, locale,
                            generation_calls, usage_totals, round(total_cost_eur, 8) if priced_calls else None)
                    raise RuntimeError(f"TRAINING_PLAN_SEGMENT_INVALID:{start_week}-{end_week}:{segment_error}")
                for session in segment.sessions:
                    session.week += start_week - 1
                segments.append(segment)
                payload.pop("_minimum_retry_output", None)
                previous_outline.extend({
                    "week": session.week,
                    "day": session.day,
                    "sport": session.sport,
                    "name": session.name,
                    "duration_min": session.duration_min,
                } for session in segment.sessions)
                any_budget_adjusted = any_budget_adjusted or bool(answer_part.get("output_budget_adjusted"))
                any_context_truncated = any_context_truncated or bool(answer_part.get("context_truncated"))
                last_answer = answer_part

            merged = merge_plan_segments(segments, total_weeks)
            content = render_plan_markdown(merged, locale)
            plan_meta = {
                "structured_plan": merged.model_dump(mode="json"),
                "structured_plan_valid": True,
                "structured_plan_error": None,
            }
            assert last_answer is not None
            answer = {
                **last_answer,
                "content": content,
                "usage": usage_totals,
                "cost_eur": round(total_cost_eur, 8) if priced_calls else None,
                "elapsed_seconds": round(total_elapsed_seconds, 3),
                "tokens_per_second": round(timed_output_tokens / total_elapsed_seconds, 3) if total_elapsed_seconds > 0 else None,
                "generation_calls": generation_calls,
                "max_output_tokens": requested_max,
                "requested_max_output_tokens": requested_max,
                "output_budget_adjusted": any_budget_adjusted,
                "context_truncated": any_context_truncated,
                "truncated": False,
                "continuation": {"available": False, "revision": 0},
                "stop_reason": "chunked_complete",
                "generation_chunks": chunk_count,
            }
            generation_chunks = chunk_count

        metadata = {
            "_resume": answer.get("_resume"),
            "continuation": answer.get("continuation", {"available": False, "revision": 0}),
            "goal": context["goal"],
            "training_context": {
                "days": context_days,
                "data": context_data,
                "weather": weather_context is not None and bool(weather_context.get("available")),
                "weather_location": weather_context.get("location") if weather_context else None,
            },
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
            "generation_chunks": generation_chunks,
            "local": answer.get("local"),
            "locale": locale,
            "quality_profile": str(payload.get("quality_profile") or "standard"),
            "pricing": answer.get("pricing"),
            "cost_eur": answer.get("cost_eur"),
            "elapsed_seconds": answer.get("elapsed_seconds"),
            "tokens_per_second": answer.get("tokens_per_second"),
            "generation_calls": answer.get("generation_calls", []),
            **plan_meta,
        }
        metadata["_request"] = {**public(payload), "prompt": prompt}
        if not metadata.get("truncated"):
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
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
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
        answer = await chat(db, [{'role': 'user', 'content': 'Analyse this planned workout and its matched activity.'}],
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
