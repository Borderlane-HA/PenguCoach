from pathlib import Path

import pytest

from pengucoach.training_plan.calendar import apply_session_overrides
from pengucoach.training_plan.structured import TrainingSession


def _session(session_id: str, day: int) -> TrainingSession:
    return TrainingSession.model_validate({
        "id": session_id,
        "week": 1,
        "day": day,
        "name": session_id,
        "sport": "running",
        "duration_min": 45,
        "steps": [{"type": "work", "duration_seconds": 2700}],
    })


def test_calendar_overrides_allow_move_and_swap_but_reject_slot_conflicts():
    monday = _session("mon-run", 1)
    wednesday = _session("wed-run", 3)

    moved = monday.model_copy(deep=True)
    moved.day = 2
    result = apply_session_overrides([monday, wednesday], {monday.id: moved}, max_week=1)
    assert [(x.id, x.day) for x in result] == [("mon-run", 2), ("wed-run", 3)]

    conflict = monday.model_copy(deep=True)
    conflict.day = 3
    with pytest.raises(ValueError, match="TRAINING_SESSION_OVERRIDE_SLOT_CONFLICT"):
        apply_session_overrides([monday, wednesday], {monday.id: conflict}, max_week=1)

    swapped_monday = monday.model_copy(deep=True)
    swapped_monday.day = 3
    swapped_wednesday = wednesday.model_copy(deep=True)
    swapped_wednesday.day = 1
    result = apply_session_overrides(
        [monday, wednesday],
        {monday.id: swapped_monday, wednesday.id: swapped_wednesday},
        max_week=1,
    )
    assert [(x.id, x.day) for x in result] == [("mon-run", 3), ("wed-run", 1)]


def test_calendar_ui_and_export_apply_dragged_slots_before_selection():
    ui = Path("apps/web/components/TrainingPlanCalendar.tsx").read_text()
    css = Path("apps/web/app/globals.css").read_text()
    router = Path("apps/api/routers/garmin_workouts.py").read_text()
    worker = Path("worker/tasks/garmin_workouts.py").read_text()
    calendar = Path("pengucoach/training_plan/calendar.py").read_text()

    assert "moveSession(sourceId:string,targetWeek:number,targetDay:number)" in ui
    assert 'draggable={!exported}' in ui
    assert 'e.dataTransfer.setData("text/plain",session.id)' in ui
    assert "Trainingseinheiten wurden getauscht" in ui
    assert "const overrides=edits" in ui
    assert ".training-day.drag-over" in css
    assert "select_session_rows" in router
    assert "select_session_rows" in worker
    assert "TRAINING_SESSION_OVERRIDE_SLOT_CONFLICT" in calendar
