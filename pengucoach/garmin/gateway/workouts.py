from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from difflib import SequenceMatcher
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


def normalize_exercise_name(value: str) -> str:
    """Normalize a human exercise label for stable per-user mappings."""
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


def _catalog_rows() -> list[dict[str, str]]:
    rows = getattr(exercises, "EXERCISES", None) or []
    result: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("display_name") or "").strip()
            category = str(row.get("category") or "").strip()
            exercise_name = str(row.get("exercise") or "").strip()
        elif isinstance(row, (tuple, list)) and len(row) >= 3:
            name, category, exercise_name = (str(row[0]).strip(), str(row[1]).strip(), str(row[2]).strip())
        else:
            continue
        if name and category:
            result.append({"name": name, "category": category, "exercise": exercise_name})
    return result


def catalog_exercise_by_name(name: str) -> dict[str, str] | None:
    """Resolve an exact Garmin display name, with a normalized exact fallback."""
    resolved = exercises.resolve(name)
    if resolved and resolved.get("category"):
        return {
            "name": str(resolved.get("name") or name),
            "category": str(resolved["category"]),
            "exercise": str(resolved.get("exercise") or ""),
        }
    wanted = normalize_exercise_name(name)
    if not wanted:
        return None
    for row in _catalog_rows():
        if normalize_exercise_name(row["name"]) == wanted:
            return row
    return None


def search_exercise_catalog(term: str, limit: int = 20) -> list[dict[str, str]]:
    """Return ranked Garmin catalogue suggestions without auto-selecting fuzzy hits."""
    limit = max(1, min(int(limit), 100))
    needle = normalize_exercise_name(term)
    rows = _catalog_rows()
    if not needle:
        return rows[:limit]
    needle_tokens = set(needle.split())

    def score(row: dict[str, str]) -> tuple[int, float, int, str]:
        name = normalize_exercise_name(row["name"])
        name_tokens = set(name.split())
        if name == needle:
            bucket = 0
        elif name.startswith(needle) or needle.startswith(name):
            bucket = 1
        elif needle in name:
            bucket = 2
        elif needle_tokens and needle_tokens.issubset(name_tokens):
            bucket = 3
        elif needle_tokens & name_tokens:
            bucket = 4
        else:
            bucket = 5
        similarity = SequenceMatcher(None, needle, name).ratio()
        return (bucket, -similarity, abs(len(name) - len(needle)), row["name"].casefold())

    ranked = sorted(rows, key=score)
    # Keep fuzzy-only suggestions conservative; they are displayed to the user
    # and are never applied automatically.
    useful = [row for row in ranked if score(row)[0] < 5 or -score(row)[1] >= 0.42]
    return useful[:limit]


def _mapping_value(
    mappings: Mapping[str, Mapping[str, Any]] | None,
    source_name: str,
) -> Mapping[str, Any] | None:
    if not mappings:
        return None
    return mappings.get(normalize_exercise_name(source_name))


def resolve_strength_exercise(
    name: str,
    mappings: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    allow_generic_fallback: bool = False,
) -> dict[str, Any] | None:
    """Resolve a strength exercise without unsafe fuzzy auto-mapping.

    User mappings intentionally override built-in language aliases, so someone
    can permanently choose e.g. ``Barbell Back Squat`` for a local label that
    would otherwise map to Garmin's generic ``Squat``. Unknown movements can
    optionally fall back to Garmin's real ``Total Body`` catalogue item.
    """
    candidates = _exercise_candidates(name)

    # 1) Exact Garmin display names are unambiguous and need no stored mapping.
    for candidate in candidates:
        resolved = catalog_exercise_by_name(candidate)
        if resolved:
            return {**resolved, "display_name": resolved["name"], "resolution": "exact", "fallback": False}

    # 2) Per-user persisted choice.
    for candidate in candidates:
        mapped = _mapping_value(mappings, candidate)
        if mapped and mapped.get("category"):
            return {
                "name": str(mapped.get("display_name") or mapped.get("name") or candidate),
                "display_name": str(mapped.get("display_name") or mapped.get("name") or candidate),
                "category": str(mapped["category"]),
                "exercise": str(mapped.get("exercise") or ""),
                "resolution": "saved",
                "fallback": False,
            }

    # 3) Curated language aliases for existing plans.
    for candidate in candidates:
        alias = _GARMIN_EXERCISE_ALIASES.get(normalize_exercise_name(candidate))
        if alias:
            display = next((row["name"] for row in _catalog_rows() if row["category"] == alias[0] and row["exercise"] == alias[1]), candidate)
            return {
                "name": display,
                "display_name": display,
                "category": alias[0],
                "exercise": alias[1],
                "resolution": "alias",
                "fallback": False,
            }

    if allow_generic_fallback:
        # ``Total Body`` is an actual Garmin catalogue exercise. This preserves
        # the whole strength workout when a single AI label is unknown while the
        # preview clearly tells the user which movement should be mapped.
        generic = catalog_exercise_by_name("Total Body") or {"name": "Total Body", "category": "TOTAL_BODY", "exercise": "TOTAL_BODY"}
        return {
            **generic,
            "display_name": generic["name"],
            "resolution": "generic_fallback",
            "fallback": True,
        }
    return None


def strength_exercise_validation(
    session: TrainingSession,
    mappings: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, spec in enumerate(session.strength_exercises):
        resolved = resolve_strength_exercise(spec.name, mappings, allow_generic_fallback=False)
        if resolved:
            result.append({
                "index": index,
                "source_name": spec.name,
                "resolved": True,
                "mapping_source": resolved["resolution"],
                "garmin_name": resolved["display_name"],
                "category": resolved["category"],
                "exercise": resolved["exercise"],
                "generic_fallback": False,
                "suggestions": [],
            })
            continue
        result.append({
            "index": index,
            "source_name": spec.name,
            "resolved": False,
            "mapping_source": "generic_fallback",
            "garmin_name": "Total Body",
            "category": "TOTAL_BODY",
            "exercise": "TOTAL_BODY",
            "generic_fallback": True,
            "suggestions": search_exercise_catalog(spec.name, limit=5),
        })
    return result


def _build_strength_steps(
    session: TrainingSession,
    mappings: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[RepeatGroup]:
    result: list[RepeatGroup] = []
    order = 1
    for exercise in session.strength_exercises:
        resolved = resolve_strength_exercise(exercise.name, mappings, allow_generic_fallback=True)
        if not resolved:  # defensive: generic fallback should make this unreachable
            raise ValueError(f"GARMIN_EXERCISE_NOT_FOUND:{exercise.name}")
        result.append(
            create_strength_set(
                str(resolved["category"]),
                step_order=order,
                sets=exercise.sets,
                reps=exercise.reps,
                rest_seconds=float(exercise.rest_seconds),
                exercise_name=str(resolved.get("exercise") or ""),
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


def build_typed_workout(
    session: TrainingSession,
    exercise_mappings: Mapping[str, Mapping[str, Any]] | None = None,
) -> Any:
    exportable, reason = session_exportability(session)
    if not exportable:
        raise ValueError(reason or "SESSION_NOT_EXPORTABLE")

    sport_id, sport_key, workout_cls, _ = _SPORT_META[session.sport]
    if session.sport == "strength":
        steps = _build_strength_steps(session, exercise_mappings)
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
    if session.sport == "strength":
        unresolved = [
            item["source_name"]
            for item in strength_exercise_validation(session, exercise_mappings)
            if item["generic_fallback"]
        ]
        if unresolved:
            note = "Garmin generic fallback (Total Body): " + ", ".join(unresolved)
            description = (description + " | " + note).strip(" |")
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

    def upload_session(
        self,
        session: TrainingSession,
        exercise_mappings: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        workout = build_typed_workout(session, exercise_mappings)
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
