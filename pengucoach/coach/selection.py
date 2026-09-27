from pydantic import BaseModel


class ContextSelection(BaseModel):
    training: bool = True
    zones: bool = True
    sleep_hrv: bool = True
    recovery: bool = True
    daily_activity: bool = True
    hydration: bool = True
    body: bool = True


def context_selection(payload: dict) -> dict[str, bool]:
    data = ContextSelection.model_validate(payload.get("context_data") or {})
    return {f"include_{key}": value for key, value in data.model_dump().items()}


def auto_context_days(message: str) -> int:
    # Follow-ups like "und heute?" need the same evidence as an explicit training
    # question. A tiny keyword classifier must not silently disable the data.
    import re
    match = re.search(r"\b(3|7|14|21|28)\s*(?:tage[ns]?|days?)\b", message.lower())
    return int(match.group(1)) if match else 7
