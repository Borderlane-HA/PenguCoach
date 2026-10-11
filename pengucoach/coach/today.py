"""Small local Today queries. Readiness never reads FIT or calls providers/AI."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from pengucoach.common.dates import day_start, user_today, user_zone
from pengucoach.db.models import Activity, ActivityFeedback, CoachCheckin
from pengucoach.coach.readiness import compute_readiness, soreness_level

LEGACY_TODAY_ORDER = ['preparation', 'weather', 'reflection', 'progress', 'load', 'metrics', 'trend', 'activities']
TODAY_CARDS = ['progress', 'preparation', 'weather', 'reflection', 'load', 'metrics', 'trend', 'activities']
TODAY_METRICS = ['steps', 'sleep', 'resting_hr', 'hrv', 'stress', 'hydration', 'body_battery_high', 'weight', 'body_fat', 'training_readiness', 'vo2max']


def today_preferences(pref):
    config = pref.dashboard_config if pref and isinstance(pref.dashboard_config, dict) else {}
    raw = config.get('today', {})
    raw = raw if isinstance(raw, dict) else {}
    def keys(name, allowed, default=()):
        values = raw.get(name, default)
        values = values if isinstance(values, list) else default
        return list(dict.fromkeys(k for k in values if isinstance(k, str) and k in allowed))
    order = keys('order', TODAY_CARDS)
    order += [k for k in TODAY_CARDS if k not in order]
    if order == LEGACY_TODAY_ORDER:
        order = list(TODAY_CARDS)
    pinned = keys('pinned_metrics', TODAY_METRICS, ['steps', 'sleep', 'resting_hr', 'hrv', 'weight', 'stress'])[:len(TODAY_METRICS)]
    start, end = raw.get('preferred_start_hour', 7), raw.get('preferred_end_hour', 21)
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= 24:
        start, end = 7, 21
    return {'order': order, 'hidden': keys('hidden', TODAY_CARDS),
            'pinned_metrics': pinned or ['steps', 'sleep', 'resting_hr', 'hrv', 'weight', 'stress'],
            'preferred_start_hour': start, 'preferred_end_hour': end}


def day_phase(today, hour, upcoming, activities, comparisons, checkin):
    pending = [s for s in upcoming if s['date'] == today]
    recorded = {a['id'] for a in activities}
    completed = [s for s in comparisons if s.get('status') == 'matched' and s.get('activity_id') in recorded]
    if not pending and (completed or activities):
        return 'reflection'
    if pending and (hour >= 12 or checkin.get('energy') is not None or checkin.get('soreness') is not None or checkin.get('soreness_regions')):
        return 'preparation'
    return 'reflection' if hour >= 18 and not pending else 'morning'


async def readiness_snapshot(db, user):
    # Keep the same recovery rules/data as briefing, using bounded local queries.
    from pengucoach.coach.context import _recovery_window, _health_payload, _sleep_payload, _hrv_payload
    from pengucoach.coach.companion import activity_day
    today, now = user_today(user), datetime.now(timezone.utc)
    health, sleep, hrv = await _recovery_window(db, user.id, today-timedelta(days=27), today)
    context = {'health_30d': _health_payload(health), 'sleep_30d': _sleep_payload(sleep), 'hrv_30d': _hrv_payload(hrv)}
    row = await db.scalar(select(CoachCheckin).where(CoachCheckin.user_id == user.id, CoachCheckin.date == today))
    checkin = dict(row.data or {}) if row else {}
    activities = (await db.execute(select(Activity.id, Activity.name, Activity.sport_type, Activity.started_at, Activity.duration_seconds, Activity.distance_m, Activity.avg_hr).where(
        Activity.user_id == user.id, Activity.started_at >= day_start(today-timedelta(days=13), user), Activity.started_at <= now
    ).order_by(Activity.started_at))).all()
    current = [a for a in activities if activity_day(a, user) >= today-timedelta(days=6)]
    previous = [a for a in activities if activity_day(a, user) < today-timedelta(days=6)]
    feedback = (await db.execute(select(ActivityFeedback.data, Activity.name, Activity.started_at).join(Activity, Activity.id == ActivityFeedback.activity_id).where(
        ActivityFeedback.user_id == user.id, Activity.user_id == user.id,
        Activity.started_at >= day_start(today-timedelta(days=2), user), Activity.started_at <= now
    ))).all()
    recent = [{'activity': f.name, 'date': activity_day(f, user).isoformat(), **{k:v for k,v in (f.data or {}).items() if k in {'feeling', 'exertion', 'discomfort', 'comment'}}} for f in feedback]
    days = {activity_day(a, user) for a in current}
    consecutive = 0
    for i in range(1, 8):
        if today-timedelta(days=i) not in days:
            break
        consecutive += 1
    reasons = []
    if any(f.get('feeling') == 'hard' or (f.get('exertion') or 0) >= 9 for f in recent): reasons.append('hard_feedback')
    if any(str(f.get('discomfort') or '').strip() for f in recent): reasons.append('feedback_discomfort')
    if checkin.get('energy') is not None and checkin['energy'] <= 2: reasons.append('low_energy')
    if soreness_level(checkin) is not None and soreness_level(checkin) >= 4: reasons.append('soreness')
    if checkin.get('discomfort'): reasons.append('discomfort')
    if checkin.get('minutes') == 0: reasons.append('no_time')
    if consecutive >= 3: reasons.append('three_active_days')
    today_sleep = next((s for s in context['sleep_30d'] if s['date'] == today), None)
    if today_sleep and today_sleep['duration_s'] is not None and today_sleep['duration_s'] < 21600: reasons.append('short_sleep')
    readiness = compute_readiness(context, checkin, recent, consecutive_active_days=consecutive, today=today)
    evidence = []
    for key, label, metric in [('sleep_30d','sleep','duration_s'), ('hrv_30d','hrv','overnight_ms'), ('health_30d','resting_hr','resting_hr_bpm'), ('health_30d','hydration','hydration_ml')]:
        available = [r for r in context[key] if r.get(metric) is not None]
        if available:
            r = available[-1]
            evidence.append({'metric':label,'value':r[metric],'date':str(r['date']),'source':(r.get('sources') or {}).get(metric,r.get('source','unknown')),'age_days':(today-r['date']).days})
    def stats(rows):
        return {'sessions':len(rows),'minutes':round(sum(a.duration_seconds or 0 for a in rows)/60),
                'distance_km':round(sum(a.distance_m or 0 for a in rows)/1000,1),'active_days':len({activity_day(a,user) for a in rows})}
    return {'date':today.isoformat(),'readiness':readiness,'checkin':checkin,'evidence':evidence,'reasons':reasons,
            'mode':'check_discomfort' if 'discomfort' in reasons else 'easy' if reasons or readiness['status'] in {'red','yellow'} else 'check_in',
            'current_week':stats(current),'previous_week':stats(previous),'activity_count':len(current),
            'generated_at':now.isoformat(), 'timezone':str(user_zone(user)),
            'today_activities':[{'id':str(a.id),'name':a.name or a.sport_type,'sport':a.sport_type,
                'started_at':(a.started_at.replace(tzinfo=timezone.utc) if not a.started_at.tzinfo else a.started_at).isoformat(),
                'duration_seconds':a.duration_seconds,'distance_m':a.distance_m,'avg_hr':a.avg_hr}
                for a in reversed(activities) if activity_day(a,user)==today
                and a.duration_seconds is not None and a.duration_seconds > 0
                and (a.started_at.replace(tzinfo=timezone.utc) if not a.started_at.tzinfo else a.started_at)+timedelta(seconds=max(0,a.duration_seconds or 0)) <= now]}
