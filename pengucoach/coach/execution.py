"""Persisted, sensor-backed execution evidence and reviewed future adjustments."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pengucoach.coach.companion import scheduled_sessions
from pengucoach.coach.plan_evolution import comparison_data, sport_family
from pengucoach.coach.workout_review import evaluate_goals, number
from pengucoach.common.dates import user_today
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, FitFile, PlanSchedule, TrainingReview
from pengucoach.garmin.zones import training_zone_snapshot
from pengucoach.training_plan.structured import TrainingSession


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def zone_profile(snapshot, domain, sport):
    rows = snapshot.get(domain, {}).get('profiles', [])
    family = {'cycling': 'CYCLING', 'running': 'RUNNING', 'swimming': 'SWIMMING'}.get(sport_family(sport), 'DEFAULT')
    return next((p for p in rows if p.get('sport') == family), None) or next((p for p in rows if p.get('sport') == 'DEFAULT'), {})


def planned_payload(session):
    return TrainingSession.model_validate(session).model_dump(mode='json') | {'date': session['date']}


async def source_data(db, user, session, activity, offset=0, snapshot=None):
    snapshot = snapshot if snapshot is not None else await training_zone_snapshot(db, user.id)
    fit = await db.scalar(select(FitFile).where(FitFile.user_id == user.id, FitFile.activity_id == activity.id))
    feedback = await db.scalar(select(ActivityFeedback).where(ActivityFeedback.user_id == user.id, ActivityFeedback.activity_id == activity.id))
    power = zone_profile(snapshot, 'power', activity.sport_type)
    hr = zone_profile(snapshot, 'heart_rate', activity.sport_type)
    path = Path(fit.parquet_path) if fit and fit.status == 'parsed' and fit.parquet_path else None
    try:
        file_version = (path.stat().st_size, path.stat().st_mtime_ns) if path else None
    except OSError:
        file_version = None
    from pengucoach.sparkyfitness.telemetry import telemetry
    telemetry_version = digest(telemetry(activity.raw)) if not file_version and telemetry(activity.raw) else None
    facts = {'planned': planned_payload(session), 'activity': {'id': str(activity.id), 'name': activity.name,
        'started_at': (activity.started_at if activity.started_at.tzinfo else activity.started_at.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat() if activity.started_at else None,
        'duration_seconds': activity.duration_seconds, 'distance_m': number(activity.distance_m),
        'avg_power': number(activity.avg_power), 'avg_hr': number(activity.avg_hr), 'sport': activity.sport_type},
        'feedback': feedback.data if feedback else None, 'ftp_w': power.get('ftp_w'),
        'profiles': {'power_zone': power.get('zones', []), 'heart_rate_zone': hr.get('zones', [])},
        'zone_source': snapshot.get('source'), 'zone_date': str(snapshot.get('synced_at') or ''),
        'offset_s': offset, 'recording': {'status': fit.status if fit else 'sparkyfitness' if telemetry_version else None,
            'telemetry_version': telemetry_version, 'version': file_version, 'sha256': fit.sha256 if fit else None, 'parser_version': fit.parser_version if fit else None}}
    return facts, path, digest(facts)


def summary(facts, goals):
    planned = facts['planned']['duration_min'] * 60
    actual = facts['activity']['duration_seconds']
    work = [s for s in goals.get('steps', []) if s['type'] in {'interval', 'work'} and s['target_type'] != 'none']
    assessed = [s for s in work if s['status'] in {'on_target', 'too_low', 'too_high', 'mixed'}]
    observed = sum(s.get('observed_seconds', 0) for s in assessed)
    adherence = round(sum(s['in_target_pct']*s.get('observed_seconds', 0) for s in assessed)/observed, 1) if observed else None
    return {'planned_minutes': planned/60, 'actual_minutes': round(actual/60, 1) if actual is not None else None,
        'duration_pct': round(actual/planned*100, 1) if actual is not None else None,
        'work_intervals': len(work), 'assessed_intervals': len(assessed),
        'intervals_on_target': sum(s['status'] == 'on_target' for s in assessed),
        'work_in_target_pct': adherence, 'coverage_pct': goals.get('coverage_pct', 0),
        'status': goals['status'], 'ftp_w': facts.get('ftp_w'),
        'method': 'recorded_time_weighted; recording_start_plus_offset',
        'limitations': ['Current synchronized zones are used for zone-based targets; absolute watt targets stay fixed.',
                        'Recording gaps and missing channels are unknown, not failed intervals.',
                        'Matching identifies a likely recording; it is not proof of training quality.']}


async def review_session(db, user, run, schedule, session_id, *, offset=None, compared=None):
    items = (compared if compared is not None else await comparison_data(db, user, run, schedule))['items']
    session = next((s for s in items if s['id'] == session_id), None)
    if not session:
        raise ValueError('SESSION_NOT_FOUND')
    cached = await db.scalar(select(TrainingReview).where(TrainingReview.user_id == user.id,
        TrainingReview.plan_run_id == run.id, TrainingReview.session_id == session_id))
    if not session.get('activity_id'):
        if cached:
            await db.delete(cached)
            await db.commit()
        return {'session': session, 'review': None, 'fingerprint': None, 'revision': schedule.revision}
    activity = await db.get(Activity, uuid.UUID(session['activity_id']))
    if not activity or activity.user_id != user.id:
        raise ValueError('ACTIVITY_NOT_FOUND')
    offset = int(offset if offset is not None else (cached.data.get('facts', {}).get('offset_s', 0)
                 if cached and cached.activity_id == activity.id else 0))
    facts, path, fingerprint = await source_data(db, user, session, activity, offset)
    if cached and cached.fingerprint == fingerprint:
        data = cached.data
    else:
        def calculate():
            rows = []
            if path and path.is_file():
                import pandas as pd
                from pengucoach.fit.activity_detail import serialize_series
                frame = pd.read_parquet(path)
                rows = serialize_series(frame, limit=max(1, len(frame)))
            else:
                from pengucoach.fit.service import load_recording_series
                rows = load_recording_series(activity, None, 100_000)
            goals = evaluate_goals(rows, facts['planned'], facts['profiles'], offset_s=offset)
            return {'facts': facts, 'goals': goals, 'summary': summary(facts, goals)}
        try:
            data = await asyncio.to_thread(calculate)
        except (OSError, ValueError):
            goals = evaluate_goals([], facts['planned'], facts['profiles'], offset_s=offset)
            data = {'facts': facts, 'goals': goals, 'summary': summary(facts, goals)}
        if cached is None:
            cached = TrainingReview(user_id=user.id, plan_run_id=run.id, session_id=session_id, activity_id=activity.id)
            db.add(cached)
        cached.activity_id, cached.fingerprint, cached.data = activity.id, fingerprint, data
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return await review_session(db, user, run, schedule, session_id, offset=offset)
    analysis = await db.get(AiRun, cached.ai_run_id) if cached and cached.ai_run_id else None
    if analysis and (analysis.user_id != user.id or (analysis.metadata_json or {}).get('review_fingerprint') != fingerprint):
        analysis = None
    return {'session': session, 'review': data, 'fingerprint': fingerprint, 'revision': schedule.revision,
            'analysis_id': str(analysis.id) if analysis else None}


async def execution_context(db, user, days=28, include_zones=True):
    """Revalidate cached evidence before exposing it to future AI requests."""
    since = datetime.now(timezone.utc)-timedelta(days=min(90, days))
    rows = (await db.scalars(select(TrainingReview).join(Activity, Activity.id == TrainingReview.activity_id).where(
        TrainingReview.user_id == user.id, Activity.user_id == user.id, Activity.started_at >= since,
        Activity.started_at <= datetime.now(timezone.utc)).order_by(Activity.started_at.desc()).limit(30))).all()
    result, plans = [], {}
    snapshot = await training_zone_snapshot(db, user.id) if rows else {}
    for row in rows:
        if row.plan_run_id not in plans:
            run, schedule = await db.get(AiRun, row.plan_run_id), await db.get(PlanSchedule, row.plan_run_id)
            plans[row.plan_run_id] = (await comparison_data(db, user, run, schedule))['items'] if run and schedule and run.user_id == user.id and schedule.user_id == user.id else []
        session = next((s for s in plans[row.plan_run_id] if s['id'] == row.session_id and s.get('activity_id') == str(row.activity_id)), None)
        if not session:
            continue
        activity = await db.get(Activity, row.activity_id)
        _, _, current = await source_data(db, user, session, activity, row.data.get('facts', {}).get('offset_s', 0), snapshot)
        if current != row.fingerprint:
            continue
        result.append({'plan_id': str(row.plan_run_id), 'session_id': row.session_id,
            'activity_id': str(row.activity_id), 'date': row.data['facts']['activity']['started_at'],
            'sport': session['sport'], 'summary': row.data['summary'], 'feedback': row.data['facts']['feedback'],
            'planned_steps': session.get('steps', [])[:15], 'source': 'recorded_plan_execution_review'})
    if not include_zones:
        for item in result:
            item['summary'] = {k: v for k, v in item['summary'].items() if k != 'ftp_w'}
    return {'items': result[:20], 'rule': 'Use observed evidence and feedback. Unknown is not failure. Do not change FTP from one session. Propose changes for review.'}


def comparable(first, second):
    from pengucoach.coach.workout_review import flatten_steps
    a, b = flatten_steps(first.get('steps')), flatten_steps(second.get('steps'))
    if not a or len(a) != len(b):
        return False
    for before, after in zip(a, b):
        ta, tb = before.get('target') or {}, after.get('target') or {}
        if before['type'] != after['type'] or ta.get('type', 'none') != tb.get('type', 'none') or ta.get('zone') != tb.get('zone'):
            return False
        if before['type'] in {'work', 'interval'}:
            if before.get('duration_seconds') and (not after.get('duration_seconds') or not .75 <= after['duration_seconds']/before['duration_seconds'] <= 1.25):
                return False
            if ta.get('type') == 'power_watts' and (not tb.get('watts') or not .85 <= tb['watts']/ta['watts'] <= 1.15):
                return False
    return True


def adapt_session(before, direction):
    after = copy.deepcopy(before)
    changed = []
    def change(steps):
        for step in steps:
            if step['type'] == 'repeat':
                change(step.get('steps', []))
            elif step['type'] in {'interval', 'work'} and step.get('duration_seconds'):
                if direction == 'reduce':
                    old = step['duration_seconds']
                    step['duration_seconds'] = max(15, round(old*.75)) if old >= 20 else old
                    changed.append(step['duration_seconds'] != old)
                target = step.get('target') or {}
                if target.get('type') == 'power_watts':
                    old = target['watts']
                    target['watts'] = round(old*(.98 if direction == 'reduce' else 1.02))
                    changed.append(target['watts'] != old)
                elif direction == 'increase':
                    old = step['duration_seconds']
                    step['duration_seconds'] = max(old+1, round(old*1.05))
                    changed.append(True)
    change(after.get('steps', []))
    if not any(changed):
        raise ValueError('NO_ADAPTABLE_TIMED_WORK')
    from pengucoach.coach.plan_evolution import seconds
    durations = [seconds(s) for s in after['steps']]
    if any(x is None for x in durations):
        raise ValueError('DISTANCE_STEP_NEEDS_TIMED_DRAFT')
    after['duration_min'] = max(5, round(sum(durations)/60))
    validated = TrainingSession.model_validate(after).model_dump(mode='json')
    validated['date'] = before['date']
    return validated


async def adaptive_proposal(db, user, run, schedule, source_id):
    comparison = await comparison_data(db, user, run, schedule)
    data = await review_session(db, user, run, schedule, source_id, compared=comparison)
    from pengucoach.db.models import CoachDecisionLog
    source_marker = 'source-session:'+source_id
    previous_decisions = (await db.scalars(select(CoachDecisionLog).where(CoachDecisionLog.user_id == user.id, CoachDecisionLog.plan_run_id == run.id, CoachDecisionLog.action == 'execution_adaptation'))).all()
    if any(any(r.get('value') == source_marker for r in (d.reasons or [])) for d in previous_decisions):
        return {'items': [], 'reason': 'REVIEW_ALREADY_APPLIED'}
    review = data.get('review')
    if not review:
        return {'items': [], 'reason': 'MATCH_ACTIVITY_FIRST'}
    facts, value = review['facts'], review['summary']
    feedback = facts.get('feedback') or {}
    if datetime.fromisoformat(facts['activity']['started_at']) < datetime.now(timezone.utc)-timedelta(days=28):
        return {'items': [], 'reason': 'RECENT_EXECUTION_REQUIRED'}
    direction = None
    if value['coverage_pct'] >= 70 and value['assessed_intervals']:
        if value['work_in_target_pct'] is not None and value['work_in_target_pct'] < 50 and feedback.get('feeling') == 'hard':
            direction = 'reduce'
        elif value['work_in_target_pct'] is not None and value['work_in_target_pct'] >= 90 and 90 <= (value['duration_pct'] or 0) <= 115 and feedback.get('feeling') == 'easy' and (feedback.get('exertion') is None or feedback['exertion'] <= 5) and not str(feedback.get('discomfort') or '').strip():
            evidence = await execution_context(db, user, 28)
            successful = [r for r in evidence['items'] if r['sport'] == facts['planned']['sport'] and comparable(facts['planned'], {'steps': r.get('planned_steps', [])}) and r['summary'].get('coverage_pct', 0) >= 70 and (r['summary']['work_in_target_pct'] or 0) >= 90 and 90 <= (r['summary']['duration_pct'] or 0) <= 115 and (r.get('feedback') or {}).get('feeling') == 'easy' and not (r.get('feedback') or {}).get('discomfort') and ((r.get('feedback') or {}).get('exertion') is None or r['feedback']['exertion'] <= 5)]
            if len({r['activity_id'] for r in successful}) >= 2:
                direction = 'increase'
    if str(feedback.get('discomfort') or '').strip():
        return {'items': [], 'reason': 'DISCOMFORT_REVIEW_WITH_COACH'}
    if not direction:
        return {'items': [], 'reason': 'MORE_RELIABLE_EVIDENCE_OR_FEEDBACK_NEEDED'}
    # Recovery only applies to today; do not forecast a future readiness score.
    from pengucoach.coach.today import readiness_snapshot
    readiness = await readiness_snapshot(db, user)
    if set(readiness.get('reasons') or []) & {'discomfort', 'feedback_discomfort'}:
        return {'items': [], 'reason': 'DISCOMFORT_REVIEW_WITH_COACH'}
    if direction == 'increase' and (readiness.get('readiness', readiness).get('status') != 'green' or set(readiness.get('reasons') or []) & {'low_energy', 'soreness', 'hard_feedback'}):
        return {'items': [], 'reason': 'RECOVERY_NOT_READY_FOR_INCREASE'}
    from pengucoach.db.models import GarminWorkoutExport
    exports = (await db.scalars(select(GarminWorkoutExport).where(GarminWorkoutExport.user_id == user.id, GarminWorkoutExport.plan_run_id == run.id))).all()
    locked = {x.session_id for x in exports if x.status == 'exported' or x.workout_id or x.scheduled_workout_id}
    today = user_today(user)
    # Only adapt a future session with the same work-step structure/target kind.
    candidate = next((s for s in sorted(comparison['items'], key=lambda s: (s['date'], s['id']))
        if today.isoformat() < s['date'] <= (today+timedelta(days=28)).isoformat()
        and s['id'] not in locked and s['status'] in {'planned', 'pending'}
        and s['sport'] == facts['planned']['sport'] and comparable(facts['planned'], s)), None)
    if candidate is None:
        return {'items': [], 'reason': 'NO_UNLOCKED_COMPARABLE_FUTURE_SESSION'}
    before = planned_payload(candidate)
    try:
        after = adapt_session(before, direction)
    except ValueError as exc:
        return {'items': [], 'reason': str(exc)}
    result = {'items': [{'before': before, 'after': after, 'changed': before != after,
        'reasons': ['recorded_execution_and_confirmed_feedback', direction, source_marker, data['fingerprint']]}], 'direction': direction,
        'source_session_id': source_id, 'source_fingerprint': data['fingerprint'], 'revision': schedule.revision,
        'rule': 'Conservative reviewed suggestion; FTP stays unchanged; warmup, recovery and cooldown stay unchanged.'}
    result['review_token'] = digest(result)
    return result


async def remove_plan_analyses(db, user_id, plan_id):
    rows = (await db.scalars(select(AiRun).where(AiRun.user_id == user_id,
        AiRun.task_type == 'activity_analysis',
        AiRun.metadata_json['planned_session']['plan_id'].as_string() == str(plan_id)))).all()
    for row in rows:
        await db.delete(row)
