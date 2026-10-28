"""Authenticated on-demand training reviews and personal progress."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.companion import activity_day, scheduled_sessions, sport_family
from pengucoach.coach.context import _sleep_payload, _hrv_payload
from pengucoach.coach.plan_evolution import comparison_data
from pengucoach.coach.progress import milestones, personal_patterns, readiness_history
from pengucoach.coach.workout_review import evaluate_goals, gps_points, number, route_match, route_metrics
from pengucoach.common.dates import day_start, user_today
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachCheckin, DailyHealth, FitFile, HrvDaily, PlanActivityMatch, PlanSchedule, SleepSession
from pengucoach.db.session import get_db
from pengucoach.fit.service import load_recording_series
from pengucoach.sparkyfitness.telemetry import telemetry
from pengucoach.garmin.zones import training_zone_snapshot
from apps.api.routers.activities import _owned_activity

router = APIRouter(tags=["training-insights"])


async def _series(db, user, activity, limit=5000):
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == activity.id, FitFile.user_id == user.id))
    return await asyncio.to_thread(load_recording_series, activity, fit, limit)


def _profile(snapshot, domain, sport):
    # Do not apply a different sport's zones merely because it is the only one.
    profiles = snapshot.get(domain, {}).get("profiles", [])
    aliases = {"cycling": "CYCLING", "running": "RUNNING", "swimming": "SWIMMING"}
    family = aliases.get(sport_family(sport), "DEFAULT")
    return next((p for p in profiles if p.get("sport") == family), None) or next((p for p in profiles if p.get("sport") == "DEFAULT"), {})


async def _matched_sessions(db, user, activity):
    matches = list((await db.scalars(select(PlanActivityMatch).where(PlanActivityMatch.user_id == user.id, PlanActivityMatch.activity_id == activity.id, PlanActivityMatch.state == "matched"))).all())
    schedules = list((await db.scalars(select(PlanSchedule).where(PlanSchedule.user_id == user.id).order_by(PlanSchedule.updated_at.desc()).limit(5))).all())
    for match in matches:
        if not any(s.plan_run_id == match.plan_run_id for s in schedules):
            schedule = await db.get(PlanSchedule, match.plan_run_id)
            if schedule and schedule.user_id == user.id:
                schedules.append(schedule)
    found = []
    for schedule in schedules:
        run = await db.get(AiRun, schedule.plan_run_id)
        if not run or run.user_id != user.id or not (run.metadata_json or {}).get("structured_plan"):
            continue
        confirmed = next((m for m in matches if m.plan_run_id == run.id), None)
        if confirmed:
            items = [s for s in scheduled_sessions(run, schedule) if s["id"] == confirmed.session_id]
        elif matches:
            continue
        else:
            day = activity_day(activity, user)
            if not day or not any(abs((datetime.fromisoformat(s["date"]).date()-day).days) <= 3 for s in scheduled_sessions(run, schedule)):
                continue
            items = [s for s in (await comparison_data(db, user, run, schedule))["items"] if s["status"] == "matched" and s.get("activity_id") == str(activity.id)]
        found.extend({"plan_id": str(run.id), "session_id": s["id"], "name": s["name"], "date": s["date"], "match_basis": "user_confirmed" if confirmed else "automatic", "session": s} for s in items)
    return found


@router.get("/activities/{activity_id}/goal-review")
async def goal_review(activity_id: uuid.UUID, plan_id: uuid.UUID | None = None, session_id: str | None = Query(default=None, max_length=80), offset_s: int = Query(default=0, ge=0, le=7200), user=Depends(safety_confirmed_user), db=Depends(get_db)):
    activity = await _owned_activity(activity_id, user, db)
    feedback = await db.scalar(select(ActivityFeedback).where(ActivityFeedback.activity_id == activity.id, ActivityFeedback.user_id == user.id))
    matches = await _matched_sessions(db, user, activity)
    options = [{k: v for k, v in m.items() if k != "session"} for m in matches]
    chosen = next((m for m in matches if m["plan_id"] == str(plan_id) and m["session_id"] == session_id), None) if plan_id else matches[0] if len(matches) == 1 else None
    if plan_id and not chosen:
        raise HTTPException(404, "MATCHED_SESSION_NOT_FOUND")
    if not chosen:
        return {"plans": options, "review": None, "reason": "choose_plan" if options else "no_matched_plan"}
    snapshot = await training_zone_snapshot(db, user.id)
    profiles = {"heart_rate_zone": _profile(snapshot, "heart_rate", activity.sport_type).get("zones", []), "power_zone": _profile(snapshot, "power", activity.sport_type).get("zones", [])}
    # Review uses the complete recorded timeline, not the chart's decimation.
    fit = await db.scalar(select(FitFile).where(FitFile.activity_id == activity.id, FitFile.user_id == user.id))
    if fit and fit.parquet_path and fit.status == "parsed":
        import pandas as pd
        from pengucoach.fit.activity_detail import serialize_series
        def load():
            frame = pd.read_parquet(fit.parquet_path)
            return serialize_series(frame, limit=max(1, len(frame)))
        series = await asyncio.to_thread(load)
    else:
        series = []
    review = await asyncio.to_thread(evaluate_goals, series, chosen["session"], profiles, offset_s=offset_s)
    return {"plans": options, "selected": {k: v for k, v in chosen.items() if k != "session"}, "review": review, "offset_s": offset_s, "zone_source": snapshot.get("source"), "zones_synced_at": snapshot.get("synced_at"), "feedback": feedback.data if feedback else None}


@router.get("/activities/{activity_id}/route-comparison")
async def route_comparison(activity_id: uuid.UUID, start: float = Query(default=0, ge=0, le=100), end: float = Query(default=100, ge=0, le=100), axis: str = Query(default="distance", pattern="^(time|distance|points)$"), user=Depends(safety_confirmed_user), db=Depends(get_db)):
    activity = await _owned_activity(activity_id, user, db)
    if end <= start:
        raise HTTPException(422, "INVALID_ROUTE_RANGE")
    data = await _series(db, user, activity)
    key = "elapsed_s" if axis == "time" else "distance_km"
    values = [number(r.get(key)) for r in data]
    if axis == "points" or len(values) < 2 or any(v is None for v in values) or any(b < a for a, b in zip(values, values[1:])) or values[-1] <= values[0]:
        values = list(range(len(data)))
    span = max(1e-9, values[-1]-values[0]) if values else 1
    reference = [row for row, v in zip(data, values) if start/100 <= (v-values[0])/span <= end/100]
    if len(gps_points(reference)) < 12:
        return {"reference": route_metrics(reference), "items": [], "reason": "missing_gps", "scanned": 0}
    segment = start > 0 or end < 100
    now = datetime.now(timezone.utc)
    # FIT recordings and SparkyFitness GPS tracks both count as recordings (alpha.84);
    # before, only activities with a parsed FIT file were ever compared.
    rows = (await db.execute(select(Activity, FitFile).outerjoin(FitFile, (FitFile.activity_id == Activity.id) & (FitFile.user_id == user.id)).where(Activity.user_id == user.id, Activity.id != activity.id, Activity.started_at >= now-timedelta(days=365), Activity.started_at <= now).order_by(Activity.started_at.desc()).limit(400))).all()
    family = sport_family(activity.sport_type)
    candidates = [(a, fit if fit is not None and fit.status == "parsed" else None) for a, fit in rows
        if sport_family(a.sport_type) == family and ((fit is not None and fit.status == "parsed") or telemetry(a.raw).get("gps"))
        and (segment or not activity.distance_m or not a.distance_m or .85 <= a.distance_m/activity.distance_m <= 1.15)][:20]
    def compare():
        items = []
        current = route_metrics(reference)
        for a, fit in candidates:
            try:
                rows = load_recording_series(a, fit, 5000)
            except (OSError, ValueError):
                continue
            match = route_match(reference, rows, segment=segment)
            if not match:
                continue
            metrics = route_metrics(rows[match["start_index"]:match["end_index"]+1])
            efficiency = None
            if all(number(x) is not None and number(x) > 0 for x in (current.get("avg_speed_kmh"), metrics.get("avg_speed_kmh"), current.get("avg_hr"), metrics.get("avg_hr"))):
                if abs(current["avg_speed_kmh"]/metrics["avg_speed_kmh"]-1) <= .05 and metrics["avg_hr"]-current["avg_hr"] >= 3:
                    efficiency = {"hr_difference": round(metrics["avg_hr"]-current["avg_hr"], 1), "pace_difference_pct": round((current["avg_speed_kmh"]/metrics["avg_speed_kmh"]-1)*100, 1)}
            items.append({"activity_id": str(a.id), "name": a.name, "date": activity_day(a, user).isoformat(), "metrics": metrics, "shape": match, "efficiency": efficiency})
        return {"reference": current, "items": items, "scanned": len(candidates), "segment": segment, "reason": None if items else "no_verified_match", "method": "ordered_gps_shape_80m_95pct", "candidate_limit": 20, "window_days": 365}
    return await asyncio.to_thread(compare)


@router.get("/coach/progress")
async def progress(days: int = Query(default=28, ge=7, le=90), user=Depends(safety_confirmed_user), db=Depends(get_db)):
    today = user_today(user)
    start = today-timedelta(days=117)
    context = {}
    health = list((await db.scalars(select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date >= start, DailyHealth.date <= today).order_by(DailyHealth.date))).all())
    context["health_30d"] = [{"date": r.date, "resting_hr_bpm": r.resting_hr, "stress_avg": r.stress_avg, "body_battery_high": r.body_battery_high, "training_readiness": r.training_readiness} for r in health]
    sleeps = list((await db.scalars(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date >= start, SleepSession.date <= today).order_by(SleepSession.date))).all())
    hrv = list((await db.scalars(select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date >= start, HrvDaily.date <= today).order_by(HrvDaily.date))).all())
    context.update(sleep_30d=_sleep_payload(sleeps), hrv_30d=_hrv_payload(hrv))
    checks = list((await db.scalars(select(CoachCheckin).where(CoachCheckin.user_id == user.id, CoachCheckin.date >= start, CoachCheckin.date <= today))).all())
    checkins = {r.date.isoformat(): r.data or {} for r in checks}
    activities = list((await db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.started_at >= day_start(start, user), Activity.started_at <= datetime.now(timezone.utc)).order_by(Activity.started_at))).all())
    acts = [{"id": str(a.id), "date": activity_day(a, user).isoformat(), "sport": sport_family(a.sport_type), "duration_seconds": a.duration_seconds, "distance_m": a.distance_m} for a in activities]
    ids = [a.id for a in activities]
    feedback_rows = list((await db.scalars(select(ActivityFeedback).where(ActivityFeedback.user_id == user.id, ActivityFeedback.activity_id.in_(ids)))).all()) if ids else []
    dates = {str(a.id): activity_day(a, user).isoformat() for a in activities}
    feedback = [{**(f.data or {}), "date": dates[str(f.activity_id)]} for f in feedback_rows]
    cutoff = (today-timedelta(days=89)).isoformat()
    history = readiness_history(context, checkins, acts, feedback, today=today, days=days)
    patterns = personal_patterns([r for r in context["sleep_30d"] if str(r["date"]) >= cutoff], {d: v for d, v in checkins.items() if d >= cutoff}, [f for f in feedback if f["date"] >= cutoff])
    return {"history": history, "patterns": patterns, "milestones": milestones(acts, today), "pattern_window_days": 90, "days": days, "method": "recomputed_daily_signals_no_future_values", "observed_days": sum(r["score"] is not None for r in history)}
