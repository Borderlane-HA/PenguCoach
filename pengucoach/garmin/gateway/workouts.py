from __future__ import annotations

from datetime import date
from typing import Any

from garminconnect import Garmin, exercises
from garminconnect.workout import (
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


_SPORT_META: dict[str, tuple[int, str, type, str]] = {
    "running": (1, "running", RunningWorkout, "upload_running_workout"),
    "cycling": (2, "cycling", CyclingWorkout, "upload_cycling_workout"),
    "swimming": (4, "swimming", SwimmingWorkout, "upload_swimming_workout"),
    "walking": (17, "walking", WalkingWorkout, "upload_walking_workout"),
    "hiking": (18, "hiking", HikingWorkout, "upload_hiking_workout"),
    "strength": (5, "strength_training", StrengthWorkout, "upload_strength_workout"),
}

_STEP_META = {
    "warmup": (1, "warmup", 1),
    "cooldown": (2, "cooldown", 2),
    "interval": (3, "interval", 3),
    "work": (3, "interval", 3),
    "recovery": (4, "recovery", 4),
    "rest": (5, "rest", 5),
}


def supported_workout_sports() -> list[str]:
    return list(_SPORT_META)


def session_exportability(session: TrainingSession) -> tuple[bool, str | None]:
    if session.sport not in _SPORT_META:
        return False, "SPORT_NOT_SUPPORTED_BY_GARMIN_WORKOUT_EXPORT"
    if session.sport == "strength" and not session.strength_exercises:
        return False, "STRENGTH_EXERCISES_MISSING"
    if session.sport != "strength" and not session.steps:
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


def _build_strength_steps(session: TrainingSession) -> list[RepeatGroup]:
    result: list[RepeatGroup] = []
    order = 1
    for exercise in session.strength_exercises:
        resolved = exercises.resolve(exercise.name)
        if not resolved:
            raise ValueError(f"GARMIN_EXERCISE_NOT_FOUND:{exercise.name}")
        category = str(resolved.get("category") or "").strip()
        exercise_name = str(resolved.get("exercise") or "").strip()
        if not category:
            raise ValueError(f"GARMIN_EXERCISE_NOT_FOUND:{exercise.name}")
        result.append(
            create_strength_set(
                category,
                step_order=order,
                sets=exercise.sets,
                reps=exercise.reps,
                rest_seconds=float(exercise.rest_seconds),
                exercise_name=exercise_name,
                weight_kg=exercise.weight_kg,
            )
        )
        order += 3
    return result


def build_typed_workout(session: TrainingSession) -> Any:
    exportable, reason = session_exportability(session)
    if not exportable:
        raise ValueError(reason or "SESSION_NOT_EXPORTABLE")

    sport_id, sport_key, workout_cls, _ = _SPORT_META[session.sport]
    steps = _build_strength_steps(session) if session.sport == "strength" else _build_endurance_steps(session)
    segment = WorkoutSegment(
        segmentOrder=1,
        sportType={"sportTypeId": sport_id, "sportTypeKey": sport_key},
        workoutSteps=steps,
    )
    description = session.notes.strip() or "Created by PenguCoach"
    return workout_cls(
        workoutName=("PenguCoach · " + session.name)[:120],
        estimatedDurationInSecs=session.duration_min * 60,
        description=description[:1000],
        workoutSegments=[segment],
    )


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
        method = getattr(self.__client, upload_method)
        return method(workout)

    def schedule_workout(self, workout_id: int | str, scheduled_date: date) -> dict[str, Any]:
        return self.__client.schedule_workout(workout_id, scheduled_date.isoformat())

    def unschedule_workout(self, scheduled_workout_id: int | str) -> Any:
        return self.__client.unschedule_workout(scheduled_workout_id)

    def delete_workout(self, workout_id: int | str) -> Any:
        return self.__client.delete_workout(workout_id)
