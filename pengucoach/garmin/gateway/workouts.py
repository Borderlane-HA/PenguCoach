from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from garminconnect import Garmin, exercises
from garminconnect.workout import (
    BaseWorkout,
    CyclingWorkout,
    ExecutableStep,
    HikingWorkout,
    RepeatGroup,
    RunningWorkout,
    StrengthWorkout,
    SwimmingWorkout,
    WalkingWorkout,
    WorkoutSegment,
    create_repeat_group,
    create_strength_set,
)

from pengucoach.training_plan.structured import PlanStep, TrainingSession


# (sport id, Garmin key, workout class, upload method).  Garmin's library has
# typed helpers for the core endurance/strength sports.  For Garmin workout
# sports that have a valid sportType but no dedicated typed helper (mobility,
# yoga, Pilates, HIIT), PenguCoach uses BaseWorkout + the generic upload_workout
# endpoint.  The regular Garmin data sync remains strictly read-only.
_SPORT_META: dict[str, tuple[int, str, type, str]] = {
    "running": (1, "running", RunningWorkout, "upload_running_workout"),
    "cycling": (2, "cycling", CyclingWorkout, "upload_cycling_workout"),
    "swimming": (4, "swimming", SwimmingWorkout, "upload_swimming_workout"),
    "walking": (17, "walking", WalkingWorkout, "upload_walking_workout"),
    "hiking": (18, "hiking", HikingWorkout, "upload_hiking_workout"),
    "strength": (5, "strength_training", StrengthWorkout, "upload_strength_workout"),
    "cardio": (6, "cardio_training", BaseWorkout, "upload_workout"),
    "yoga": (7, "yoga", BaseWorkout, "upload_workout"),
    "pilates": (8, "pilates", BaseWorkout, "upload_workout"),
    "hiit": (9, "hiit", BaseWorkout, "upload_workout"),
    "mobility": (11, "mobility", BaseWorkout, "upload_workout"),
}

_SIMPLE_TIMED_SPORTS = {"cardio", "yoga", "pilates", "hiit", "mobility"}

_STEP_META = {
    "warmup": (1, "warmup", 1),
    "cooldown": (2, "cooldown", 2),
    "interval": (3, "interval", 3),
    "work": (3, "interval", 3),
    "recovery": (4, "recovery", 4),
    "rest": (5, "rest", 5),
}

# AI output is deliberately human-readable and can be localized. Garmin's
# bundled exercise catalogue, however, resolves exact English display names.
# These canonical aliases cover the common generic exercises PenguCoach asks a
# training model to use. They are category/exercise pairs from Garmin's own
# catalogue, so existing German plans can be retried without regeneration.
_GARMIN_EXERCISE_ALIASES: dict[str, tuple[str, str]] = {
    "kniebeuge": ("SQUAT", "SQUAT"),
    "kniebeugen": ("SQUAT", "SQUAT"),
    "squat": ("SQUAT", "SQUAT"),
    "squats": ("SQUAT", "SQUAT"),
    "liegestutz": ("PUSH_UP", "PUSH_UP"),
    "liegestutze": ("PUSH_UP", "PUSH_UP"),
    "push up": ("PUSH_UP", "PUSH_UP"),
    "push ups": ("PUSH_UP", "PUSH_UP"),
    "ausfallschritt": ("LUNGE", "LUNGE"),
    "ausfallschritte": ("LUNGE", "LUNGE"),
    "lunge": ("LUNGE", "LUNGE"),
    "lunges": ("LUNGE", "LUNGE"),
    "plank": ("PLANK", "PLANK"),
    "planke": ("PLANK", "PLANK"),
    "unterarmstutz": ("PLANK", "PLANK"),
    "side plank": ("PLANK", "SIDE_PLANK"),
    "seitstutz": ("PLANK", "SIDE_PLANK"),
    "seitliche planke": ("PLANK", "SIDE_PLANK"),
    "kreuzheben": ("DEADLIFT", "DEADLIFT"),
    "deadlift": ("DEADLIFT", "DEADLIFT"),
    "rudern": ("ROW", "ROW"),
    "row": ("ROW", "ROW"),
    "rowing": ("ROW", "ROW"),
    "beinpressen": ("SQUAT", "LEG_PRESS"),
    "beinpresse": ("SQUAT", "LEG_PRESS"),
    "leg press": ("SQUAT", "LEG_PRESS"),
    "bankdrucken": ("BENCH_PRESS", "BENCH_PRESS"),
    "bench press": ("BENCH_PRESS", "BENCH_PRESS"),
    "wadenheben": ("CALF_RAISE", "CALF_RAISE"),
    "calf raise": ("CALF_RAISE", "CALF_RAISE"),
}


def supported_workout_sports() -> list[str]:
    return list(_SPORT_META)


def session_exportability(session: TrainingSession) -> tuple[bool, str | None]:
    if session.sport not in _SPORT_META:
        return False, "SPORT_NOT_SUPPORTED_BY_GARMIN_WORKOUT_EXPORT"
    if session.sport == "strength" and not session.strength_exercises:
        return False, "STRENGTH_EXERCISES_MISSING"
    # Mobility/yoga/Pilates/HIIT/cardio can be represented by one timed Garmin
    # main step even when the AI intentionally did not create sub-steps.
    if session.sport not in {"strength", *_SIMPLE_TIMED_SPORTS} and not session.steps:
        return False, "STRUCTURED_STEPS_MISSING"
    return True, None


def _target_payload(step: PlanStep) -> tuple[dict[str, Any], dict[str, Any]]:
    if step.target.type == "heart_rate_zone" and step.target.zone:
        if step.target.zone > 5:
            raise ValueError("GARMIN_HR_ZONE_OUT_OF_RANGE")
        return (
            {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
            {"zoneNumber": step.target.zone},
        )
    if step.target.type == "power_zone" and step.target.zone:
        if step.target.zone > 7:
            raise ValueError("GARMIN_POWER_ZONE_OUT_OF_RANGE")
        return (
            {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone", "displayOrder": 2},
            {"zoneNumber": step.target.zone},
        )
    return ({"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}, {})


def _build_endurance_steps(session: TrainingSession) -> list[ExecutableStep | RepeatGroup]:
    order = 1

    def build(spec: PlanStep) -> ExecutableStep | RepeatGroup:
        nonlocal order
        step_order = order
        order += 1
        if spec.type == "repeat":
            children = [build(child) for child in spec.steps]
            return create_repeat_group(int(spec.repeat or 2), children, step_order)

        step_id, step_key, display_order = _STEP_META[spec.type]
        if spec.duration_seconds is not None:
            end_condition = {
                "conditionTypeId": 2,
                "conditionTypeKey": "time",
                "displayOrder": 2,
                "displayable": True,
            }
            end_value = float(spec.duration_seconds)
        elif spec.distance_meters is not None:
            end_condition = {
                "conditionTypeId": 3,
                "conditionTypeKey": "distance",
                "displayOrder": 3,
                "displayable": True,
            }
            end_value = float(spec.distance_meters)
        else:  # schema validation should make this unreachable
            raise ValueError("GARMIN_STEP_END_CONDITION_MISSING")

        target_type, target_extra = _target_payload(spec)
        return ExecutableStep(
            stepOrder=step_order,
            stepType={"stepTypeId": step_id, "stepTypeKey": step_key, "displayOrder": display_order},
            endCondition=end_condition,
            endConditionValue=end_value,
            targetType=target_type,
            description=spec.description or None,
            **target_extra,
        )

    return [build(step) for step in session.steps]


def _normalise_exercise_name(value: str) -> str:
    value = value.strip().lower().replace("ß", "ss")
    value = "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )
    value = value.replace("-", " ")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _exercise_candidates(name: str) -> list[str]:
    """Return safe alternatives from a human/AI exercise label.

    Examples: ``Kreuzheben (oder ähnliches)`` -> ``Kreuzheben`` and
    ``Bankdrücken oder Liegestütz`` -> ``Bankdrücken``, ``Liegestütz``.
    """
    raw = str(name or "").strip()
    if not raw:
        return []
    without_notes = re.sub(r"\([^)]*\)", " ", raw).strip()
    candidates = [raw, without_notes]
    for value in (raw, without_notes):
        candidates.extend(re.split(r"\s+(?:oder|or|bzw\.?|alternativ)\s+|\s*/\s*|\s*\|\s*", value, flags=re.IGNORECASE))
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        value = value.strip(" .,:;-–—")
        if value and value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
    return result


def _resolve_strength_exercise(name: str) -> dict[str, str] | None:
    # 1) Prefer exact Garmin catalogue display names when the model obeyed the
    # English-name instruction.
    for candidate in _exercise_candidates(name):
        resolved = exercises.resolve(candidate)
        if resolved and resolved.get("category"):
            return {
                "category": str(resolved["category"]),
                "exercise": str(resolved.get("exercise") or ""),
                "display_name": candidate,
            }

    # 2) Map common localized/general labels to known stable Garmin catalogue
    # identifiers. This fixes existing stored plans too.
    for candidate in _exercise_candidates(name):
        alias = _GARMIN_EXERCISE_ALIASES.get(_normalise_exercise_name(candidate))
        if alias:
            return {"category": alias[0], "exercise": alias[1], "display_name": candidate}

    # 3) Last safe fallback: case/diacritic-insensitive *exact* display-name
    # comparison. Do not fuzzy-map a strength movement to a different exercise.
    catalogue = getattr(exercises, "EXERCISES", None)
    if catalogue:
        wanted = {_normalise_exercise_name(x) for x in _exercise_candidates(name)}
        for row in catalogue:
            if isinstance(row, (tuple, list)) and len(row) >= 3:
                display, category, exercise_name = row[0], row[1], row[2]
                if _normalise_exercise_name(str(display)) in wanted:
                    return {
                        "category": str(category),
                        "exercise": str(exercise_name),
                        "display_name": str(display),
                    }
            elif isinstance(row, dict):
                display = str(row.get("name") or row.get("display_name") or "")
                if _normalise_exercise_name(display) in wanted and row.get("category"):
                    return {
                        "category": str(row["category"]),
                        "exercise": str(row.get("exercise") or ""),
                        "display_name": display,
                    }
    return None


def _build_strength_steps(session: TrainingSession) -> list[RepeatGroup]:
    result: list[RepeatGroup] = []
    order = 1
    for exercise in session.strength_exercises:
        resolved = _resolve_strength_exercise(exercise.name)
        if not resolved:
            raise ValueError(f"GARMIN_EXERCISE_NOT_FOUND:{exercise.name}")
        result.append(
            create_strength_set(
                resolved["category"],
                step_order=order,
                sets=exercise.sets,
                reps=exercise.reps,
                rest_seconds=float(exercise.rest_seconds),
                exercise_name=resolved["exercise"],
                weight_kg=exercise.weight_kg,
            )
        )
        order += 3
    return result


def _build_simple_timed_steps(session: TrainingSession) -> list[ExecutableStep | RepeatGroup]:
    if session.steps:
        return _build_endurance_steps(session)
    return [
        ExecutableStep(
            stepOrder=1,
            stepType={"stepTypeId": 8, "stepTypeKey": "main", "displayOrder": 8},
            endCondition={
                "conditionTypeId": 2,
                "conditionTypeKey": "time",
                "displayOrder": 2,
                "displayable": True,
            },
            endConditionValue=float(session.duration_min * 60),
            targetType={"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
            description=(session.notes or session.name)[:500],
        )
    ]


def build_typed_workout(session: TrainingSession) -> Any:
    exportable, reason = session_exportability(session)
    if not exportable:
        raise ValueError(reason or "SESSION_NOT_EXPORTABLE")

    sport_id, sport_key, workout_cls, _ = _SPORT_META[session.sport]
    if session.sport == "strength":
        steps = _build_strength_steps(session)
    elif session.sport in _SIMPLE_TIMED_SPORTS:
        steps = _build_simple_timed_steps(session)
    else:
        steps = _build_endurance_steps(session)
    sport_type = {"sportTypeId": sport_id, "sportTypeKey": sport_key, "displayOrder": sport_id}
    segment = WorkoutSegment(
        segmentOrder=1,
        sportType=sport_type,
        workoutSteps=steps,
    )
    description = session.notes.strip() or "Created by PenguCoach"
    kwargs = {
        "workoutName": ("PenguCoach · " + session.name)[:120],
        "estimatedDurationInSecs": session.duration_min * 60,
        "description": description[:1000],
        "workoutSegments": [segment],
    }
    if workout_cls is BaseWorkout:
        kwargs["sportType"] = sport_type
    return workout_cls(**kwargs)


class GarminWorkoutGateway:
    """Narrow write-only facade for PenguCoach workout/calendar operations.

    The regular Garmin synchronization keeps using ``GarminReadOnlyGateway``.
    This facade is instantiated only after the user explicitly enables workout
    export and an export request names concrete plan sessions.
    """

    def __init__(self, client: Garmin) -> None:
        self.__client = client

    def upload_session(self, session: TrainingSession) -> dict[str, Any]:
        workout = build_typed_workout(session)
        upload_method = _SPORT_META[session.sport][3]
        if upload_method == "upload_workout":
            return self.__client.upload_workout(workout.to_dict())
        method = getattr(self.__client, upload_method)
        return method(workout)

    def schedule_workout(self, workout_id: int | str, scheduled_date: date) -> dict[str, Any]:
        return self.__client.schedule_workout(workout_id, scheduled_date.isoformat())

    def unschedule_workout(self, scheduled_workout_id: int | str) -> Any:
        return self.__client.unschedule_workout(scheduled_workout_id)

    def delete_workout(self, workout_id: int | str) -> Any:
        return self.__client.delete_workout(workout_id)
