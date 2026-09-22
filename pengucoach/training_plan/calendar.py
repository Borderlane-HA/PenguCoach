from __future__ import annotations

from datetime import date, timedelta

from .structured import TrainingPlanDocument, TrainingSession


def scheduled_date(start_date: date, session: TrainingSession) -> date:
    """Map ISO weekday/week index to a concrete date.

    ``start_date`` represents Monday of week 1. The UI defaults to the next
    Monday and labels the field accordingly to avoid timezone ambiguity.
    """
    return start_date + timedelta(days=(session.week - 1) * 7 + (session.day - 1))


def selected_sessions(plan: TrainingPlanDocument, session_ids: list[str] | None) -> list[TrainingSession]:
    if session_ids is None:
        return list(plan.sessions)
    wanted = set(session_ids)
    return [session for session in plan.sessions if session.id in wanted]


def apply_session_overrides(
    sessions: list[TrainingSession],
    overrides: dict[str, TrainingSession | dict] | None,
) -> list[TrainingSession]:
    """Apply user edits prepared in the calendar before Garmin export.

    Identity/scheduling fields stay immutable: an edit may change the visible
    name, duration, notes, structured steps and strength exercises, but it may
    not silently move a workout to another week/day or change its sport/id.
    """
    if not overrides:
        return list(sessions)
    known = {session.id for session in sessions}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError("UNKNOWN_TRAINING_SESSION_OVERRIDE")
    result: list[TrainingSession] = []
    for original in sessions:
        raw = overrides.get(original.id)
        if raw is None:
            result.append(original)
            continue
        edited = raw if isinstance(raw, TrainingSession) else TrainingSession.model_validate(raw)
        if (
            edited.id != original.id
            or edited.week != original.week
            or edited.day != original.day
            or edited.sport != original.sport
        ):
            raise ValueError("TRAINING_SESSION_OVERRIDE_IDENTITY_MISMATCH")
        result.append(edited)
    return result
