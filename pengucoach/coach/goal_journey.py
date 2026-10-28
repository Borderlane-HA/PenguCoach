"""Measurable goals grounded in recorded activities, with no inferred fitness score."""
import math
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from pengucoach.coach.companion import activity_day, sport_family
from pengucoach.common.dates import user_zone


class GoalJourneyIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    metric: Literal["distance_km", "duration_min", "sessions"] = "distance_km"
    sport: Literal["running", "cycling", "walking", "hiking", "swimming", "strength", "any"] = "running"
    target: float = Field(gt=0, le=10000, allow_inf_nan=False)
    start_date: date
    target_date: date | None = None
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_goal(self):
        self.title = self.title.strip()
        if not self.title or self.start_date < date(2000, 1, 1):
            raise ValueError("GOAL_DETAILS_REQUIRED")
        if self.target_date and self.target_date < self.start_date:
            raise ValueError("TARGET_DATE_BEFORE_START")
        if self.metric == "sessions" and (not self.target.is_integer() or self.target > 1000):
            raise ValueError("WHOLE_SESSION_TARGET_REQUIRED")
        if self.metric == "duration_min" and self.target > 1440:
            raise ValueError("DURATION_TARGET_TOO_LARGE")
        if self.metric == "distance_km" and self.sport in {"strength", "any"}:
            raise ValueError("DISTANCE_SPORT_REQUIRED")
        return self


def goal_progress(goal, activities, user, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = date.fromisoformat(goal["start_date"])
    end = date.fromisoformat(goal["target_date"]) if goal.get("target_date") else now.astimezone(user_zone(user)).date()
    # Compare both local calendar dates and actual instants; never count future records.
    eligible = []
    for activity in activities:
        stamp = activity.started_at
        if not stamp:
            continue
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        day = activity_day(activity, user)
        if stamp > now or day < start or day > end:
            continue
        if goal["sport"] != "any" and sport_family(activity.sport_type) != goal["sport"]:
            continue
        field = activity.distance_m if goal["metric"] == "distance_km" else activity.duration_seconds
        if field is None or not math.isfinite(float(field)) or field <= 0:
            continue
        if goal["metric"] == "sessions" and field < 300:
            continue
        value = float(field) / (1000 if goal["metric"] == "distance_km" else 60)
        eligible.append((activity, 1.0 if goal["metric"] == "sessions" else value, day))
    eligible.sort(key=lambda x: (x[2], str(x[0].id)))
    target = float(goal["target"])
    value = float(len(eligible)) if goal["metric"] == "sessions" else max((x[1] for x in eligible), default=0.0)
    thresholds = sorted({float(math.ceil(target * n / 4)) if goal["metric"] == "sessions" else target * n / 4 for n in range(1, 5)})
    milestones = []
    for threshold in thresholds:
        evidence = eligible[int(threshold)-1] if goal["metric"] == "sessions" and len(eligible) >= threshold else next((x for x in eligible if x[1] >= threshold), None) if goal["metric"] != "sessions" else None
        milestones.append({"value": round(threshold, 3), "reached": evidence is not None,
                           "date": evidence[2].isoformat() if evidence else None,
                           "activity_id": str(evidence[0].id) if evidence else None})
    best = max(eligible, key=lambda x: x[1]) if eligible else None
    return {"value": round(value, 3) if eligible else None, "target": target,
            "percent": round(min(100, value / target * 100)), "observed_activities": len(eligible),
            "status": "achieved" if value >= target else "in_progress" if eligible else "no_data",
            "milestones": milestones, "evidence": {"activity_id": str(best[0].id), "name": best[0].name, "date": best[2].isoformat()} if best else None}
