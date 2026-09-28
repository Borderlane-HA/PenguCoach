"""Deterministic, transparent training-readiness estimate.

This module deliberately does not call an LLM and does not make medical claims.
It combines only recorded recovery/training signals and explicit user feedback.
Missing data is ignored rather than interpreted as good or bad recovery.
"""
from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Any


def _dated(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get(field) is not None and row.get("date") is not None]


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _fresh(row: dict[str, Any] | None, today: date | None, max_age_days: int = 2) -> bool:
    if not row:
        return False
    if today is None:
        return True
    observed = _as_date(row.get("date"))
    return observed is not None and 0 <= (today - observed).days <= max_age_days


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


def _source(row: dict[str, Any], field: str) -> str:
    sources = row.get("sources") or {}
    return str(sources.get(field) or row.get("source") or "unknown")


def compute_readiness(
    context: dict[str, Any],
    checkin: dict[str, Any],
    recent_feedback: list[dict[str, Any]],
    *,
    consecutive_active_days: int = 0,
    today: date | None = None,
) -> dict[str, Any]:
    """Return a bounded score plus the exact factors that changed it.

    Score semantics are intentionally conservative:
    - 75..100 green: no meaningful recovery warning in the available signals
    - 50..74 yellow: consider reducing intensity/volume
    - 0..49 red: prefer recovery/easy work and reassess

    If fewer than two independent factors are available, no numeric score is
    returned. This avoids turning sparse data into false precision.
    """
    base = 70
    score = base
    components: list[dict[str, Any]] = []

    def add(key: str, impact: int, value: Any, *, baseline: Any = None, unit: str = "", date_value: Any = None, source: str = "user", state: str = "neutral") -> None:
        nonlocal score
        score += impact
        components.append({
            "key": key,
            "impact": impact,
            "value": value,
            "baseline": baseline,
            "unit": unit,
            "date": str(date_value) if date_value is not None else None,
            "source": source,
            "state": state,
        })

    sleeps = _dated(context.get("sleep_30d", []), "duration_s")
    if sleeps and _fresh(sleeps[-1], today):
        row = sleeps[-1]
        hours = float(row["duration_s"]) / 3600
        if hours < 5:
            impact, state = -22, "negative"
        elif hours < 6:
            impact, state = -15, "negative"
        elif hours < 7:
            impact, state = -7, "warning"
        elif hours <= 9:
            impact, state = 5, "positive"
        else:
            impact, state = 0, "neutral"
        add("sleep", impact, round(hours, 1), unit="h", date_value=row["date"], source=str(row.get("source") or "unknown"), state=state)

    hrv_rows = _dated(context.get("hrv_30d", []), "overnight_ms")
    if hrv_rows and _fresh(hrv_rows[-1], today):
        row = hrv_rows[-1]
        current = float(row["overnight_ms"])
        low, high = row.get("baseline_low_ms"), row.get("baseline_high_ms")
        baseline = None
        if low is not None and high is not None:
            baseline = round((float(low) + float(high)) / 2, 1)
            if current < float(low):
                impact, state = -14, "negative"
            elif current > float(high):
                impact, state = 4, "positive"
            else:
                impact, state = 3, "positive"
        else:
            previous = [float(x["overnight_ms"]) for x in hrv_rows[-15:-1]]
            baseline = _avg(previous)
            if baseline:
                delta = (current - baseline) / baseline
                if delta <= -0.15:
                    impact, state = -12, "negative"
                elif delta <= -0.07:
                    impact, state = -6, "warning"
                elif delta >= 0.07:
                    impact, state = 4, "positive"
                else:
                    impact, state = 1, "neutral"
            else:
                impact, state = 0, "neutral"
        add("hrv", impact, round(current, 1), baseline=baseline, unit="ms", date_value=row["date"], source=str(row.get("source") or "unknown"), state=state)

    health_rows = context.get("health_30d", [])
    resting = _dated(health_rows, "resting_hr_bpm")
    if resting and _fresh(resting[-1], today):
        row = resting[-1]
        current = float(row["resting_hr_bpm"])
        previous = [float(x["resting_hr_bpm"]) for x in resting[-15:-1]]
        baseline = _avg(previous)
        if baseline is None:
            impact, state = 0, "neutral"
        else:
            delta = current - baseline
            if delta >= 8:
                impact, state = -12, "negative"
            elif delta >= 4:
                impact, state = -6, "warning"
            elif delta <= -4:
                impact, state = 3, "positive"
            else:
                impact, state = 1, "neutral"
        add("resting_hr", impact, round(current, 1), baseline=baseline, unit="bpm", date_value=row["date"], source=_source(row, "resting_hr"), state=state)

    stress = _dated(health_rows, "stress_avg")
    if stress and _fresh(stress[-1], today):
        row = stress[-1]
        value = float(row["stress_avg"])
        impact, state = (-10, "negative") if value >= 70 else (-5, "warning") if value >= 50 else (3, "positive") if value < 35 else (0, "neutral")
        add("stress", impact, round(value, 1), unit="", date_value=row["date"], source=_source(row, "stress_avg"), state=state)

    battery = _dated(health_rows, "body_battery_high")
    if battery and _fresh(battery[-1], today):
        row = battery[-1]
        value = float(row["body_battery_high"])
        impact, state = (-10, "negative") if value < 25 else (-5, "warning") if value < 50 else (3, "positive") if value >= 75 else (0, "neutral")
        add("body_battery", impact, round(value, 1), date_value=row["date"], source=_source(row, "body_battery_high"), state=state)

    garmin_ready = _dated(health_rows, "training_readiness")
    if garmin_ready and _fresh(garmin_ready[-1], today):
        row = garmin_ready[-1]
        value = float(row["training_readiness"])
        impact, state = (-8, "negative") if value < 30 else (-4, "warning") if value < 50 else (4, "positive") if value >= 75 else (0, "neutral")
        add("provider_readiness", impact, round(value, 1), date_value=row["date"], source=_source(row, "training_readiness"), state=state)

    energy = checkin.get("energy")
    if energy is not None:
        impact = {1: -18, 2: -10, 3: 0, 4: 3, 5: 6}[int(energy)]
        add("energy", impact, int(energy), unit="/5", source="user", state="negative" if impact <= -10 else "warning" if impact < 0 else "positive" if impact > 0 else "neutral")

    soreness = checkin.get("soreness")
    if soreness is not None:
        impact = {1: 2, 2: 0, 3: -4, 4: -10, 5: -15}[int(soreness)]
        add("soreness", impact, int(soreness), unit="/5", source="user", state="negative" if impact <= -10 else "warning" if impact < 0 else "positive" if impact > 0 else "neutral")

    if str(checkin.get("discomfort") or "").strip():
        add("discomfort", -30, True, source="user", state="negative")

    hard_feedback = [f for f in recent_feedback if f.get("feeling") == "hard" or (f.get("exertion") or 0) >= 9]
    if hard_feedback:
        add("hard_feedback", -8, len(hard_feedback), source="user", state="warning")
    feedback_discomfort = [f for f in recent_feedback if str(f.get("discomfort") or "").strip()]
    if feedback_discomfort:
        add("feedback_discomfort", -10, len(feedback_discomfort), source="user", state="negative")

    if consecutive_active_days >= 3:
        add("consecutive_days", -5, consecutive_active_days, unit="days", source="training_history", state="warning")

    independent = {x["key"] for x in components}
    enough = len(independent) >= 2 or any(x["key"] == "provider_readiness" for x in components)
    if not enough:
        return {
            "score": None,
            "status": "insufficient",
            "confidence": "low",
            "recommendation": "review_plan",
            "components": components,
            "available_factors": len(independent),
            "method": "deterministic_v1",
            "notice": "Training estimate only; sparse data is not interpreted as recovery.",
        }

    score = max(0, min(100, int(round(score))))
    if any(x["key"] in {"discomfort", "feedback_discomfort"} for x in components):
        score = min(score, 39)
    status = "green" if score >= 75 else "yellow" if score >= 50 else "red"
    recommendation = "planned_ok" if status == "green" else "reduce" if status == "yellow" else "easy_or_rest"
    if any(x["key"] == "discomfort" for x in components):
        recommendation = "check_discomfort"
    confidence = "high" if len(independent) >= 6 else "medium" if len(independent) >= 3 else "low"
    return {
        "score": score,
        "status": status,
        "confidence": confidence,
        "recommendation": recommendation,
        "components": sorted(components, key=lambda x: (x["impact"] >= 0, x["impact"])),
        "available_factors": len(independent),
        "method": "deterministic_v1",
        "notice": "Training estimate only; not a medical assessment. Missing data is ignored.",
    }
