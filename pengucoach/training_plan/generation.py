from __future__ import annotations

from typing import Any

from .structured import STRUCTURED_PLAN_INSTRUCTION, TrainingPlanDocument, extract_structured_plan, render_plan_markdown


def training_plan_instruction(base_prompt: str) -> str:
    base = (base_prompt or "").strip()
    return f"{base}\n\n{STRUCTURED_PLAN_INSTRUCTION}".strip()


def normalize_training_plan_answer(answer: dict[str, Any], locale: str) -> tuple[str, dict[str, Any]]:
    """Validate the machine plan and produce deterministic human-readable Markdown.

    Local models occasionally ignore format instructions. That does not make the
    AI job fail: in that case the original prose remains visible and metadata
    records why calendar/Garmin export is unavailable for that run.
    """
    raw_content = str(answer.get("content") or "")
    plan, error = extract_structured_plan(raw_content)
    if plan is None:
        return raw_content, {
            "structured_plan": None,
            "structured_plan_valid": False,
            "structured_plan_error": error,
        }
    return render_plan_markdown(plan, locale), {
        "structured_plan": plan.model_dump(mode="json"),
        "structured_plan_valid": True,
        "structured_plan_error": None,
    }


def merge_plan_segments(segments: list[TrainingPlanDocument], total_weeks: int) -> TrainingPlanDocument:
    """Merge independently generated week segments into one validated plan.

    Segment week numbers are local (1..segment length). ``segment_start_week`` is
    carried in each session metadata by the caller via a temporary attribute-free
    remap before this helper is invoked, so sessions already contain absolute weeks.
    IDs are normalized here to avoid collisions between chunk-local identifiers.
    """
    if not segments:
        raise ValueError("NO_PLAN_SEGMENTS")
    sessions = []
    sequence = 0
    for segment in segments:
        for session in segment.sessions:
            sequence += 1
            item = session.model_copy(deep=True)
            item.id = f"w{item.week}-d{item.day}-{item.sport}-{sequence}"
            sessions.append(item)
    first = segments[0]
    return TrainingPlanDocument(
        format_version=1,
        title=first.title,
        summary=first.summary,
        weeks=total_weeks,
        sessions=sessions,
    )
