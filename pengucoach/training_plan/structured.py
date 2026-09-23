from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PLAN_OPEN = "<PENGUCOACH_PLAN_JSON>"
PLAN_CLOSE = "</PENGUCOACH_PLAN_JSON>"

Sport = Literal[
    "running", "cycling", "swimming", "walking", "hiking", "strength",
    "cardio", "mobility", "yoga", "pilates", "hiit", "other",
]
StepKind = Literal["warmup", "work", "interval", "recovery", "cooldown", "rest", "repeat"]
TargetKind = Literal["none", "heart_rate_zone", "power_zone"]


class PlanTarget(BaseModel):
    type: TargetKind = "none"
    zone: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def validate_zone(self) -> "PlanTarget":
        if self.type == "none":
            self.zone = None
        elif self.zone is None:
            raise ValueError("zone is required for zone targets")
        return self


class PlanStep(BaseModel):
    type: StepKind
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    distance_meters: float | None = Field(default=None, gt=0, le=500000)
    target: PlanTarget = Field(default_factory=PlanTarget)
    repeat: int | None = Field(default=None, ge=2, le=100)
    steps: list["PlanStep"] = Field(default_factory=list)
    description: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_shape(self) -> "PlanStep":
        if self.type == "repeat":
            if not self.repeat or not self.steps:
                raise ValueError("repeat steps require repeat and nested steps")
            self.duration_seconds = None
            self.distance_meters = None
        else:
            if self.steps or self.repeat:
                raise ValueError("only repeat steps may contain nested steps")
            if self.duration_seconds is None and self.distance_meters is None:
                raise ValueError("timed/distance steps require duration_seconds or distance_meters")
        return self


class StrengthExercise(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sets: int = Field(default=3, ge=1, le=20)
    reps: int = Field(default=10, ge=1, le=100)
    rest_seconds: int = Field(default=90, ge=0, le=1800)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)


class TrainingSession(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    week: int = Field(ge=1, le=24)
    day: int = Field(ge=1, le=7, description="ISO weekday: Monday=1, Sunday=7")
    name: str = Field(min_length=1, max_length=120)
    sport: Sport
    duration_min: int = Field(ge=5, le=480)
    optional: bool = False
    notes: str = Field(default="", max_length=1500)
    steps: list[PlanStep] = Field(default_factory=list)
    strength_exercises: list[StrengthExercise] = Field(default_factory=list)


class TrainingPlanDocument(BaseModel):
    format_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=2500)
    weeks: int = Field(ge=1, le=24)
    sessions: list[TrainingSession] = Field(min_length=1, max_length=168)

    @model_validator(mode="after")
    def validate_sessions(self) -> "TrainingPlanDocument":
        ids = [session.id for session in self.sessions]
        if len(ids) != len(set(ids)):
            raise ValueError("session ids must be unique")
        if any(session.week > self.weeks for session in self.sessions):
            raise ValueError("session week exceeds plan length")
        return self


STRUCTURED_PLAN_INSTRUCTION = f"""
IMPORTANT OUTPUT CONTRACT FOR PENGUCOACH:
Return the complete plan as one compact JSON object. Do not use Markdown fences and do not add prose before or after the JSON.
PenguCoach still accepts the legacy {PLAN_OPEN} / {PLAN_CLOSE} wrapper, but the wrapper is optional; provider-enforced
structured-output modes may return the bare JSON object. The API provides a hard output-token budget separately.
Fit the WHOLE plan inside that budget: shorten wording before reducing structure. Keep summary to at most two short
sentences, notes/descriptions to one short sentence when needed, use repeat groups instead of enumerating intervals,
and omit fields that merely repeat schema defaults (for example optional=false, empty notes/steps/exercise lists,
or target={{"type":"none"}}) when they add no information. Never sacrifice requested weeks or training sessions because
of token pressure. Close the JSON object and the PENGUCOACH marker before the budget is exhausted.

JSON schema/semantics:
- format_version: 1
- title: short plan title
- summary: concise coaching summary
- weeks: requested number of weeks
- sessions: only actual training sessions; do not create entries for rest days
- every session: id (unique, e.g. w1-d2-run), week (1..weeks), day (ISO weekday Monday=1), name,
  sport, duration_min, optional, notes, steps, strength_exercises
- sport must be one of: running, cycling, swimming, walking, hiking, strength, cardio, mobility, yoga, pilates, hiit, other
- steps are structured Garmin-style steps for endurance/cardio sessions. Step type must be one of:
  warmup, work, interval, recovery, cooldown, rest, repeat.
- a normal step has duration_seconds OR distance_meters and optional target.
- target is {{"type":"none"}} or {{"type":"heart_rate_zone","zone":1..5}} or
  {{"type":"power_zone","zone":1..7}}. Prefer the user's Garmin zones from context when available.
- a repeat step has repeat>=2 and nested steps. Example: 6 x (3 min interval + 2 min recovery).
- strength sessions should populate strength_exercises with canonical plain English Garmin exercise names plus sets/reps/rest_seconds;
  prefer simple catalogue names such as Squat, Push-up, Lunge, Plank, Side Plank, Deadlift, Row, Leg Press, Bench Press,
  and Calf Raise instead of localized names or phrases like "or similar"; steps may be empty for strength. Each strength_exercises
  item must be one concrete movement, never a circuit/block title, muscle-group label, superset name or descriptive session heading.
- for every timed non-strength session, the durations of all steps (including repeat multiplicity) should add up to
  duration_min * 60 within about 60 seconds. Do not duplicate a main/work step merely to fill text.
- keep intensity conservative when source data is incomplete. Do not invent measured values.
- honor fixed days/constraints and requested training days per week.
- the structured plan is the source of truth; it must contain enough detail to render the human-readable plan.
""".strip()


def extract_structured_plan(content: str) -> tuple[TrainingPlanDocument | None, str | None]:
    """Extract and validate the machine-readable plan block from an LLM response.

    Returns ``(plan, error)``. The caller can retain the original AI content if
    parsing fails, so generation remains useful even when a local model ignores
    the output contract.
    """
    if not content:
        return None, "EMPTY_RESPONSE"
    pattern = re.compile(re.escape(PLAN_OPEN) + r"\s*(.*?)\s*" + re.escape(PLAN_CLOSE), re.DOTALL)
    match = pattern.search(content)
    if not match:
        # Tolerate a model returning the bare object despite the explicit markers.
        raw = content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        if not (raw.startswith("{") and raw.endswith("}")):
            return None, "STRUCTURED_PLAN_MARKER_MISSING"
    else:
        raw = match.group(1).strip()
    try:
        value = json.loads(raw)
        return TrainingPlanDocument.model_validate(value), None
    except Exception as exc:  # pydantic/json errors become safe metadata, not a failed AI job.
        return None, f"STRUCTURED_PLAN_INVALID: {type(exc).__name__}: {str(exc)[:500]}"


def _target_label(target: PlanTarget, de: bool) -> str:
    if target.type == "heart_rate_zone" and target.zone:
        return f"HF Z{target.zone}" if de else f"HR Z{target.zone}"
    if target.type == "power_zone" and target.zone:
        return f"Power Z{target.zone}"
    return ""


def _step_label(step: PlanStep, de: bool) -> str:
    names = {
        "warmup": ("Einrollen/Warm-up", "Warm-up"),
        "work": ("Hauptteil", "Main"),
        "interval": ("Intervall", "Interval"),
        "recovery": ("Erholung", "Recovery"),
        "cooldown": ("Cool-down", "Cool-down"),
        "rest": ("Pause", "Rest"),
        "repeat": ("Wiederholen", "Repeat"),
    }
    label = names[step.type][0 if de else 1]
    if step.type == "repeat":
        inner = "; ".join(_step_label(child, de) for child in step.steps)
        return f"{step.repeat}× ({inner})"
    parts: list[str] = [label]
    if step.duration_seconds:
        minutes, seconds = divmod(step.duration_seconds, 60)
        parts.append(f"{minutes}:{seconds:02d} min" if seconds else f"{minutes} min")
    elif step.distance_meters:
        parts.append(f"{step.distance_meters / 1000:.1f} km" if step.distance_meters >= 1000 else f"{step.distance_meters:g} m")
    target = _target_label(step.target, de)
    if target:
        parts.append(target)
    if step.description:
        parts.append(step.description)
    return " · ".join(parts)


def render_plan_markdown(plan: TrainingPlanDocument, locale: str = "de") -> str:
    """Render deterministic readable Markdown from the validated plan JSON."""
    de = str(locale).startswith("de")
    day_names = (["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"] if de else ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    out = [f"# {plan.title}"]
    if plan.summary:
        out.extend(["", plan.summary])
    for week in range(1, plan.weeks + 1):
        out.extend(["", f"## {'Woche' if de else 'Week'} {week}"])
        sessions = sorted((x for x in plan.sessions if x.week == week), key=lambda x: x.day)
        if not sessions:
            out.append("- " + ("Regenerationswoche / keine geplante Einheit." if de else "Recovery week / no planned session."))
            continue
        for session in sessions:
            opt = " · optional" if session.optional else ""
            out.append(f"### {day_names[session.day - 1]} · {session.name}")
            out.append(f"**{session.sport} · {session.duration_min} min{opt}**")
            if session.notes:
                out.append(session.notes)
            if session.steps:
                out.extend(f"- {_step_label(step, de)}" for step in session.steps)
            if session.strength_exercises:
                for exercise in session.strength_exercises:
                    weight = f" · {exercise.weight_kg:g} kg" if exercise.weight_kg is not None else ""
                    out.append(f"- {exercise.name}: {exercise.sets}×{exercise.reps} · {exercise.rest_seconds}s {'Pause' if de else 'rest'}{weight}")
    return "\n".join(out).strip()
