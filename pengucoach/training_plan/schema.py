"""Generation constraints that Pydantic's after-validators cannot describe.

Saved plans retain the backwards-compatible document model. New generations get
explicit alternatives so providers can avoid invalid combinations before output.
All answers still pass the normal document and weekly-completeness validation.
"""
from __future__ import annotations

import copy
from typing import Any

from .structured import TrainingPlanDocument


def generation_schema(weeks: int, days_per_week: int, base: dict[str, Any] | None = None) -> dict[str, Any]:
    schema = copy.deepcopy(base) if base is not None else TrainingPlanDocument.model_json_schema()
    definitions = schema["$defs"]
    schema["properties"]["weeks"].update(const=weeks)
    schema["properties"]["sessions"]["minItems"] = weeks * days_per_week
    schema["properties"]["sessions"]["description"] = (
        f"At least {days_per_week} actual sessions in EACH local week 1..{weeks}; "
        f"at least {weeks * days_per_week} sessions in total. No rest-day placeholders."
    )
    definitions["TrainingSession"]["properties"]["week"]["maximum"] = weeks

    original = definitions["PlanStep"]
    variants = []
    for name, required in (("TimedPlanStep", "duration_seconds"), ("DistancePlanStep", "distance_meters"), ("RepeatPlanStep", "repeat")):
        variant = copy.deepcopy(original)
        props = variant["properties"]
        variant["title"] = name
        variant["additionalProperties"] = False
        variant["required"] = ["type", required]
        props["type"] = {"type": "string", "const": "repeat"} if name == "RepeatPlanStep" else {
            "type": "string", "enum": ["warmup", "work", "interval", "recovery", "cooldown", "rest"]}
        if name == "RepeatPlanStep":
            props["repeat"] = {"type": "integer", "minimum": 2, "maximum": 100}
            props["steps"]["minItems"] = 1
            variant["required"].append("steps")
            props["duration_seconds"] = {"type": "null"}
            props["distance_meters"] = {"type": "null"}
            props["target"] = {"$ref": "#/$defs/NoStepTarget"}
        else:
            props[required] = copy.deepcopy(props[required]["anyOf"][0])
            props["repeat"] = {"type": "null"}
            props["steps"]["maxItems"] = 0
            if name == "DistancePlanStep":
                props["duration_seconds"] = {"type": "null"}
        definitions[name] = variant
        variants.append({"$ref": f"#/$defs/{name}"})
    definitions["PlanStep"] = {"title": "PlanStep", "anyOf": variants}

    # The typed targets also have a conditional requirement: a zone target
    # needs a zone, whereas a repeat container carries no executable target.
    definitions["NoStepTarget"] = {"type": "object", "properties": {
        "type": {"type": "string", "const": "none"}, "zone": {"type": "null"}},
        "additionalProperties": False}
    definitions["PlanTarget"] = {"anyOf": [
        {"$ref": "#/$defs/NoStepTarget"},
        {"type": "object", "properties": {
            "type": {"type": "string", "enum": ["heart_rate_zone", "power_zone"]},
            "zone": {"type": "integer", "minimum": 1, "maximum": 10}},
            "required": ["type", "zone"], "additionalProperties": False},
    ]}

    original = definitions["StrengthExercise"]
    variants = []
    for name, target in (("RepExercise", "reps"), ("TimedExercise", "duration_seconds"), ("ReserveExercise", "reps_in_reserve")):
        variant = copy.deepcopy(original)
        variant["title"] = name
        variant["additionalProperties"] = False
        variant["required"] = ["name", target]
        props = variant["properties"]
        for key in ("reps", "duration_seconds", "reps_in_reserve"):
            props[key] = copy.deepcopy(props[key]["anyOf"][0]) if key == target else {"type": "null"}
        if target != "reps":
            props["reps_max"] = {"type": "null"}
        definitions[name] = variant
        variants.append({"$ref": f"#/$defs/{name}"})
    definitions["StrengthExercise"] = {"title": "StrengthExercise", "anyOf": variants}
    return schema
