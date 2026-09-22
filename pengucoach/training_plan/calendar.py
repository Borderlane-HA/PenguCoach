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
