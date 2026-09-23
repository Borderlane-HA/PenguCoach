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


def select_session_rows(sessions: list[TrainingSession], session_ids: list[str] | None) -> list[TrainingSession]:
    """Select sessions after calendar/export overrides have been applied."""
    if session_ids is None:
        return list(sessions)
    wanted = set(session_ids)
    return [session for session in sessions if session.id in wanted]


def apply_session_overrides(
    sessions: list[TrainingSession],
    overrides: dict[str, TrainingSession | dict] | None,
    *,
    max_week: int | None = None,
) -> list[TrainingSession]:
    """Apply the user's Garmin-export calendar draft.

    Content fields and the calendar slot (week/day) may be changed before
    export. Stable identity fields remain immutable: an edit may never change
    the session id or sport. Duplicate calendar slots are rejected so drag &
    drop cannot silently stack two workouts into one visual day.
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
        if edited.id != original.id or edited.sport != original.sport:
            raise ValueError("TRAINING_SESSION_OVERRIDE_IDENTITY_MISMATCH")
        if max_week is not None and edited.week > max_week:
            raise ValueError("TRAINING_SESSION_OVERRIDE_OUTSIDE_PLAN")
        result.append(edited)

    slots = [(session.week, session.day) for session in result]
    if len(slots) != len(set(slots)):
        raise ValueError("TRAINING_SESSION_OVERRIDE_SLOT_CONFLICT")
    return result
