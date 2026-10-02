"""Reviewable, deterministic plan matching and seven-day schedule proposals."""
from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from pengucoach.db.models import Activity, ActivityFeedback, ActivityMetric, AiRun, GarminConnection, PlanActivityMatch, PlanSchedule, SparkyFitnessConnection
from pengucoach.common.dates import day_start, user_today, user_zone
from pengucoach.coach.training_intelligence import _is_hard_session, sport_family, weather_assessment
from pengucoach.training_plan.structured import TrainingSession


def local_day(activity, user):
    stamp = activity.started_at
    if stamp is None:
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(user_zone(user)).date()


def targets(steps):
    result = []
    for step in steps or []:
        target = step.get("target") or {}
        if target.get("type") != "none" and target.get("zone"):
            result.append({"type": target["type"], "zone": target["zone"]})
        result.extend(targets(step.get("steps")))
    return [dict(t) for t in sorted({tuple(sorted(x.items())) for x in result})]


def compare_v2(sessions, activities, user, *, confirmed=None, reserved=None, other_sessions=None):
    """Shifted days are suggestions only; uncertain and missing records stay pending."""
    confirmed, reserved = confirmed or {}, set(reserved or [])
    claimed = {str(m.activity_id) for m in confirmed.values() if m.activity_id}
    candidates = {}
    for s in [*sessions, *(other_sessions or [])]:
        key = s.get("match_key", s["id"])
        if key in confirmed:
            continue
        day = date.fromisoformat(s["date"])
        rows = []
        for a in activities:
            aid = str(a.id)
            actual_day = local_day(a, user)
            if aid in reserved | claimed or actual_day is None or sport_family(a.sport_type) != sport_family(s["sport"]):
                continue
            delta = (actual_day - day).days
            if abs(delta) > 3:
                continue
            minutes = a.duration_seconds / 60 if a.duration_seconds else None
            ratio = abs(minutes - s["duration_min"]) / s["duration_min"] if minutes is not None else None
            score = round(max(0, 100 - abs(delta) * 18 - (min(60, ratio * 80) if ratio is not None else 30)))
            rows.append({"id": aid, "name": a.name or a.sport_type, "date": actual_day.isoformat(), "minutes": round(minutes, 1) if minutes is not None else None, "day_difference": delta, "duration_difference": round(minutes-s["duration_min"], 1) if minutes is not None else None, "score": score, "same_day": delta == 0, "duration_close": ratio is not None and ratio <= .25})
        candidates[key] = sorted(rows, key=lambda r: (-r["score"], r["id"]))[:12]
    same_day_uses = {}
    for rows in candidates.values():
        for r in rows:
            if r["same_day"]:
                same_day_uses[r["id"]] = same_day_uses.get(r["id"], 0) + 1
    by_id = {str(a.id): a for a in activities}
    result = []
    for s in sessions:
        rows = candidates.get(s["id"], [])
        manual = confirmed.get(s["id"])
        same = [r for r in rows if r["same_day"]]
        automatic = same[0] if len(same) == 1 and same[0]["duration_close"] and same_day_uses[same[0]["id"]] == 1 else None
        aid = str(manual.activity_id) if manual and manual.activity_id else automatic["id"] if automatic and not manual else None
        a = by_id.get(aid)
        status = "matched" if a else "unmatched" if manual and manual.state == "missed" else "ambiguous" if rows else "pending" if date.fromisoformat(s["date"]) < user_today(user) else "planned"
        actual = round(a.duration_seconds/60, 1) if a and a.duration_seconds is not None else None
        result.append({**s, "status": status, "activity_id": aid if a else None, "actual_date": local_day(a, user).isoformat() if a else None, "actual_minutes": actual, "difference_minutes": round(actual-s["duration_min"], 1) if actual is not None else None, "candidates": rows, "candidate_ids": [r["id"] for r in rows], "match_basis": "user_confirmed" if manual and a else "same_local_day_sport_duration" if a else None, "manual_state": manual.state if manual else None, "planned_targets": targets(s.get("steps")), "avg_hr": a.avg_hr if a else None, "avg_power": a.avg_power if a else None, "intensity_comparison": "actual_sensor_values_only; average values cannot verify intervals or time in zones"})
    return result


def seconds(step):
    if step["type"] == "repeat":
        parts = [seconds(s) for s in step.get("steps", [])]
        return None if any(x is None for x in parts) else step["repeat"] * sum(parts)
    return step.get("duration_seconds") if not step.get("distance_meters") else None


def short_variant(session, minutes):
    """Preserve warmup/cooldown, interval duration/recovery and strength rest/reps."""
    if not 5 <= minutes < session["duration_min"]:
        raise ValueError("SHORTER_DURATION_REQUIRED")
    after = copy.deepcopy(session)
    reasons = ["available_time"]
    if session["sport"] == "strength":
        exercises = after.get("strength_exercises") or []
        total = sum(x["sets"] for x in exercises)
        if not total:
            raise ValueError("STRUCTURED_STRENGTH_REQUIRED")
        desired = int(total * minutes / session["duration_min"])
        if desired < len(exercises):
            raise ValueError("MINIMUM_SESSION_DURATION")
        while sum(x["sets"] for x in exercises) > desired:
            max(exercises, key=lambda x: x["sets"])["sets"] -= 1
        reasons.append("fewer_sets_same_reps_and_rest; duration_is_estimated")
    else:
        steps = after.get("steps") or []
        if not steps:
            steps = [{"type": "work", "duration_seconds": minutes * 60, "target": {"type": "none"}}]
            reasons.append("duration_only_no_structured_targets")
        else:
            values = [seconds(s) for s in steps]
            if any(x is None for x in values):
                raise ValueError("DISTANCE_STEP_NEEDS_TIMED_DRAFT")
            if abs(sum(values) - session["duration_min"] * 60) > 60:
                raise ValueError("STEP_DURATION_MISMATCH")
            budget = minutes * 60
            # Remove entire repetitions rather than shortening interval/rest pairs.
            for step in steps:
                if step["type"] == "repeat":
                    cycle = sum(seconds(s) for s in step["steps"])
                    total_seconds = sum(seconds(s) for s in steps)
                    while total_seconds > budget and step["repeat"] > 1:
                        step["repeat"] -= 1
                        total_seconds -= cycle
                        reasons.append("fewer_complete_repetitions")
            # Continuous work can shrink; preparation and recovery stay unchanged.
            excess = sum(seconds(s) for s in steps) - budget
            for step in sorted([s for s in steps if s["type"] == "work"], key=lambda s: -s["duration_seconds"]):
                cut = min(max(0, step["duration_seconds"] - 60), max(0, excess))
                step["duration_seconds"] -= cut
                excess -= cut
            if excess > 0:
                raise ValueError("MINIMUM_SESSION_DURATION")
            expanded = []
            for step in steps:
                if step["type"] == "repeat" and step["repeat"] == 1:
                    expanded.extend(step["steps"])
                else:
                    expanded.append(step)
            steps = expanded
            remaining = budget - sum(seconds(s) for s in steps)
            if remaining:
                idx = next((i for i,s in enumerate(steps) if s["type"] == "cooldown"), len(steps))
                steps.insert(idx, {"type": "work", "duration_seconds": remaining, "target": {"type": "none"}, "description": "Locker / Easy"})
            reasons.append("warmup_cooldown_and_recovery_preserved")
        after["steps"] = steps
    after["duration_min"] = minutes
    after["name"] = ("Kurz / Short · " + session["name"])[:120]
    after["notes"] = (session.get("notes", "") + "\nZeitangepasste Kurzvariante; kein intensiveres Training. / Time-adjusted short variant; no intensity increase.")[-1500:]
    validated = TrainingSession.model_validate(after).model_dump()
    if "date" in session:
        validated["date"] = session["date"]
    return {"before": session, "after": validated, "reasons": list(dict.fromkeys(reasons))}


def week_proposal(sessions, comparison, *, start, plan_start, weeks, profile, availability,
                  readiness, today, locked=None, weather=None, blocked_dates=None, caution=False):
    """Keep the plan's sessions/identity; never insert missed workouts or increase load."""
    end = min(start + timedelta(days=6), plan_start + timedelta(weeks=weeks) - timedelta(days=1))
    allowed = set(profile.get("training_days") or range(1,8))
    caps = { (start + timedelta(days=i)).isoformat(): availability.get((start + timedelta(days=i)).isoformat(), profile.get("session_minutes") or 480) for i in range(7) }
    locked = set(locked or [])
    done = {s["id"] for s in comparison if s["status"] == "matched"}
    unresolved = sum(s["status"] in {"pending", "ambiguous"} and s["date"] < start.isoformat() for s in comparison)
    warning = ["unresolved_past_sessions_not_added"] if unresolved else []
    occupied = set(blocked_dates or [])
    hard_days = {date.fromisoformat(s["date"]) for s in sessions if _is_hard_session(s) and (s["id"] in done or s["id"] in locked or s["date"] > end.isoformat()) and abs((date.fromisoformat(s["date"])-start).days) <= 7}
    candidates = sorted([s for s in sessions if start.isoformat() <= s["date"] <= end.isoformat()], key=lambda s: (s["id"] not in locked | done, s["date"], s["id"]))
    result = []
    weather = weather or {}
    for before in candidates:
        reasons = []
        if before["id"] in locked | done:
            occupied.add(before["date"])
            if _is_hard_session(before):
                hard_days.add(date.fromisoformat(before["date"]))
            result.append({"before": before, "after": before, "reasons": ["garmin_export_locked" if before["id"] in locked else "already_completed"], "changed": False})
            continue
        hard = _is_hard_session(before)
        options = []
        for day_index in range(7):
            day = start + timedelta(days=day_index)
            key = day.isoformat()
            if day > end or day < plan_start or day < today or day.isoweekday() not in allowed or key in occupied or caps[key] < 5:
                continue
            if any(s["id"] != before["id"] and s["id"] not in {r["before"]["id"] for r in result} and s["date"] == key for s in candidates):
                continue
            if hard and any(abs((day - d).days) <= 1 for d in hard_days):
                continue
            if day == today and (caution or readiness.get("status") in {"red", "yellow"}) and hard:
                continue
            assessment = weather_assessment(weather.get(key), before["sport"]) or {}
            score = abs((day - date.fromisoformat(before["date"])).days) * 3 + (12 if assessment.get("indoor_recommended") else 0) + (8 if caps[key] < before["duration_min"] else 0)
            options.append((score, day))
        if not options:
            warning.append("no_suitable_slot:" + before["id"])
            occupied.add(before["date"])
            if hard:
                hard_days.add(date.fromisoformat(before["date"]))
            result.append({"before": before, "after": before, "reasons": ["no_suitable_slot_review_manually"], "changed": False})
            continue
        day = min(options)[1]
        after = copy.deepcopy(before)
        offset = (day - plan_start).days
        after.update(date=day.isoformat(), week=offset//7 + 1, day=offset%7 + 1)
        if after["date"] != before["date"]:
            reasons.append("availability_spacing_and_weather")
        cap = caps[day.isoformat()]
        if day == today and (caution or readiness.get("status") == "yellow"):
            cap = min(cap, max(5, int(before["duration_min"] * .75)))
            reasons.append("today_recovery")
        if cap < before["duration_min"]:
            try:
                shortened = short_variant(after, cap)
                after = shortened["after"]
                reasons.extend(shortened["reasons"])
            except ValueError:
                warning.append("short_variant_unavailable:" + before["id"])
                occupied.add(before["date"])
                if hard:
                    hard_days.add(date.fromisoformat(before["date"]))
                result.append({"before": before, "after": before, "reasons": ["minimum_duration_review_manually"], "changed": False})
                continue
        assessment = weather_assessment(weather.get(day.isoformat()), before["sport"]) or {}
        if assessment.get("indoor_recommended"):
            after["name"] = ("Indoor · " + after["name"])[:120]
            after["notes"] = (after.get("notes", "") + "\nIndoor-Alternative wegen Wetter / Indoor alternative due to weather")[-1500:]
            reasons.append("weather_indoor")
        occupied.add(day.isoformat())
        if hard:
            hard_days.add(day)
        result.append({"before": before, "after": after, "reasons": reasons or ["plan_fits"], "changed": before != after})
    return {"start": start.isoformat(), "end": end.isoformat(), "items": result, "warnings": list(dict.fromkeys(warning)), "unresolved_past_sessions": unresolved, "method": "deterministic_seven_day_review", "readiness_scope": "today_only", "forecast_dates": sorted(weather), "original_minutes": sum(s["before"]["duration_min"] for s in result), "proposed_minutes": sum(s["after"]["duration_min"] for s in result)}


async def freshness(db, user):
    result = []
    for name, model in (("garmin", GarminConnection), ("sparkyfitness", SparkyFitnessConnection)):
        row = await db.scalar(select(model).where(model.user_id == user.id))
        if not row:
            continue
        stamp = row.last_successful_sync_at
        normalized = stamp.replace(tzinfo=timezone.utc) if stamp and not stamp.tzinfo else stamp
        result.append({"source": name, "status": row.status, "last_successful_sync_at": normalized.isoformat() if normalized else None, "age_minutes": round(max(0,(datetime.now(timezone.utc)-normalized).total_seconds()/60)) if normalized else None, "last_error_code": row.last_error_code})
    return {"sources": result, "missing_records_are_not_missed_workouts": True}



async def comparison_data(db, user, run, schedule):
    from pengucoach.coach.companion import scheduled_sessions
    sessions = scheduled_sessions(run, schedule)
    start = min(date.fromisoformat(s["date"]) for s in sessions) - timedelta(days=3)
    end = max(date.fromisoformat(s["date"]) for s in sessions) + timedelta(days=4)
    all_matches = list((await db.scalars(select(PlanActivityMatch).where(PlanActivityMatch.user_id == user.id))).all())
    confirmed = {m.session_id: m for m in all_matches if m.plan_run_id == run.id}
    reserved = {str(m.activity_id) for m in all_matches if m.plan_run_id != run.id and m.activity_id}
    ids = [m.activity_id for m in confirmed.values() if m.activity_id]
    activities = list((await db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.started_at <= datetime.now(timezone.utc), or_(
        (Activity.started_at >= day_start(start,user)) & (Activity.started_at < day_start(end,user)),
        Activity.id.in_(ids),
    )))).all())
    other_sessions = []
    schedules = (await db.execute(select(PlanSchedule, AiRun).join(AiRun, AiRun.id == PlanSchedule.plan_run_id).where(PlanSchedule.user_id == user.id, PlanSchedule.plan_run_id != run.id))).all()
    for other_schedule, other_run in schedules:
        for s in scheduled_sessions(other_run, other_schedule):
            if start.isoformat() <= s["date"] < end.isoformat():
                if not any(m.plan_run_id == other_run.id and m.session_id == s["id"] for m in all_matches):
                    other_sessions.append({**s, "match_key": str(other_run.id)+":"+s["id"]})
    items = compare_v2(sessions, activities, user, confirmed=confirmed, reserved=reserved, other_sessions=other_sessions)
    matched_ids = [uuid.UUID(s["activity_id"]) for s in items if s["activity_id"]]
    feedback = {str(f.activity_id): f.data for f in (await db.scalars(select(ActivityFeedback).where(ActivityFeedback.user_id == user.id, ActivityFeedback.activity_id.in_(matched_ids)))).all()}
    metrics = {str(m.activity_id): m for m in (await db.scalars(select(ActivityMetric).where(ActivityMetric.user_id == user.id, ActivityMetric.activity_id.in_(matched_ids)))).all()}
    for s in items:
        s["feedback"] = feedback.get(s["activity_id"])
        metric = metrics.get(s["activity_id"])
        laps = ((metric.details or {}).get("session") or {}).get("_laps") if metric else None
        s["recorded_laps"] = [{"seconds": x.get("total_timer_time"), "avg_hr": x.get("avg_heart_rate"), "avg_power": x.get("avg_power")} for x in (laps or [])[:50]]
    return {"items": items, "freshness": await freshness(db,user)}
