"""Retrospective readiness, observed personal patterns and bounded milestones."""
from datetime import date, timedelta
from statistics import mean

from pengucoach.coach.readiness import compute_readiness
from pengucoach.coach.workout_review import number


def readiness_history(context, checkins, activities, feedback, *, today, days=28):
    rows = []
    active_days = {a["date"] for a in activities}
    for i in range(days-1, -1, -1):
        day = today-timedelta(days=i)
        # No later measurements enter a historical baseline or recommendation.
        window = {key: [r for r in context.get(key, []) if day-timedelta(days=28) <= date.fromisoformat(str(r["date"])) <= day] for key in ("health_30d", "sleep_30d", "hrv_30d")}
        recent = [f for f in feedback if day-timedelta(days=2) <= date.fromisoformat(f["date"]) <= day]
        consecutive = 0
        for n in range(1, 8):
            if (day-timedelta(days=n)).isoformat() in active_days:
                consecutive += 1
            else:
                break
        ready = compute_readiness(window, checkins.get(day.isoformat(), {}), recent, consecutive_active_days=consecutive, today=day)
        recorded = [a for a in activities if a["date"] == day.isoformat()]
        durations = [number(a.get("duration_seconds")) for a in recorded]
        minutes = round(sum(v for v in durations if v is not None)/60) if any(v is not None for v in durations) else None
        rows.append({"date": day.isoformat(), "score": ready["score"], "status": ready["status"], "confidence": ready["confidence"], "training_minutes": minutes, "sessions": len(recorded), "factors": ready["available_factors"]})
    return rows


def personal_patterns(sleeps, checkins, feedback):
    """Day-level cohorts, >=3 days each; display associations, never causes."""
    sleep = {str(r["date"]): number(r.get("duration_s")) for r in sleeps}
    result = []
    cohorts = {"short": [], "long": []}
    for day, check in checkins.items():
        duration, energy = sleep.get(day), number(check.get("energy"))
        if duration is None or energy is None:
            continue
        if duration < 6*3600:
            cohorts["short"].append((day, energy))
        elif 7*3600 <= duration <= 9*3600:
            cohorts["long"].append((day, energy))
    if min(map(len, cohorts.values())) >= 3:
        short, long = mean(v for _, v in cohorts["short"]), mean(v for _, v in cohorts["long"])
        if abs(long-short) >= .5:
            result.append({"key": "sleep_energy", "short_value": round(short, 1), "long_value": round(long, 1), "unit": "/5", "short_days": len(cohorts["short"]), "long_days": len(cohorts["long"]), "dates": {k: [d for d, _ in values] for k, values in cohorts.items()}})
    # Multiple activities on one day count as one observation.
    by_day = {}
    for f in feedback:
        day = f["date"]
        by_day[day] = by_day.get(day, False) or f.get("feeling") == "hard" or (number(f.get("exertion")) or 0) >= 9
    cohorts = {"short": [], "long": []}
    for day, hard in by_day.items():
        duration = sleep.get(day)
        if duration is None:
            continue
        if duration < 6*3600:
            cohorts["short"].append((day, int(hard)))
        elif 7*3600 <= duration <= 9*3600:
            cohorts["long"].append((day, int(hard)))
    if min(map(len, cohorts.values())) >= 3:
        short, long = mean(v for _, v in cohorts["short"])*100, mean(v for _, v in cohorts["long"])*100
        if abs(short-long) >= 20:
            result.append({"key": "sleep_feedback", "short_value": round(short), "long_value": round(long), "unit": "%", "short_days": len(cohorts["short"]), "long_days": len(cohorts["long"]), "dates": {k: [d for d, _ in values] for k, values in cohorts.items()}})
    return result


def milestones(activities, today):
    # Explicit 90-day window: never claim an all-time record from a short window.
    start = today-timedelta(days=89)
    rows = [a for a in activities if start.isoformat() <= a["date"] <= today.isoformat()]
    result = []
    monday = today-timedelta(days=today.weekday())
    weeks = [[a for a in rows if (monday-timedelta(days=7*n)).isoformat() <= a["date"] < (monday-timedelta(days=7*(n-1))).isoformat()] for n in (2, 1)]
    if all(len({a["date"] for a in week}) >= 3 for week in weeks):
        result.append({"key": "regularity", "value": sum(len(week) for week in weeks), "weeks": 2, "date": (monday-timedelta(days=1)).isoformat(), "from": (monday-timedelta(days=14)).isoformat(), "to": (monday-timedelta(days=1)).isoformat(), "activity_ids": [a["id"] for week in weeks for a in week]})
    for sport in ("running", "cycling", "swimming", "walking", "hiking"):
        sport_rows = [a for a in rows if a.get("sport") == sport and (number(a.get("duration_seconds")) or 0) >= 20*60]
        if len(sport_rows) < 4:
            continue
        longest = max(sport_rows, key=lambda a: a["duration_seconds"])
        earlier = [a for a in sport_rows if a["date"] < longest["date"]]
        if longest["date"] >= (today-timedelta(days=6)).isoformat() and len(earlier) >= 3 and longest["duration_seconds"] >= max(a["duration_seconds"] for a in earlier)*1.1:
            result.append({"key": "longest_session", "sport": sport, "value": round(longest["duration_seconds"]/60), "previous": round(max(a["duration_seconds"] for a in earlier)/60), "date": longest["date"], "activity_id": longest["id"], "window_days": 90})
    return result
