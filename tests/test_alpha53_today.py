import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from tests.test_alpha39_companion import data  # noqa: F401
from apps.api.routers import companion, settings, weather
from pengucoach.coach.readiness import compute_readiness, soreness_level
from pengucoach.coach.today import TODAY_CARDS, day_phase, readiness_snapshot, today_preferences
from pengucoach.common.dates import user_today
from pengucoach.db.models import Activity, ActivityFeedback, CoachCheckin, FitFile, UserPreference
from pengucoach.weather import today as hourly


@pytest.mark.parametrize('regions', [{'legs':0}, {'legs':6}, {'head':3}, {'legs':'invalid'}])
def test_region_validation(regions):
    with pytest.raises(ValidationError):
        companion.CheckinIn(soreness_regions=regions)


def test_regional_soreness_is_one_factor_and_none_is_not_whole_body_evidence():
    assert soreness_level({'soreness_regions':{'legs':1}}) is None
    assert soreness_level({'soreness':1,'soreness_regions':{'legs':4,'back':3}})==4
    assert soreness_level({'soreness_regions':{'legs':True,'back':'5'}}) is None
    today=user_today(SimpleNamespace(timezone='UTC'))
    a=compute_readiness({}, {'energy':4,'soreness':4}, [], today=today)
    b=compute_readiness({}, {'energy':4,'soreness_regions':{'legs':4,'back':3}}, [], today=today)
    assert a['score']==b['score']
    assert len([c for c in b['components'] if c['key']=='soreness'])==1


async def test_fast_snapshot_uses_bounded_local_queries_without_plan_or_fit_work(data, monkeypatch):
    db,user,other=data
    import pengucoach.coach.context as context
    import pengucoach.coach.companion as service
    heavy=AsyncMock(side_effect=AssertionError('heavy context must not run'))
    monkeypatch.setattr(context,'build_coach_context',heavy)
    monkeypatch.setattr(service,'personal_context',heavy)
    now=datetime.now(timezone.utc)
    day=user_today(user)
    db.add_all([CoachCheckin(user_id=user.id,date=day-timedelta(days=1),data={'energy':1}),
                CoachCheckin(user_id=other.id,date=day,data={'discomfort':'PRIVATE'})])
    a=Activity(user_id=user.id,garmin_activity_id=-53,started_at=now-timedelta(hours=1),duration_seconds=1800,sport_type='running',name='Run')
    db.add_all([a,Activity(user_id=user.id,garmin_activity_id=-54,started_at=now+timedelta(days=1),duration_seconds=3600,sport_type='running'),
                Activity(user_id=user.id,garmin_activity_id=-55,started_at=now-timedelta(minutes=1),duration_seconds=3600,sport_type='running'),
                Activity(user_id=other.id,garmin_activity_id=-56,started_at=now-timedelta(hours=1),duration_seconds=3600,sport_type='running')])
    await db.flush()
    db.add(ActivityFeedback(activity_id=a.id,user_id=user.id,data={'feeling':'hard','experience':{'text':'PRIVATE'},'route_notes':[{'text':'PRIVATE'}]}))
    await db.flush()
    queries=[]
    engine=db.bind.sync_engine
    def record(conn,cursor,statement,parameters,ctx,many): queries.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try: result=await readiness_snapshot(db,user)
    finally: event.remove(engine,'before_cursor_execute',record)
    assert result['checkin']=={} and 'hard_feedback' in result['reasons']
    assert len(queries)<=7
    assert not any('fit_files' in q or 'ai_runs' in q or 'activities.raw' in q for q in queries)
    assert all(x['id']==str(a.id) for x in result['today_activities'])
    assert 'PRIVATE' not in str(result)
    heavy.assert_not_called()


async def test_region_checkin_persists_and_is_private(data):
    db,user,other=data
    await companion.save_checkin(companion.CheckinIn(soreness_regions={'legs':5},energy=3),user,db)
    assert (await readiness_snapshot(db,user))['checkin']['soreness_regions']=={'legs':5}
    assert 'soreness' in (await readiness_snapshot(db,user))['reasons']
    assert (await readiness_snapshot(db,other))['checkin']=={}


async def test_briefing_route_choices_require_owned_parsed_gps_and_do_not_read_files(data,monkeypatch):
    db,user,other=data
    from pengucoach.coach import companion as service
    monkeypatch.setattr(service,'personal_context',AsyncMock(return_value={}))
    now=datetime.now(timezone.utc)
    for i,(owner,file_owner,quality,status) in enumerate([
        (user,user,{'coverage':{'gps':99}},'parsed'),
        (user,other,{'coverage':{'gps':99}},'parsed'),
        (other,other,{'coverage':{'gps':99}},'parsed'),
        (user,user,{'coverage':{'gps':None}},'parsed'),
        (user,user,{'coverage':None},'parsed'),
        (user,user,{'coverage':{'gps':99}},'downloaded'),
    ]):
        a=Activity(user_id=owner.id,garmin_activity_id=-530-i,started_at=now-timedelta(hours=2),duration_seconds=1800,sport_type='road_biking',name=f'Route {i}')
        db.add(a);await db.flush()
        db.add(FitFile(user_id=file_owner.id,activity_id=a.id,status=status,data_quality=quality,original_path='does-not-exist.fit',file_size=1,sha256=str(i)))
    await db.flush()
    result=await service.briefing(db,user)
    assert [r['name'] for r in result['route_options']]==['Route 0']
    assert result['route_options'][0]['sport']=='cycling'


async def test_today_settings_merge_isolation_and_read_only_get(data):
    db,user,other=data
    assert (await settings.get_today_settings(user,db))['order']==TODAY_CARDS
    assert await db.get(UserPreference,user.id) is None
    pref=UserPreference(user_id=user.id,theme='slate',dashboard_config={'weather':{'enabled':True},'maps':{'secret':'preserved'}})
    db.add(pref); await db.flush()
    result=await settings.save_today_settings(settings.TodaySettingsIn(order=['reflection'],hidden=['weather'],pinned_metrics=['hrv'],preferred_start_hour=16,preferred_end_hour=22),user,db)
    assert result['order'][0]=='reflection' and len(result['order'])==len(TODAY_CARDS)
    assert pref.dashboard_config['maps']=={'secret':'preserved'} and pref.theme=='slate'
    assert (await settings.get_today_settings(other,db))['hidden']==[]


@pytest.mark.parametrize('kwargs',[{'order':['weather','weather']},{'hidden':['weather','weather']},{'pinned_metrics':[]},{'pinned_metrics':['hrv','hrv']},{'preferred_start_hour':22,'preferred_end_hour':7},{'order':['unknown']}])
def test_today_settings_reject_invalid_inputs(kwargs):
    with pytest.raises(ValidationError): settings.TodaySettingsIn(**kwargs)


@pytest.mark.parametrize('raw',[None,[],{'order':None,'hidden':42,'pinned_metrics':{},'preferred_start_hour':'x'}, {'order':[{},'weather','weather'],'preferred_start_hour':23,'preferred_end_hour':2}])
def test_settings_recover_malformed_legacy_values(raw):
    result=today_preferences(SimpleNamespace(dashboard_config={'today':raw}))
    assert len(result['order'])==len(TODAY_CARDS) and result['preferred_start_hour']==7


def test_day_phase_never_treats_ambiguous_match_as_completed():
    day='2026-10-10'; s={'date':day}; a={'id':'a'}
    assert day_phase(day,8,[s],[],[],{})=='morning'
    assert day_phase(day,8,[s],[],[],{'energy':4})=='preparation'
    assert day_phase(day,18,[s],[a],[{'status':'ambiguous','activity_id':'a'}],{})=='preparation'
    assert day_phase(day,8,[],[a],[{'status':'matched','activity_id':'a'}],{})=='reflection'
    assert day_phase(day,8,[],[],[{'status':'matched','activity_id':'a'}],{})=='morning'


def rows(start,n=12):
    return [{'time':(start+timedelta(hours=i)).timestamp(),'temperature_2m':18,'precipitation_probability':0,'wind_speed_10m':10,'wind_gusts_10m':15,'weather_code':0,'is_day':1} for i in range(n)]


def windows(values,now,minutes=45,zone=ZoneInfo('UTC'),start=7,end=21):
    return hourly.weather_windows(values,now=now,zone=zone,minutes=minutes,start_hour=start,end_hour=end)


def test_weather_probability_and_gusts_use_covered_hour_end_and_keep_zero():
    now=datetime(2026,10,10,7,tzinfo=timezone.utc); values=rows(now,2)
    values[0]['precipitation_probability']=99; values[0]['wind_gusts_10m']=90
    result=windows(values,now)[0]
    assert result['rain_probability']==0 and result['gusts_kmh']==15 and result['warnings']==[]
    values[1]['precipitation_probability']=90; values[1]['wind_gusts_10m']=60
    assert windows(values,now)[0]['warnings']==['rain','wind']


@pytest.mark.parametrize('field',hourly.FIELDS)
def test_missing_weather_is_not_optimistic(field):
    now=datetime(2026,10,10,7,tzinfo=timezone.utc); values=rows(now,3)
    values[1][field]=None
    assert windows(values,now,minutes=90)==[]


def test_weather_duration_preferences_past_gaps_and_nonoverlap():
    now=datetime(2026,10,10,7,30,tzinfo=timezone.utc); values=rows(now.replace(minute=0))
    result=windows(values,now,minutes=90,start=9,end=16)
    assert len(result)==3
    for w in result:
        a,b=datetime.fromisoformat(w['start']),datetime.fromisoformat(w['end'])
        assert a.hour>=9 and b.hour<=16 and b-a==timedelta(minutes=90)
    for a,b in zip(sorted(result,key=lambda w:w['start']),sorted(result,key=lambda w:w['start'])[1:]):
        assert datetime.fromisoformat(b['start'])-datetime.fromisoformat(a['start'])>=timedelta(hours=2)
    values[1]['time']+=1800
    assert windows(values[:3],now.replace(minute=0),minutes=90)==[]


@pytest.mark.parametrize('date',[(2026,3,29),(2026,10,25)])
def test_weather_dst_keeps_actual_elapsed_duration(date):
    start=datetime(*date,0,tzinfo=timezone.utc); result=windows(rows(start,8),start,minutes=90,zone=ZoneInfo('Europe/Berlin'),start=0,end=12)
    assert len(result)==3
    assert all(datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])==timedelta(minutes=90) for w in result)


async def test_weather_disabled_makes_no_provider_request(data,monkeypatch):
    db,user,_=data; provider=AsyncMock(side_effect=AssertionError('provider must not run'))
    monkeypatch.setattr(hourly,'fetch_hours',provider)
    result=await weather.today_weather_windows(45,user,db)
    assert result['reason']=='not_configured'; provider.assert_not_called()


async def test_forecast_singleflight_units_partial_arrays_and_cache_copy(monkeypatch):
    hourly._CACHE.clear();hourly._LOCKS.clear();calls=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'hourly':{'time':[1,3601],'temperature_2m':[18]}}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url,params): calls.append(params);await asyncio.sleep(0);return Response()
    monkeypatch.setattr(hourly.httpx,'AsyncClient',Client)
    a,b=await asyncio.gather(hourly.fetch_hours(48,11,'Europe/Berlin'),hourly.fetch_hours(48,11,'Europe/Berlin'))
    assert len(calls)==1 and calls[0]['timeformat']=='unixtime' and calls[0]['wind_speed_unit']=='kmh'
    assert a['rows'][1]['temperature_2m'] is None
    a['rows'][0]['temperature_2m']=99
    assert b['rows'][0]['temperature_2m']==18
    assert (await hourly.fetch_hours(48,11,'Europe/Berlin'))['rows'][0]['temperature_2m']==18
    hourly._CACHE.clear();hourly._LOCKS.clear()
