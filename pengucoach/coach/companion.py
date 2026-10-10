"""Personal coaching context and transparent, deterministic calendar comparisons."""
from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from pengucoach.common.dates import day_start, user_today, user_zone
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachCheckin, CoachMemory, CoachProfile, Message, PlanSchedule
from pengucoach.training_plan.structured import TrainingPlanDocument
from pengucoach.coach.readiness import compute_readiness
from pengucoach.coach.training_intelligence import training_load_summary
from pengucoach.health.development import development_summary_for_coach


def activity_day(activity, user):
    at = activity.started_at
    return (at.replace(tzinfo=timezone.utc) if at and not at.tzinfo else at).astimezone(user_zone(user)).date() if at else None


def sport_family(value):
    value = (value or "").lower()
    for family, words in {"cycling": ("cycl", "bik", "rad"), "running": ("run", "lauf"), "swimming": ("swim", "schwimm"), "strength": ("strength", "weight", "kraft"), "hiking": ("hik", "wander"), "walking": ("walk", "gehen"), "mobility": ("mobility", "stretch")}.items():
        if any(word in value for word in words):
            return family
    return value


def scheduled_sessions(run, schedule):
    plan = TrainingPlanDocument.model_validate((run.metadata_json or {}).get("structured_plan"))
    return [{**copy.deepcopy((schedule.overrides or {}).get(s.id) or s.model_dump()), "date": (schedule.start_date + timedelta(weeks=((schedule.overrides or {}).get(s.id) or s.model_dump())["week"] - 1, days=((schedule.overrides or {}).get(s.id) or s.model_dump())["day"] - 1)).isoformat()} for s in plan.sessions]


def compare_sessions(sessions, activities, user):
    """Never silently pair ambiguous workouts or reuse an activity for two sessions."""
    candidates = {}
    for session in sessions:
        candidates[session["id"]] = [a for a in activities if activity_day(a, user) == date.fromisoformat(session["date"]) and sport_family(a.sport_type) == session["sport"]]
    uses = {}
    for values in candidates.values():
        for a in values:
            uses[a.id] = uses.get(a.id, 0) + 1
    result = []
    for s in sessions:
        available = candidates[s["id"]]
        a = available[0] if len(available) == 1 and uses[available[0].id] == 1 else None
        actual = round(a.duration_seconds / 60, 1) if a and a.duration_seconds is not None else None
        result.append({**s, "status": "matched" if a else "ambiguous" if available else "unmatched" if date.fromisoformat(s["date"]) < user_today(user) else "planned", "activity_id": str(a.id) if a else None, "actual_minutes": actual, "difference_minutes": round(actual - s["duration_min"], 1) if actual is not None else None, "candidate_ids": [str(x.id) for x in available], "match_basis": "same_local_day_and_sport" if a else None})
    return result


async def conversation_excerpt(db, conversation):
    """Extractive history: no invented facts or additional model call/cost.

    Keep original quotations from earlier user turns, not inferred preferences.
    Permanent facts are managed separately by the user in CoachMemory.
    """
    rows = list((await db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id))).all())
    earlier = [x for x in rows[:-12] if x.role == "user"]
    if not earlier:
        conversation.summary = ""
    else:
        chosen = earlier[:3] + earlier[max(3, len(earlier) - 9):]
        conversation.summary = "Earlier user messages (abbreviated quotations; not confirmed permanent facts):\n" + "\n".join(f"• {x.content[:220]}" for x in chosen)
    return rows


async def personal_context(db, user, *, training=True, recovery=True, days=7):
    profile = await db.get(CoachProfile, user.id)
    data = dict(profile.data or {}) if profile else {}
    if data.get("enabled", True) is False:
        return {}
    memories = list((await db.scalars(select(CoachMemory).where(CoachMemory.user_id == user.id).order_by(CoachMemory.updated_at.desc()).limit(30))).all())
    result = {"source": "user", "profile": data, "memories": [{"text": m.content, "updated_at": m.updated_at.isoformat()} for m in memories]}
    if recovery:
        checkin = await db.scalar(select(CoachCheckin).where(CoachCheckin.user_id == user.id, CoachCheckin.date == user_today(user)))
        result["today_checkin"] = {"date": checkin.date.isoformat(), **checkin.data} if checkin else None
    if training:
        feedback = (await db.execute(select(ActivityFeedback, Activity).join(Activity, Activity.id == ActivityFeedback.activity_id).where(ActivityFeedback.user_id == user.id, Activity.started_at >= day_start(user_today(user) - timedelta(days=max(0, days - 1)), user)).order_by(Activity.started_at.desc()).limit(8))).all()
        from pengucoach.coach.session_features import active_experiences, matching_experiences
        confirmed_experiences = await active_experiences(db, user)
        result["training_experiences"] = confirmed_experiences
        result["recent_feedback"] = [{"activity": a.name, "date": activity_day(a, user).isoformat(), **{k:v for k,v in (f.data or {}).items() if k in {"feeling", "exertion", "discomfort", "comment"}}} for f, a in feedback]
        schedules = list((await db.scalars(select(PlanSchedule).where(PlanSchedule.user_id == user.id).order_by(PlanSchedule.updated_at.desc()).limit(5))).all())
        upcoming = []
        comparisons = []
        today_comparisons = []
        for schedule in schedules:
            run = await db.get(AiRun, schedule.plan_run_id)
            if run:
                all_sessions = scheduled_sessions(run, schedule)
                recent_sessions = [s for s in all_sessions if (user_today(user) - timedelta(days=max(0, days - 1))).isoformat() <= s["date"] <= user_today(user).isoformat()]
                from pengucoach.coach.plan_evolution import comparison_data
                compared = await comparison_data(db, user, run, schedule)
                today_comparisons.extend({**{k:v for k,v in s.items() if k not in {"candidates", "candidate_ids", "recorded_laps"}},"plan_id":str(run.id)} for s in compared["items"] if s["date"] == user_today(user).isoformat())
                recent_ids = {s["id"] for s in recent_sessions}
                completed_ids = {s["id"] for s in compared["items"] if s["status"] == "matched"}
                comparisons.extend({k:v for k,v in s.items() if k not in {"candidates", "candidate_ids", "recorded_laps"}} for s in compared["items"] if s["id"] in recent_ids)
                upcoming.extend([{**s, "plan_id": str(run.id), "schedule_revision": schedule.revision} for s in all_sessions if s["id"] not in completed_ids and user_today(user).isoformat() <= s["date"] <= (user_today(user) + timedelta(days=7)).isoformat()])
        result["recent_plan_comparison"] = comparisons[-12:]
        result["today_plan_comparison"] = today_comparisons[:30]
        result["upcoming_sessions"] = [{**s, "experience_hints": matching_experiences(confirmed_experiences, s)} for s in sorted(upcoming, key=lambda s: s["date"])[:10]]
    return result


def _readiness_context(context):
    if "health_30d" in context or "sleep_30d" in context or "hrv_30d" in context:
        return context
    lookback = context.get("lookback") or {}
    return {
        "health_30d": lookback.get("daily_health", []),
        "sleep_30d": lookback.get("sleep", []),
        "hrv_30d": lookback.get("hrv", []),
    }


async def add_personal_context(db, user, context, payload, conversation=None):
    if payload.get("use_personal_context", True):
        selection = payload.get("context_data") or {}
        enabled = payload.get("context_mode") != "none"
        personal = await personal_context(db, user, training=enabled and selection.get("training", True), recovery=enabled and selection.get("recovery", True), days=int(context.get("period_days") or (context.get("lookback") or {}).get("days") or 7))
        if enabled and selection.get("recovery", True):
            personal["readiness"] = compute_readiness(_readiness_context(context), personal.get("today_checkin") or {}, personal.get("recent_feedback") or [], today=user_today(user))
        if enabled and selection.get("training", True):
            personal["training_load"] = await training_load_summary(db, user)
        if enabled and (selection.get("training", True) or selection.get("recovery", True)):
            # Compact 90-day development evidence lets the coach answer questions
            # such as “am I getting fitter?” without sending chart-sized arrays.
            personal["training_development"] = await development_summary_for_coach(db, user, days=90)
        context["personal_coaching"] = personal
    if conversation and conversation.summary:
        context["conversation_summary"] = conversation.summary
    return context


async def briefing(db, user):
    from pengucoach.coach.today import readiness_snapshot, day_phase
    from pengucoach.db.models import FitFile
    snapshot = await readiness_snapshot(db, user)
    personal = await personal_context(db, user)
    today = snapshot['date']
    upcoming = personal.get('upcoming_sessions', [])
    mode = snapshot['mode']
    if mode == 'check_in' and upcoming:
        mode = 'review_plan'
    comparisons = personal.get('today_plan_comparison', [])
    ids = [a['id'] for a in snapshot['today_activities']]
    feedback = (await db.scalars(select(ActivityFeedback).where(ActivityFeedback.user_id == user.id, ActivityFeedback.activity_id.in_([uuid.UUID(identifier) for identifier in ids])))).all() if ids else []
    by_id = {str(f.activity_id): {k:v for k,v in (f.data or {}).items() if k in {'feeling','exertion','discomfort','comment'}} for f in feedback}
    activities = [{**a,'feedback':by_id.get(a['id'],{})} for a in snapshot['today_activities']]
    routes = (await db.execute(select(Activity.id,Activity.name,Activity.sport_type,Activity.started_at,FitFile.data_quality).join(FitFile,FitFile.activity_id==Activity.id).where(
        Activity.user_id==user.id,FitFile.user_id==user.id,FitFile.status=='parsed',Activity.started_at<=datetime.now(timezone.utc)
    ).order_by(Activity.started_at.desc()).limit(50))).all()
    route_options = [{'id':str(a.id),'name':a.name or a.sport_type,'sport':sport_family(a.sport_type),'date':activity_day(a,user).isoformat()} for a in routes
                     if isinstance(a.data_quality, dict) and isinstance(a.data_quality.get('coverage'), dict) and isinstance(a.data_quality['coverage'].get('gps'), (int,float)) and a.data_quality['coverage']['gps']>0][:20]
    return {**snapshot,'mode':mode,'profile':personal.get('profile',{}),'upcoming':upcoming,
            'today_activities':activities,'today_comparison':comparisons,'route_options':route_options,
            'day_phase':day_phase(today,datetime.now(user_zone(user)).hour,upcoming,activities,comparisons,snapshot['checkin']),
            'method':'PenguCoach deterministic readiness v1; missing records do not prove inactivity or recovery.'}
