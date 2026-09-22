from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import LlmModel, LlmProvider, LlmRoute
from pengucoach.security.crypto import SecretBox


class AiGenerationCancelled(RuntimeError):
    """Raised when the user cancels a cooperative AI generation."""


ProgressCallback = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


OPENAI_COMPATIBLE_PROVIDER_TYPES = {"openai", "openai_compatible", "ionos", "gemini", "xai"}
PROVIDER_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "ionos": "https://openai.inference.de-txl.ionos.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "xai": "https://api.x.ai/v1",
}

def provider_base_url(provider_type: str, configured: str | None) -> str:
    return (configured or PROVIDER_DEFAULT_BASE_URLS.get(provider_type) or "").rstrip("/")


def _emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is not None:
        callback(payload)


SYSTEM_PROMPT_DE = """Du bist PenguCoach, ein selbst gehosteter Assistent für Trainings- und Wellnessanalyse.
Nutze ausschließlich Fakten aus dem bereitgestellten Kontext. Erfinde niemals Messwerte, Trainingseinheiten,
Symptome oder Erholungsdaten. Unterscheide klar zwischen Garmin-Werten, von PenguCoach berechneten
Metriken und Angaben des Nutzers. Garmin-Zusammenfassungen sind – sofern vorhanden – die maßgebliche
Quelle für offizielle Aktivitäts-Gesamtwerte; PenguCoach-Berechnungen ergänzen die Analyse.
PenguCoach ist kein Medizinprodukt. Stelle keine Diagnosen und erteile keine medizinische Trainingsfreigabe.
Bei dringlichen oder potentiell ernsten Symptomen sollst du eine zeitnahe professionelle medizinische Abklärung
empfehlen. Mache Unsicherheit und fehlende Daten transparent. Leite aus Trainingsdaten allein kein
Übertrainingssyndrom ab; beschreibe stattdessen Muster wie hohe/niedrige kurzfristige Belastung und verfügbare
Erholungssignale mit angemessener Unsicherheit. Antworte ausschließlich auf Deutsch."""

SYSTEM_PROMPT_EN = """You are PenguCoach, a self-hosted training and wellness analysis assistant.
Use only facts in the supplied context. Never invent measurements, workouts, symptoms or recovery data.
Clearly distinguish Garmin values, PenguCoach-calculated metrics and user-provided information. Garmin summary
values are the authoritative source for official activity totals when present; PenguCoach calculations are analytical
supplements. You are not a medical device and you do not diagnose, treat, or provide medical clearance. If a user
describes urgent or potentially serious symptoms, recommend prompt professional medical assessment rather than
giving training clearance. Make uncertainty and missing data explicit. Do not claim overtraining syndrome from
training data alone; describe patterns such as high/low recent load and recovery signals with appropriate uncertainty.
Reply exclusively in English."""

DEEP_ACTIVITY_PROMPT_DE = """Führe eine tiefgehende, datenbasierte Analyse dieser Trainingseinheit durch.
Priorisiere die offiziellen Garmin-Gesamtwerte und verwende PenguCoach-FIT-Metriken als ergänzende analytische Evidenz.
Analysiere – sofern Daten vorhanden sind – Tempo/Geschwindigkeit, Herzfrequenzreaktion, Leistung, Kadenz,
Höhenprofil, Splits, Sensorabdeckung, Effizienz und auffällige Veränderungen innerhalb der Einheit.
Wenn training_zones vorhanden sind, verwende die von Garmin konfigurierten sportartspezifischen Herzfrequenz- und
Leistungszonen. Wenn time_in_zones vorhanden ist, nutze diese lokal aus FIT berechnete Zeitverteilung und kennzeichne
klar: Zonengrenzen = Garmin, Zeit in Zone = PenguCoach/FIT. Erfinde keine fehlenden Zonen.

Wenn Kontextdaten vorhanden sind, verwende exakt den angeforderten Kontextumfang aus lookback.scope:
- session_only: ausschließlich diese Trainingseinheit; keine Tages- oder Rückblickbewertung erfinden.
- activity_day: Tageskontext des Trainingstags einschließlich verfügbarer Garmin-Tageswerte wie Schlaf, HRV,
  Ruhepuls, Stress, Body Battery, Training Readiness, Schritte und Hydration sowie weitere Einheiten dieses Tages.
- three_days: die Einheit plus den inklusiven 3-Tage-Kontext mit Trainingshäufigkeit, Dauer, Distanz, Garmin
  Training Load, Ruhetagen und verfügbaren Erholungsdaten.
- seven_days: die Einheit plus den inklusiven 7-Tage-Kontext; nutze zusätzlich den 3-Tage-Vergleich, wenn vorhanden.
Ordne kurzfristige Belastung vorsichtig als eher niedrig, ausgewogen oder hoch ein, ohne ein Übertrainingssyndrom
zu diagnostizieren. Tageswerte sind Garmin-Tagesaggregate und können den gesamten Kalendertag abbilden.

Strukturiere die Antwort passend zum tatsächlich gelieferten Kontext in:
1. Kurzfazit
2. Leistungsanalyse der aktuellen Einheit
3. Herzfrequenz, Leistung/Pace und Effizienz
4. Höhenprofil, Splits und Pacing
5. Kontext des gewählten Zeitraums (nur wenn geliefert)
6. Belastungs-/Erholungskontext (nur wenn geliefert)
7. Stärken der Einheit
8. Auffälligkeiten / Punkte zum Beobachten
9. Konkrete Empfehlung für die nächsten 1–3 Trainingstage

Nutze konkrete Zahlen aus dem Kontext. Erfinde keine fehlenden Werte. Kennzeichne klar, was direkt von Garmin
stammt und was von PenguCoach berechnet wurde. Antworte ausschließlich auf Deutsch."""

DEEP_ACTIVITY_PROMPT_EN = """Perform a deep, evidence-focused analysis of this training session.
Prioritize official Garmin activity totals and use PenguCoach FIT metrics as supplementary analytical evidence.
Where data exists, assess pacing/speed, heart-rate response, power, cadence, elevation, splits, sensor coverage,
efficiency and meaningful changes within the session. If training_zones are supplied, use Garmin's configured
sport-specific heart-rate and power zones. If time_in_zones is supplied, use the locally FIT-calculated distribution
and state clearly: zone boundaries = Garmin, time in zone = PenguCoach/FIT. Never invent missing zones.

When context data is supplied, use exactly the requested scope from lookback.scope:
- session_only: analyse only this training session; do not invent daily or lookback conclusions.
- activity_day: use the calendar-day context for the session, including available Garmin daily values such as sleep,
  HRV, resting heart rate, stress, Body Battery, Training Readiness, steps and hydration, plus other sessions that day.
- three_days: use the session plus the inclusive 3-day context with training frequency, duration, distance, Garmin
  Training Load, rest days and available recovery data.
- seven_days: use the session plus the inclusive 7-day context and the 3-day comparison when available.
Describe short-term load cautiously as relatively light, balanced or heavy; do not diagnose overtraining syndrome.
Daily values are Garmin calendar-day aggregates and may represent the complete calendar day.

Complete the answer using sections appropriate to the supplied context:
1. Executive summary
2. Current-session performance analysis
3. Heart rate, power/pace and efficiency
4. Elevation, splits and pacing
5. Selected-period context (only when supplied)
6. Load and recovery context (only when supplied)
7. Strengths
8. Watch-outs
9. Practical recommendation for the next 1–3 training days

Use concrete numbers from the supplied context. Never invent missing values. Clearly distinguish Garmin values
from PenguCoach-calculated metrics. Reply exclusively in English."""

TRAINING_PLAN_PROMPT_DE = """Erstelle einen praktischen, periodisierten Trainingsplan aus dem angegebenen Ziel und dem bereitgestellten
Trainingskontext. Beachte Wochenanzahl, Trainingstage und typische Sessiondauer. Balanciere Trainingsreiz und Erholung.
Nutze ausschließlich den im Kontext ausgewählten Zeitraum und die dort freigegebenen Daten zu Training, Belastung und Erholung.
Behaupte keine medizinische Trainingsbereitschaft und ergänze keine nicht ausgewählten Datenquellen. Wenn training_zones vorhanden sind, verwende die von Garmin konfigurierten Herzfrequenz- und Leistungszonen
für konkrete Intensitätsvorgaben (z. B. Z2 Grundlage oder Z4 Intervalle) und nenne die gelieferten Grenzen, wenn sinnvoll.
Erfinde keine Zonen, FTP- oder Schwellenwerte. Berücksichtige Progression und leichtere/regenerative Einheiten. Für Kraftziele: große Bewegungsmuster,
Sätze/Wiederholungen und RPE/RIR-Leitplanken, ohne unbekannte Gewichte zu erfinden. Für Ausdauerziele: lockere aerobe
Einheiten, Qualität/Intervalle und längere Einheiten passend zum Ziel. Für Hybridziele: Kraft und Ausdauer sinnvoll verteilen.
Kennzeichne optionale Einheiten und Ruhetage. Struktur: Ziel & Annahmen, Wochenstruktur, Plan Woche für Woche,
Sessiondetails, Progressionsregeln, Belastungs-/Erholungsleitplanken und Anpassung bei verpassten Einheiten oder schwachen
Erholungssignalen. Erfinde keine Gesundheitsdaten. Antworte ausschließlich auf Deutsch."""

TRAINING_PLAN_PROMPT_EN = """Create a practical, periodized training plan using the user's stated goal and the supplied recent training context.
Respect the requested number of weeks, training days and typical session duration. Balance training stimulus and recovery.
Use only the selected lookback period and the data categories explicitly supplied in context. Do not infer medical readiness or add unselected data sources.
If training_zones are supplied, use Garmin-configured heart-rate and power zones for concrete intensity prescriptions
(e.g. Z2 aerobic work or Z4 intervals) and include supplied bounds when useful. Never invent zones, FTP or thresholds.
Include progression and easier/recovery sessions. For strength goals include major movement patterns, sets/reps and
RPE/RIR guardrails without pretending exact loads are known. For endurance goals include easy aerobic, quality/interval
and longer sessions as appropriate. For hybrid goals balance strength and endurance interference. Clearly mark optional
sessions and rest days. Structure the result as: Goal & assumptions, Weekly structure, Week-by-week plan, Session details,
Progression rules, Recovery/load guardrails, and How to adjust when sessions are missed or recovery data is poor.
Do not invent health data. Reply exclusively in English."""

COACH_CHAT_PROMPT_DE = """Beantworte die Frage des Nutzers anhand des bereitgestellten Garmin- und PenguCoach-Kontexts.
Nutze konkrete Werte, wenn sie relevant sind, unterscheide Messwerte von Interpretation und sage klar, wenn die Datenlage
für eine Aussage nicht ausreicht. Nutze Garmin-Trainingszonen aus training_zones, wenn die Frage Intensität, Puls oder Leistung betrifft.
Wenn die Frage keinen Trainings-/Gesundheitskontext benötigt, antworte direkt und ignoriere
irrelevante Trainingsdaten. Antworte ausschließlich auf Deutsch."""

COACH_CHAT_PROMPT_EN = """Answer the user's question from the supplied Garmin and PenguCoach context.
Use concrete values when relevant, distinguish measured facts from interpretation, and state when the available data is
insufficient. Use Garmin training zones from training_zones when the question concerns intensity, heart rate or power.
If the question does not require training/wellness context, answer directly and ignore irrelevant training data.
Reply exclusively in English."""

# Compatibility exports used by older tests/integrations.
DEEP_ACTIVITY_PROMPT = DEEP_ACTIVITY_PROMPT_EN
TRAINING_PLAN_PROMPT = TRAINING_PLAN_PROMPT_EN
COACH_CHAT_PROMPT = COACH_CHAT_PROMPT_EN
SYSTEM_PROMPT = SYSTEM_PROMPT_EN

TASK_DEFAULTS: dict[str, dict[str, Any]] = {
    "coach_chat": {
        "max_output_tokens": 2500,
        "context_window_tokens": 8192,
        "max_context_chars": 24000,
        "default_prompt_de": COACH_CHAT_PROMPT_DE,
        "default_prompt_en": COACH_CHAT_PROMPT_EN,
    },
    "activity_analysis": {
        "max_output_tokens": 8000,
        "context_window_tokens": 16384,
        "max_context_chars": 52000,
        "default_prompt_de": DEEP_ACTIVITY_PROMPT_DE,
        "default_prompt_en": DEEP_ACTIVITY_PROMPT_EN,
    },
    "training_plan": {
        "max_output_tokens": 8000,
        "context_window_tokens": 16384,
        "max_context_chars": 52000,
        "default_prompt_de": TRAINING_PLAN_PROMPT_DE,
        "default_prompt_en": TRAINING_PLAN_PROMPT_EN,
    },
}


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return fallback


def _locale_key(locale: str | None) -> str:
    return "de" if str(locale or "de").lower().startswith("de") else "en"


async def task_settings(db: AsyncSession, task: str, locale: str | None = None) -> dict[str, Any]:
    defaults = dict(TASK_DEFAULTS.get(task, TASK_DEFAULTS["coach_chat"]))
    route = await db.get(LlmRoute, task)
    custom = route.settings if route and isinstance(route.settings, dict) else {}
    result = {**defaults, **custom}

    # Migrate alpha.4's single prompt transparently if present in JSON settings.
    legacy_prompt = str(custom.get("default_prompt") or "").strip()
    for language in ("de", "en"):
        key = f"default_prompt_{language}"
        prompt = str(result.get(key) or legacy_prompt or defaults[key]).strip()
        result[key] = prompt[:16000]

    result["max_output_tokens"] = _clamp_int(result.get("max_output_tokens"), 128, 65536, defaults["max_output_tokens"])
    result["context_window_tokens"] = _clamp_int(
        result.get("context_window_tokens"), 2048, 1_048_576, defaults["context_window_tokens"]
    )
    result["max_context_chars"] = _clamp_int(
        result.get("max_context_chars"), 4000, 800000, defaults["max_context_chars"]
    )
    language = _locale_key(locale)
    result["default_prompt"] = result[f"default_prompt_{language}"]
    return result


async def eligible_models(db: AsyncSession, local_only: bool = False) -> list[dict[str, Any]]:
    models = (await db.scalars(select(LlmModel).where(LlmModel.enabled.is_(True)).order_by(LlmModel.display_name))).all()
    out: list[dict[str, Any]] = []
    for model in models:
        provider = await db.get(LlmProvider, model.provider_id)
        if not provider or not provider.enabled or (local_only and not provider.is_local):
            continue
        meta = model.metadata_json if isinstance(model.metadata_json, dict) else {}
        out.append({
            "id": str(model.id),
            "display_name": model.display_name,
            "model_identifier": model.model_identifier,
            "provider": provider.name,
            "provider_type": provider.provider_type,
            "local": provider.is_local,
            "context_window": model.context_window,
            "provider_max_output_tokens": meta.get("provider_max_output_tokens"),
            "temperature": model.temperature,
        })
    return out


async def resolve_model(
    db: AsyncSession,
    task: str = "coach_chat",
    local_only: bool = False,
    model_id: uuid.UUID | None = None,
) -> tuple[LlmProvider, LlmModel] | None:
    if model_id:
        model = await db.get(LlmModel, model_id)
        if model and model.enabled:
            provider = await db.get(LlmProvider, model.provider_id)
            if provider and provider.enabled and (not local_only or provider.is_local):
                return provider, model
        return None

    route = await db.get(LlmRoute, task)
    candidate_ids: list[uuid.UUID | None] = []
    if route and route.enabled:
        candidate_ids.extend([route.primary_model_id, route.fallback_model_id])
    for candidate_id in [x for x in candidate_ids if x]:
        model = await db.get(LlmModel, candidate_id)
        if not model or not model.enabled:
            continue
        provider = await db.get(LlmProvider, model.provider_id)
        if provider and provider.enabled and (not local_only or provider.is_local):
            return provider, model

    models = (await db.scalars(select(LlmModel).where(LlmModel.enabled.is_(True)).order_by(LlmModel.display_name))).all()
    for model in models:
        provider = await db.get(LlmProvider, model.provider_id)
        if provider and provider.enabled and (not local_only or provider.is_local):
            return provider, model
    return None


def _secret(provider: LlmProvider) -> str | None:
    return SecretBox().decrypt(provider.secret_ciphertext) if provider.secret_ciphertext else None


def _json_size(value: Any) -> tuple[str, int]:
    payload = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return payload, len(payload)


def _bounded_context(context: dict[str, Any], max_chars: int) -> tuple[str, dict[str, Any]]:
    """Keep the context valid JSON while enforcing a deterministic input budget."""
    working = copy.deepcopy(context)
    payload, size = _json_size(working)
    original_size = size
    if size <= max_chars:
        return payload, {"context_chars": size, "context_estimated_tokens": max(1, size // 4), "context_truncated": False}

    list_paths = [
        ("activity", "splits"),
        ("lookback", "activities"),
        ("lookback", "health"),
        ("lookback", "sleep"),
        ("lookback", "hrv"),
        ("recent_activities",),
        ("health_30d",),
        ("sleep_30d",),
        ("hrv_30d",),
    ]
    for path in list_paths:
        node: Any = working
        for key in path[:-1]:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        key = path[-1]
        values = node.get(key) if isinstance(node, dict) else None
        if isinstance(values, list) and len(values) > 8:
            node[key] = values[:8]
            node[f"{key}_truncated"] = True
        payload, size = _json_size(working)
        if size <= max_chars:
            break

    if size > max_chars:
        compact: dict[str, Any] = {
            "source_notice": working.get("source_notice"),
            "activity": working.get("activity"),
            "lookback": {
                "days": working.get("lookback", {}).get("days"),
                "from": working.get("lookback", {}).get("from"),
                "to": working.get("lookback", {}).get("to"),
                "selected_data": working.get("lookback", {}).get("selected_data"),
                "summary_period": working.get("lookback", {}).get("summary_period"),
                "summary_recent_7d": working.get("lookback", {}).get("summary_recent_7d"),
                # Activity analysis still uses these legacy summary keys.
                "summary_3d": working.get("lookback", {}).get("summary_3d"),
                "summary_7d": working.get("lookback", {}).get("summary_7d"),
                "summary_28d": working.get("lookback", {}).get("summary_28d"),
                "activities": (working.get("lookback", {}).get("activities") or [])[:6],
                "daily_health": (working.get("lookback", {}).get("daily_health") or [])[-7:],
                "sleep": (working.get("lookback", {}).get("sleep") or [])[-7:],
                "hrv": (working.get("lookback", {}).get("hrv") or [])[-7:],
            },
            "goal": working.get("goal"),
            "training_zones": working.get("training_zones"),
            "context_truncated": True,
        }
        payload, size = _json_size(compact)
        if size > max_chars and isinstance(compact.get("activity"), dict):
            # An activity-analysis request must never lose the activity itself.
            # Reduce the current-session payload before discarding lookback data.
            activity = compact["activity"]
            compact["activity"] = {
                "garmin": activity.get("garmin"),
                "pengucoach": activity.get("pengucoach"),
                "fit_analytics_source": activity.get("fit_analytics_source"),
                "fit_analytics": activity.get("fit_analytics"),
                "training_zones": activity.get("training_zones"),
                "time_in_zones": activity.get("time_in_zones"),
                "splits_source": activity.get("splits_source"),
                "splits": (activity.get("splits") or [])[:2],
                "context_compacted": True,
            }
            payload, size = _json_size(compact)
        if size > max_chars and isinstance(compact.get("activity"), dict):
            activity = compact["activity"]
            compact["activity"] = {
                "garmin": activity.get("garmin"),
                "pengucoach": activity.get("pengucoach"),
                "training_zones": activity.get("training_zones"),
                "time_in_zones": activity.get("time_in_zones"),
                "context_compacted": True,
            }
            compact["context_note"] = "Lookback and detailed FIT context were reduced to preserve the current activity."
            payload, size = _json_size(compact)
    return payload, {
        "context_chars": size,
        "context_estimated_tokens": max(1, size // 4),
        "context_truncated": True,
        "original_context_chars": original_size,
    }


def _system_prompt(locale: str) -> str:
    return SYSTEM_PROMPT_DE if _locale_key(locale) == "de" else SYSTEM_PROMPT_EN


async def chat(
    db: AsyncSession,
    messages: list[dict[str, str]],
    context: dict[str, Any],
    locale: str,
    task: str = "coach_chat",
    local_only: bool = False,
    *,
    model_id: uuid.UUID | None = None,
    instruction_prompt: str | None = None,
    requested_max_tokens: int | None = None,
    requested_context_window_tokens: int | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    config = await task_settings(db, task, locale)
    selected = await resolve_model(db, task, local_only=local_only, model_id=model_id)
    if not selected:
        raise RuntimeError("NO_ELIGIBLE_LLM_MODEL_CONFIGURED")
    provider, model = selected

    configured_max = int(config["max_output_tokens"])
    # Route budgets are task defaults, not a hidden ceiling. An explicit value from
    # the task UI may be higher; the selected model/provider and the context window
    # still enforce the real hard limits below.
    max_tokens = configured_max if requested_max_tokens is None else _clamp_int(
        requested_max_tokens, 128, 65536, configured_max
    )

    configured_ctx = int(config["context_window_tokens"])
    requested_ctx = configured_ctx if requested_context_window_tokens is None else _clamp_int(
        requested_context_window_tokens, 2048, 1_048_576, configured_ctx
    )
    model_ctx = int(model.context_window) if model.context_window else None
    context_window_tokens = min(requested_ctx, model_ctx) if model_ctx else requested_ctx
    provider_max_output = None
    if isinstance(model.metadata_json, dict):
        raw_provider_max = model.metadata_json.get("provider_max_output_tokens")
        if isinstance(raw_provider_max, int) and raw_provider_max > 0:
            provider_max_output = raw_provider_max
    requested_output_tokens = max_tokens
    if provider_max_output:
        max_tokens = min(max_tokens, provider_max_output)
    # A configured output ceiling is not useful if it squeezes the actual
    # training data out of the model context. Keep a task-specific minimum
    # input budget and automatically lower only the effective output request
    # when the selected context window is too small. Users remain free to raise
    # the context window to obtain the full requested output budget.
    minimum_input_tokens = {
        "activity_analysis": 3072,
        "training_plan": 3072,
        "coach_chat": 1024,
    }.get(task, 1024)
    framing_reserve_tokens = 768
    max_output_that_fits = max(128, context_window_tokens - minimum_input_tokens - framing_reserve_tokens)
    max_tokens = min(max_tokens, max_output_that_fits)
    output_budget_adjusted = max_tokens < requested_output_tokens
    # Leave room for system/task instructions and chat framing. The remaining budget is shared by JSON context and messages.
    usable_input_tokens = max(minimum_input_tokens, context_window_tokens - max_tokens - framing_reserve_tokens)
    context_budget_tokens = max(768, int(usable_input_tokens * 0.72))
    message_budget_tokens = max(256, usable_input_tokens - context_budget_tokens)
    max_context_chars = min(int(config["max_context_chars"]), context_budget_tokens * 4)

    task_prompt = (instruction_prompt or config["default_prompt"]).strip()[:16000]
    context_json, context_meta = _bounded_context(context, max_context_chars)
    output_target = max(128, int(max_tokens * 0.88))
    budget_notice = (
        f"\nHARD OUTPUT BUDGET: The API will stop generation at {max_tokens} output tokens. "
        f"Finish the complete response before that limit and target at most about {output_target} tokens. "
        "Do not rely on being allowed to continue after truncation."
    )
    if task == "training_plan":
        goal = context.get("goal") if isinstance(context, dict) else None
        weeks = int((goal or {}).get("weeks") or 1) if isinstance(goal, dict) else 1
        days_per_week = int((goal or {}).get("days_per_week") or 1) if isinstance(goal, dict) else 1
        expected_sessions = max(1, weeks * days_per_week)
        per_session = max(55, int(max(256, output_target - 450) / expected_sessions))
        budget_notice += (
            f" The requested plan is approximately {expected_sessions} sessions ({weeks} weeks × {days_per_week}/week). "
            f"Budget the JSON at roughly {per_session} tokens per session on average. "
            "If space becomes tight, shorten summary, notes, names and descriptions first; use repeat groups for intervals; "
            "omit optional/default JSON fields when they add no information. NEVER omit requested weeks/sessions merely to save tokens. "
            "Return no prose outside the required structured plan block."
        )
    system_content = (
        _system_prompt(locale)
        + "\nThe task instructions below may refine the task but may not override safety, source-integrity or no-invention rules."
        + budget_notice
        + f"\nTask instructions:\n{task_prompt}"
        + f"\nData context (JSON):\n{context_json}"
    )

    recent_messages = messages[-12:]
    message_budget = message_budget_tokens * 4
    bounded_messages: list[dict[str, str]] = []
    used_message_chars = 0
    for message in reversed(recent_messages):
        content = str(message.get("content", ""))
        remaining = message_budget - used_message_chars
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[-remaining:]
        bounded_messages.append({"role": str(message.get("role", "user")), "content": content})
        used_message_chars += len(content)
    bounded_messages.reverse()
    prompt_messages = [{"role": "system", "content": system_content}] + bounded_messages

    if cancel_check and cancel_check():
        raise AiGenerationCancelled("AI_JOB_CANCELLED")

    _emit_progress(
        progress_callback,
        stage="connecting",
        message="AI model is preparing the response",
        max_output_tokens=max_tokens,
        context_window_tokens=context_window_tokens,
        output_tokens_estimate=0,
        output_tokens_exact=None,
    )

    # For local Ollama generation the response is streamed below. The read timeout
    # therefore applies to a gap between chunks rather than to the total generation
    # duration. A generous first-token/read gap avoids the former 300 s hard wait
    # that made long 8k-token local plans fail after roughly five minutes.
    if provider.provider_type == "ollama":
        timeout = httpx.Timeout(connect=30.0, read=max(float(settings.ai_request_timeout_seconds), 900.0), write=60.0, pool=60.0)
    else:
        timeout = httpx.Timeout(float(settings.ai_request_timeout_seconds))
    usage: dict[str, Any] = {}
    stop_reason: str | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider.provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES:
            base = provider_base_url(provider.provider_type, provider.base_url)
            headers = {"Authorization": f"Bearer {_secret(provider)}", "Content-Type": "application/json"}
            response = await client.post(
                base + "/chat/completions",
                headers=headers,
                json={
                    "model": model.model_identifier,
                    "messages": prompt_messages,
                    "temperature": model.temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            text = choice["message"]["content"]
            stop_reason = choice.get("finish_reason")
            raw_usage = body.get("usage") or {}
            usage = {
                "input_tokens": raw_usage.get("prompt_tokens"),
                "output_tokens": raw_usage.get("completion_tokens"),
                "total_tokens": raw_usage.get("total_tokens"),
            }
        elif provider.provider_type == "anthropic":
            base = (provider.base_url or "https://api.anthropic.com/v1").rstrip("/")
            headers = {"x-api-key": _secret(provider) or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
            response = await client.post(
                base + "/messages",
                headers=headers,
                json={
                    "model": model.model_identifier,
                    "system": prompt_messages[0]["content"],
                    "max_tokens": max_tokens,
                    # Temperature is intentionally omitted. Current Claude models
                    # accept provider defaults, and newer Opus generations reject
                    # non-default sampling parameters.
                    "messages": prompt_messages[1:],
                },
            )
            response.raise_for_status()
            body = response.json()
            text = "\n".join(x.get("text", "") for x in body.get("content", []) if x.get("type") == "text")
            stop_reason = body.get("stop_reason")
            raw_usage = body.get("usage") or {}
            usage = {
                "input_tokens": raw_usage.get("input_tokens"),
                "output_tokens": raw_usage.get("output_tokens"),
            }
            if usage["input_tokens"] is not None and usage["output_tokens"] is not None:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        elif provider.provider_type == "ollama":
            base = (provider.base_url or "http://127.0.0.1:11434").rstrip("/")
            parts: list[str] = []
            generated_chars = 0
            stream_events = 0
            last_progress = 0.0
            last_cancel_check = 0.0
            final_chunk: dict[str, Any] = {}
            started = time.monotonic()
            async with client.stream(
                "POST",
                base + "/api/chat",
                json={
                    "model": model.model_identifier,
                    "messages": prompt_messages,
                    "stream": True,
                    "options": {
                        "temperature": model.temperature,
                        "num_predict": max_tokens,
                        "num_ctx": context_window_tokens,
                    },
                },
            ) as response:
                response.raise_for_status()
                cancel_event = asyncio.Event()

                async def watch_cancel() -> None:
                    if not cancel_check:
                        return
                    while not cancel_event.is_set():
                        await asyncio.sleep(0.5)
                        if cancel_check():
                            cancel_event.set()
                            await response.aclose()
                            return

                cancel_task = asyncio.create_task(watch_cancel())
                try:
                    async for line in response.aiter_lines():
                        now = time.monotonic()
                        if cancel_event.is_set() or (cancel_check and now - last_cancel_check >= 0.75 and cancel_check()):
                            raise AiGenerationCancelled("AI_JOB_CANCELLED")
                        last_cancel_check = now
                        if not line:
                            continue
                        chunk = json.loads(line)
                        message_chunk = chunk.get("message") or {}
                        piece = str(message_chunk.get("content") or "")
                        thinking_piece = str(message_chunk.get("thinking") or "")
                        if piece:
                            parts.append(piece)
                        if piece or thinking_piece:
                            generated_chars += len(piece) + len(thinking_piece)
                            stream_events += 1
                        if chunk.get("done"):
                            final_chunk = chunk
                        if (piece or thinking_piece) and (now - last_progress >= 0.6 or stream_events % 32 == 0):
                            last_progress = now
                            estimate = max(stream_events, max(1, round(generated_chars / 3.7)))
                            _emit_progress(
                                progress_callback,
                                stage="generation",
                                message="AI response is being generated",
                                max_output_tokens=max_tokens,
                                output_tokens_estimate=min(max_tokens, estimate),
                                output_tokens_exact=None,
                                generated_chars=generated_chars,
                                elapsed_seconds=round(now - started, 1),
                                streaming=True,
                            )
                except httpx.HTTPError as exc:
                    if cancel_event.is_set() or (cancel_check and cancel_check()):
                        raise AiGenerationCancelled("AI_JOB_CANCELLED") from exc
                    raise
                finally:
                    cancel_event.set()
                    cancel_task.cancel()
                    try:
                        await cancel_task
                    except asyncio.CancelledError:
                        pass
            if cancel_check and cancel_check():
                raise AiGenerationCancelled("AI_JOB_CANCELLED")
            text = "".join(parts)
            stop_reason = final_chunk.get("done_reason")
            usage = {
                "input_tokens": final_chunk.get("prompt_eval_count"),
                "output_tokens": final_chunk.get("eval_count"),
            }
            if usage["input_tokens"] is not None and usage["output_tokens"] is not None:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            _emit_progress(
                progress_callback,
                stage="finalizing",
                message="AI response received · finalizing",
                max_output_tokens=max_tokens,
                output_tokens_estimate=usage.get("output_tokens") or max(stream_events, round(generated_chars / 3.7)),
                output_tokens_exact=usage.get("output_tokens"),
                input_tokens=usage.get("input_tokens"),
                elapsed_seconds=round(time.monotonic() - started, 1),
                streaming=True,
            )
        else:
            raise RuntimeError("UNSUPPORTED_LLM_PROVIDER")

    if cancel_check and cancel_check():
        raise AiGenerationCancelled("AI_JOB_CANCELLED")

    output_tokens = usage.get("output_tokens")
    truncated = stop_reason in {"length", "max_tokens"} or (
        isinstance(output_tokens, int) and output_tokens >= max_tokens
    )
    return {
        "content": text,
        "provider": provider.name,
        "model": model.display_name,
        "model_identifier": model.model_identifier,
        "model_id": str(model.id),
        "local": provider.is_local,
        "max_output_tokens": max_tokens,
        "requested_max_output_tokens": requested_output_tokens,
        "output_budget_adjusted": output_budget_adjusted,
        "context_window_tokens": context_window_tokens,
        "context_budget_tokens": context_budget_tokens,
        "usage": usage,
        "stop_reason": stop_reason,
        "truncated": truncated,
        "message_chars": used_message_chars,
        **context_meta,
    }


async def test_provider(provider_type: str, base_url: str | None, api_key: str | None) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider_type == "ollama":
            response = await client.get((base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/tags")
            response.raise_for_status()
            models = [x.get("name") for x in response.json().get("models", [])]
            return {"ok": True, "models": models}
        if provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES:
            base = provider_base_url(provider_type, base_url)
            response = await client.get(base + "/models", headers={"Authorization": f"Bearer {api_key or ''}"})
            response.raise_for_status()
            return {"ok": True, "models": [x.get("id") for x in response.json().get("data", [])][:100]}
        if provider_type == "anthropic":
            base = (base_url or "https://api.anthropic.com/v1").rstrip("/")
            headers = {
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            response = await client.get(base + "/models", headers=headers, params={"limit": 100})
            response.raise_for_status()
            data = response.json().get("data", [])
            details = [{
                "id": x.get("id"),
                "display_name": x.get("display_name") or x.get("id"),
                "context_window": x.get("max_input_tokens"),
                "max_output_tokens": x.get("max_tokens"),
            } for x in data if x.get("id")]
            return {"ok": True, "models": [x["id"] for x in details], "model_details": details}
    return {"ok": False}
