"""Local recorded-data efforts, route briefing and confirmed experiences."""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta

from sqlalchemy import select

from pengucoach.coach.workout_review import number, flatten_steps, route_metrics
from pengucoach.coach.training_intelligence import _is_hard_session, sport_family
from pengucoach.db.models import Activity, ActivityFeedback, CoachProfile


def session_kind(session):
    if sport_family(session.get('sport')) == 'strength':
        return 'strength'
    return 'interval' if _is_hard_session(session) else 'endurance'


async def experiences(db, user, *, enabled_only=False):
    rows = (await db.execute(select(ActivityFeedback, Activity).join(Activity, Activity.id == ActivityFeedback.activity_id).where(ActivityFeedback.user_id == user.id, Activity.user_id == user.id).order_by(ActivityFeedback.updated_at.desc()))).all()
    result = []
    for feedback, activity in rows:
        entry = (feedback.data or {}).get('experience')
        if not isinstance(entry, dict) or not str(entry.get('text') or '').strip():
            continue
        if enabled_only and not entry.get('enabled', True):
            continue
        result.append({**entry, 'activity_id': str(activity.id), 'activity_name': activity.name or activity.sport_type, 'sport': sport_family(activity.sport_type), 'updated_at': feedback.updated_at.isoformat()})
    return result


def matching_experiences(entries, session):
    return [e for e in entries if e.get('enabled', True) and e['sport'] == sport_family(session.get('sport')) and e.get('kind', 'all') in {'all', session_kind(session)}][:3]


async def active_experiences(db, user):
    profile = await db.get(CoachProfile, user.id)
    if profile and (profile.data or {}).get('enabled') is False:
        return []
    return (await experiences(db, user, enabled_only=True))[:30]


def best_efforts(series, windows=(60, 300, 1200)):
    """Exact sample-held integrals; every second of a window must be recorded.

    Maxima occur when a window edge crosses a sample boundary. There is no
    artificial resampling, gap filling or omission of coasting/pauses.
    """
    if len(series) < 2:
        return []
    times = [number(r.get('elapsed_s')) for r in series]
    recorded_times = [t for t in times if t is not None]
    origin = recorded_times[0] if recorded_times else None
    if origin is None or any(b <= a for a,b in zip(recorded_times, recorded_times[1:])):
        return []
    result = []
    for key, metric in [('power', 'power'), ('speed_kmh', 'speed')]:
        runs, ts, values = [], [], []
        for i, (left, right) in enumerate(zip(series, series[1:])):
            a,b = times[i],times[i+1]
            value = number(left.get(key))
            valid = a is not None and b is not None and left.get('track_segment') == right.get('track_segment') and 0 < b-a <= 30 and value is not None and value >= 0
            if not valid:
                if values:
                    runs.append((ts,values))
                ts,values = [],[]
                continue
            if not ts:
                ts=[a]
            ts.append(b);values.append(value)
        if values:
            runs.append((ts,values))
        for window in windows:
            best = None
            for timestamps, vals in runs:
                if timestamps[-1]-timestamps[0] < window:
                    continue
                prefix=[0.0]
                for a,b,value in zip(timestamps,timestamps[1:],vals):
                    prefix.append(prefix[-1]+(b-a)*value)
                def integral(at):
                    index=min(len(vals)-1, max(0,bisect_right(timestamps,at)-1))
                    return prefix[index]+(at-timestamps[index])*vals[index]
                starts=sorted({t for t in timestamps if timestamps[0] <= t <= timestamps[-1]-window} | {t-window for t in timestamps if timestamps[0] <= t-window <= timestamps[-1]-window})
                for start in starts:
                    avg=(integral(start+window)-integral(start))/window
                    if best is None or avg > best['value']:
                        best={'metric':metric,'seconds':window,'value':avg,'start_s':start-origin,'end_s':start+window-origin}
            if best and (metric == 'power' or best['value'] > 0):
                result.append({**best,'value':round(best['value'],2)})
    return result


def route_briefing(series):
    """100m elevation bins. No bridging missing values or recording breaks."""
    hills=[]
    anchor=None;active=None
    def finish():
        nonlocal active
        if active and active['length_m'] >= 299.9 and active['gain_m'] >= 15:
            segment=series[active['start_index']:active['end_index']+1]
            active['metrics']=route_metrics(segment)
            active['grade_pct']=round(active['gain_m']/active['length_m']*100,1)
            active['length_m']=round(active['length_m']);active['gain_m']=round(active['gain_m'])
            hills.append(active)
        active=None
    for index,row in enumerate(series):
        dist,alt=number(row.get('distance_km')),number(row.get('altitude_m'))
        lat,lon=number(row.get('position_lat')),number(row.get('position_long'))
        if dist is None or alt is None or lat is None or lon is None or abs(lat)>90 or abs(lon)>180:
            finish();anchor=None;continue
        if anchor:
            previous=series[index-1]
            dt=number(row.get('elapsed_s'));pt=number(previous.get('elapsed_s'))
            pd=number(previous.get('distance_km'))
            if row.get('track_segment') != previous.get('track_segment') or pd is None or dist < pd or (dt is not None and pt is not None and (dt <= pt or dt-pt > 120)) or (dist-pd)*1000 > 250:
                finish();anchor=None
        if anchor is None:
            anchor=(index,dist,alt);continue
        length=(dist-anchor[1])*1000
        if length < 99.9:
            continue
        gain=alt-anchor[2]
        if 3 <= gain/length*100 <= 35:
            if active is None:
                first=series[anchor[0]]
                active={'start_index':anchor[0],'end_index':index,'distance_km':anchor[1],'end_distance_km':dist,'start_s':number(first.get('elapsed_s')),'end_s':number(row.get('elapsed_s')),'lat':number(first.get('position_lat')),'lon':number(first.get('position_long')),'length_m':0.0,'gain_m':0.0}
            active.update(end_index=index,end_distance_km=dist,end_s=number(row.get('elapsed_s')))
            active['length_m']+=length;active['gain_m']+=gain
        else:
            finish()
        anchor=(index,dist,alt)
    finish()
    hills=sorted(hills,key=lambda h:h['gain_m'],reverse=True)[:8]
    hills.sort(key=lambda h:h['start_index'])
    return {'hills':hills,'metrics':route_metrics(series),'has_gps':any(number(r.get('position_lat')) is not None and number(r.get('position_long')) is not None for r in series),'has_elevation':any(number(r.get('altitude_m')) is not None for r in series),'method':'100m_bins_3pct_300m_15m_gain'}


def route_plan_overlay(series, session):
    steps=flatten_steps(session.get('steps') or [])
    times=[number(r.get('elapsed_s')) for r in series]
    if not times or any(t is None for t in times) or any(b < a for a,b in zip(times,times[1:])) or times[-1]<=times[0]:
        return {'items':[],'reason':'missing_time'}
    if not steps:
        return {'items':[],'reason':'missing_steps'}
    if any(number(s.get('duration_seconds')) is None for s in steps):
        return {'items':[],'reason':'distance_steps'}
    elapsed=0;items=[]
    for step in steps:
        duration=number(step.get('duration_seconds'));start=times[0]+elapsed;end=start+duration
        if start > times[-1]:
            break
        index=max(0,bisect_right(times,start)-1)
        row=series[index]
        items.append({'type':step.get('type'),'description':step.get('description'),'target':step.get('target'),'start_s':start,'end_s':min(end,times[-1]),'start_index':index,'distance_km':number(row.get('distance_km')),'lat':number(row.get('position_lat')),'lon':number(row.get('position_long')),'truncated':end>times[-1]})
        elapsed+=duration
    return {'items':items,'reason':None,'recording_shorter':sum(number(s.get('duration_seconds')) for s in steps)>times[-1]-times[0],'assumption':'same_elapsed_time_as_recording'}


def alternative_days(sessions, profile, start, weeks, *, today, other_sessions=(), locked=()):
    """Free allowed dates with no adjacent hard days, without plan mutation."""
    allowed=set(profile.get('training_days') or range(1,8))
    result={}
    for session in sessions:
        if session['id'] in locked or session['date'] < today.isoformat():
            continue
        others=[s for s in sessions if s['id'] != session['id']]+list(other_sessions)
        occupied={s['date'] for s in others}
        hard_dates=[date.fromisoformat(s['date']) for s in others if _is_hard_session(s)]
        candidates=[]
        for i in range(weeks*7):
            day=start+timedelta(days=i)
            if day < today or day.isoformat()==session['date'] or day.isoformat() in occupied or day.isoweekday() not in allowed:
                continue
            if _is_hard_session(session) and any(abs((day-other).days)<=1 for other in hard_dates):
                continue
            candidates.append(day)
        old=date.fromisoformat(session['date'])
        result[session['id']]=[{'date':d.isoformat(),'week':(d-start).days//7+1,'day':d.isoweekday()} for d in sorted(candidates,key=lambda d:(abs((d-old).days),d))[:3]]
    return result
