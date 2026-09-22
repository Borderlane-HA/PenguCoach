from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

QUALITY_PROFILES = ("very_low", "low", "standard", "high")

_PROFILE_FACTORS: dict[str, dict[str, float]] = {
    "coach_chat": {"very_low": 0.35, "low": 0.60, "standard": 1.0, "high": 1.60},
    "activity_analysis": {"very_low": 0.50, "low": 0.75, "standard": 1.0, "high": 1.50},
    # Structured plans need enough room for all sessions. Savings are therefore
    # intentionally gentler than in chat/analysis and come mainly from compact prose.
    "training_plan": {"very_low": 0.60, "low": 0.80, "standard": 1.0, "high": 1.50},
}


def normalize_quality(value: Any) -> str:
    text = str(value or "standard")
    return text if text in QUALITY_PROFILES else "standard"


def quality_budget(task: str, standard_tokens: int, profile: str) -> int:
    profile = normalize_quality(profile)
    factor = _PROFILE_FACTORS.get(task, _PROFILE_FACTORS["coach_chat"])[profile]
    return max(128, min(65536, int(round(standard_tokens * factor))))


def quality_options(task: str, standard_tokens: int) -> list[dict[str, Any]]:
    return [
        {"id": profile, "max_output_tokens": quality_budget(task, standard_tokens, profile)}
        for profile in QUALITY_PROFILES
    ]


def quality_instruction(profile: str, locale: str, task: str) -> str:
    profile = normalize_quality(profile)
    de = str(locale).lower().startswith("de")
    if profile == "standard":
        return ""
    if task == "training_plan":
        if profile == "very_low":
            return ("\nQUALITÄTSPROFIL SEHR NIEDRIG: Erzeuge den vollständigen strukturierten Plan mit allen verlangten "
                    "Einheiten und Schritten, aber extrem knapp. Keine Wiederholungen, minimale Beschreibungen/Notizen, kurze Namen. "
                    "Strukturelle Vollständigkeit hat Vorrang vor Erklärtext.") if de else (
                    "\nQUALITY PROFILE VERY LOW: Produce the complete structured plan with every requested session and step, "
                    "but be extremely concise. No repetition, minimal descriptions/notes, short names. Structural completeness comes first."
                )
        if profile == "low":
            return ("\nQUALITÄTSPROFIL NIEDRIG: Halte Beschreibungen und Notizen knapp, aber liefere alle Einheiten und Garmin-Schritte vollständig.") if de else (
                    "\nQUALITY PROFILE LOW: Keep descriptions and notes concise while preserving every session and Garmin step."
                )
        return ("\nQUALITÄTSPROFIL HOCH: Nutze das zusätzliche Budget für präzisere Trainingshinweise, Progression und sinnvolle kurze Begründungen; "
                "der strukturierte Plan muss weiterhin kompakt und vollständig bleiben.") if de else (
                "\nQUALITY PROFILE HIGH: Use the extra budget for more precise training guidance, progression and concise rationale; "
                "the structured plan must remain complete and efficient."
            )
    if profile == "very_low":
        return ("\nQUALITÄTSPROFIL SEHR NIEDRIG: Antworte maximal kompakt. Nur Ergebnis, wichtigste Begründung und konkrete nächste Schritte; keine Wiederholungen.") if de else (
                "\nQUALITY PROFILE VERY LOW: Be maximally concise. Give only the result, essential rationale and concrete next steps; no repetition."
            )
    if profile == "low":
        return ("\nQUALITÄTSPROFIL NIEDRIG: Antworte kompakt und priorisiere die wichtigsten Erkenntnisse und nächsten Schritte.") if de else (
                "\nQUALITY PROFILE LOW: Respond concisely and prioritize the most important findings and next steps."
            )
    return ("\nQUALITÄTSPROFIL HOCH: Antworte ausführlicher mit nachvollziehbarer Begründung, relevanten Alternativen und konkreten nächsten Schritten.") if de else (
            "\nQUALITY PROFILE HIGH: Answer in more depth with clear rationale, relevant alternatives and concrete next steps."
        )


def model_pricing(metadata: dict[str, Any] | None) -> dict[str, float | None]:
    meta = metadata if isinstance(metadata, dict) else {}
    def value(key: str) -> float | None:
        raw = meta.get(key)
        if raw is None or raw == "":
            return None
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None
    return {
        "input_eur_per_million": value("input_cost_per_million_eur"),
        "output_eur_per_million": value("output_cost_per_million_eur"),
    }


def calculate_cost_eur(usage: dict[str, Any] | None, pricing: dict[str, Any] | None) -> float | None:
    usage = usage if isinstance(usage, dict) else {}
    pricing = pricing if isinstance(pricing, dict) else {}
    p_in = pricing.get("input_eur_per_million")
    p_out = pricing.get("output_eur_per_million")
    if p_in is None and p_out is None:
        return None
    try:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cost = input_tokens * float(p_in or 0) / 1_000_000 + output_tokens * float(p_out or 0) / 1_000_000
        return round(cost, 8)
    except (TypeError, ValueError):
        return None


def period_start(period: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    if period == "year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "month_current":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None
