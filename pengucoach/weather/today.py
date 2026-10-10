"""Hourly weather comparisons; optional, separate from readiness and plan writes."""
import asyncio
import copy
import math
import time
from datetime import datetime, timedelta, timezone

import httpx

from pengucoach.weather.service import FORECAST_URL
from pengucoach.coach.workout_review import number

FIELDS = ('temperature_2m','precipitation_probability','wind_speed_10m','wind_gusts_10m','weather_code','is_day')
_CACHE = {}
_LOCKS = {}


async def fetch_hours(latitude, longitude, zone):
    key = (latitude, longitude, zone)
    cached = _CACHE.get(key)
    if cached and time.monotonic()-cached[0] < 600:
        return copy.deepcopy(cached[1])
    # Bounded process-local cache of public forecasts. No check-in/user data cached.
    if len(_LOCKS) > 64:
        for old in list(_LOCKS):
            if not _LOCKS[old].locked():
                _LOCKS.pop(old, None)
                if len(_LOCKS) <= 32: break
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _CACHE.get(key)
        if cached and time.monotonic()-cached[0] < 600:
            return copy.deepcopy(cached[1])
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(FORECAST_URL, params={'latitude':latitude,'longitude':longitude,'timezone':zone,
                'forecast_days':2,'hourly':','.join(FIELDS),'timeformat':'unixtime','wind_speed_unit':'kmh','temperature_unit':'celsius'})
            response.raise_for_status()
            payload = response.json()
        hourly = payload.get('hourly') or {}
        timestamps = hourly.get('time') or []
        rows = [{'time':stamp, **{field:(hourly.get(field) or [])[index] if index<len(hourly.get(field) or []) else None for field in FIELDS}}
                for index,stamp in enumerate(timestamps)]
        result = {'rows':rows,'fetched_at':datetime.now(timezone.utc).isoformat(),'provider':'Open-Meteo','provider_url':'https://open-meteo.com/'}
        _CACHE[key] = (time.monotonic(),result)
        if len(_CACHE) > 64:
            _CACHE.pop(min(_CACHE,key=lambda k:_CACHE[k][0]),None)
        return copy.deepcopy(result)


def weather_windows(rows, *, now, zone, minutes, start_hour, end_hour):
    """Complete hourly coverage. Unix instants keep local DST boundaries correct.

    Rain probability and gusts refer to the preceding hour: use end-boundary
    readings for each covered hour. Partial hours conservatively use that hour.
    """
    now = now.astimezone(timezone.utc)
    today = now.astimezone(zone).date()
    count = math.ceil(minutes/60)
    valid = []
    for row in rows:
        stamp = number(row.get('time'))
        values = {key:number(row.get(key)) for key in FIELDS}
        if stamp is None or any(value is None for value in values.values()):
            valid.append(None);continue
        if not (0<=values['precipitation_probability']<=100 and values['wind_speed_10m']>=0 and values['wind_gusts_10m']>=0
                and -80<=values['temperature_2m']<=60 and values['is_day'] in {0,1} and values['weather_code'] in {0,1,2,3,45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,99}):
            valid.append(None);continue
        valid.append({'time':stamp,**values})
    candidates = []
    for index in range(max(0,len(valid)-count)):
        section = valid[index:index+count+1]
        if any(r is None for r in section) or any(b['time']-a['time']!=3600 for a,b in zip(section,section[1:])):
            continue
        begin = datetime.fromtimestamp(section[0]['time'],timezone.utc)
        end = begin+timedelta(minutes=minutes)
        local_start,local_end = begin.astimezone(zone),end.astimezone(zone)
        if begin<now or local_start.date()!=today or local_start.hour<start_hour:
            continue
        if local_end.date()!=today:
            if not (end_hour==24 and local_end.date()==today+timedelta(days=1) and local_end.hour==0 and local_end.minute==0):continue
        elif local_end.hour+local_end.minute/60>end_hour:continue
        rain = max(r['precipitation_probability'] for r in section[1:])
        wind = max(r['wind_speed_10m'] for r in section)
        gusts = max(r['wind_gusts_10m'] for r in section[1:])
        lo,hi = min(r['temperature_2m'] for r in section),max(r['temperature_2m'] for r in section)
        warnings = []
        if any(r['weather_code'] in {95,96,99} for r in section):warnings.append('thunderstorm')
        if any(r['weather_code'] in {56,57,66,67,71,73,75,77,85,86} for r in section):warnings.append('snow_ice')
        if rain>=60:warnings.append('rain')
        if wind>=30 or gusts>=50:warnings.append('wind')
        if hi>=30:warnings.append('heat')
        if lo<=0:warnings.append('cold')
        daylight = all(r['is_day']==1 for r in section)
        score = rain+wind+gusts*.5+max(0,hi-25)*4+max(0,5-lo)*4+(0 if daylight else 15)+(200 if {'thunderstorm','snow_ice'}&set(warnings) else 0)
        candidates.append({'start':begin.isoformat(),'end':end.isoformat(),'start_label':local_start.strftime('%H:%M'),
            'end_label':local_end.strftime('%H:%M'),'temperature_min':round(lo,1),'temperature_max':round(hi,1),
            'rain_probability':round(rain),'wind_kmh':round(wind),'gusts_kmh':round(gusts),'daylight':daylight,
            'warnings':warnings,'_rank':score,'_coverage_end':begin+timedelta(hours=count)})
    selected = []
    for candidate in sorted(candidates,key=lambda r:(r['_rank'],r['start'])):
        start = datetime.fromisoformat(candidate['start'])
        end = candidate['_coverage_end']
        if any(start<r['_coverage_end'] and end>datetime.fromisoformat(r['start']) for r in selected):continue
        selected.append(candidate)
        if len(selected)==3:break
    return [{k:v for k,v in r.items() if not k.startswith('_')} for r in selected]
