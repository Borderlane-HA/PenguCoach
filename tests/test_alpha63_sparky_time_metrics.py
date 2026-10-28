import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from apps.api.routers.activities import _summary
from pengucoach.coach.context import _activity_garmin
from pengucoach.coach.plan_evolution import compare_v2
from pengucoach.db.base import Base
from pengucoach.db.models import Activity, ActivityFeedback, SourceRecord, User
from pengucoach.fit.activity_detail import selected_activity_extras
from pengucoach.sparkyfitness.activity_time import resolve_activity_time
from pengucoach.sparkyfitness.sync import _enrich_activity_item, _merge_activity, _repair_activity_times, _sport, _sync_activities, _synthetic_activity_id

@compiles(JSONB, 'sqlite')
def json_sqlite(type_, compiler, **kw):return 'JSON'

@pytest.mark.parametrize('clock', ['09:24:00','14:38:00','18:05:00'])
@pytest.mark.parametrize('day,offset', [('2026-10-17',2),('2026-12-17',1)])
def test_sparky_clock_uses_recording_timezone(clock,day,offset):
    info=resolve_activity_time({'entry_date':day,'entry_time':clock,'record_timezone':'Europe/Berlin','start_time':day+'T00:00:00Z'})
    assert info.timestamp.astimezone(ZoneInfo('Europe/Berlin')).isoformat().startswith(day+'T'+clock)
    assert info.timestamp.hour==(int(clock[:2])-offset)%24
    assert info.precision=='second' and info.local_date==date.fromisoformat(day)

def test_original_wrapped_json_time_wins_and_preserves_real_midnight():
    row={'entry_date':'2026-10-17','entry_time':'09:24','record_timezone':'Europe/Berlin',
         'provider_activity_details':{'data':{'raw_data':json.dumps({'startTime':'2026-10-17T00:00:00Z'})}}}
    info=resolve_activity_time(row)
    assert info.timestamp==datetime(2026,10,17,tzinfo=timezone.utc)
    assert info.precision=='second' and info.source=='raw_data.startTime'

def test_user_zone_fallback_and_explicit_local_midnight():
    info=resolve_activity_time({'entry_date':'2026-10-17','entry_time':'00:00:00'},'Europe/Berlin')
    assert info.timestamp==datetime(2026,10,16,22,tzinfo=timezone.utc)
    assert info.local_date==date(2026,10,17) and info.precision=='second'
    assert resolve_activity_time({'entry_date':'2026-10-17'},'America/Los_Angeles').local_date==date(2026,10,17)

@pytest.mark.parametrize('row', [
    {'entry_date':'2026-03-29','entry_time':'02:30','record_timezone':'Europe/Berlin'},
    {'entry_date':'2026-10-25','entry_time':'02:30','record_timezone':'Europe/Berlin'},
    {'entry_date':'2026-10-17','entry_time':'09:24','record_timezone':'invalid/zone'},
    {'entry_date':'2026-10-17','entry_time':'bad','record_timezone':'Europe/Berlin'},
    {'entry_date':'2026-10-17','start_time':'2026-10-17T00:00:00Z'},
])
def test_missing_invalid_or_ambiguous_clock_is_date_only(row):
    info=resolve_activity_time(row,'Europe/Berlin')
    assert info.precision=='date' and info.local_date==date.fromisoformat(row['entry_date'])
    assert info.timestamp is not None

def test_explicit_offset_resolves_repeated_clock_hour():
    info=resolve_activity_time({'entry_date':'2026-10-25','entry_time':'02:30:00+01:00','record_timezone':'Europe/Berlin'})
    assert info.precision=='second' and info.timestamp.hour==1

def test_min_hr_numeric_strings_json_and_metric_units():
    raw={'source':'sparkyfitness','sparkyfitness':{'exercise_entry_details':{'raw_data':json.dumps({'minHeartRate':'96',
        'maxPower':'510','maxCadence':'110','ground_contact_time_ms':'240','vertical_oscillation_mm':'76',
        'stride_length_cm':'112','stroke_count':'40','min_temperature_celsius':'-2','avg_temperature':'0'})}}}
    extra=selected_activity_extras(raw)
    assert extra['min_hr_bpm']==96 and extra['max_power_w']==510 and extra['max_cadence']==110
    assert extra['avg_ground_contact_time_ms']==240 and extra['avg_vertical_oscillation_cm']==7.6
    assert extra['avg_stride_length_cm']==112 and extra['stroke_count']==40
    assert extra['temperature_min_c']==-2 and extra['temperature_avg_c']==0
    raw['minHR']=88
    assert selected_activity_extras(raw)['min_hr_bpm']==88

def test_hr_statistics_do_not_use_unrelated_minima_or_invalid_values():
    raw={'sparkyfitness':{'raw_data':json.dumps({'heartRateStatistics':{'minimum':{'quantity':95}},'duration':{'minimum':1}})}}
    assert selected_activity_extras(raw)['min_hr_bpm']==95
    for value in [None,'',True,'NaN','Infinity','0','-1',float('nan')]:
        assert 'min_hr_bpm' not in selected_activity_extras({'sparkyfitness':{'min_heart_rate':value}})
    assert 'min_hr_bpm' not in selected_activity_extras({'sparkyfitness':{'duration':{'minimum':1}}})

@pytest.mark.parametrize('name,sport', [('Walking','walking'),('Hiking','hiking'),('Functional Strength Training','strength')])
def test_individual_is_entry_kind_not_sport(name,sport):
    assert _sport({'type':'individual','exercise_name':name})==sport

async def test_missing_clock_enriches_complete_headlines():
    item={'id':'one','entry_date':'2026-10-17','type':'individual','exercise_name':'Walking',
          'distance':6.03,'duration_minutes':54.35,'calories_burned':345,'avg_heart_rate':119,'min_heart_rate':96,
          'elevation_gain_meters':22,'elevation_loss_meters':28,'min_elevation_meters':378,'max_elevation_meters':391,'max_speed_mps':2.1}
    class Client:
        calls=[]
        async def request(self,path):
            self.calls.append(path)
            return {'data':{**item,'entry_time':'09:24:00','record_timezone':'Europe/Berlin'}}
    client=Client();enriched,count=await _enrich_activity_item(client,item)
    assert count==1 and len(client.calls)==1
    assert resolve_activity_time(enriched).timestamp.hour==7

async def test_historical_repair_preserves_ids_feedback_garmin_and_other_users():
    engine=create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
    Session=async_sessionmaker(engine,expire_on_commit=False)
    async with Session() as db:
        user=User(username='owner',email='owner@example.invalid',password_hash='x',timezone='Europe/Berlin');other=User(username='other',email='other@example.invalid',password_hash='x');db.add_all([user,other]);await db.flush()
        item={'id':'walk','entry_date':'2026-10-17','entry_time':'09:24:00','record_timezone':'Europe/Berlin','type':'individual','exercise_name':'Walking','duration_minutes':54.35,'distance':6.03,'min_heart_rate':'96','avg_heart_rate':119}
        stamp=datetime(2026,10,17,tzinfo=timezone.utc)
        a=Activity(user_id=user.id,garmin_activity_id=_synthetic_activity_id('walk'),name='Walking',sport_type='individual',started_at=stamp,duration_seconds=3261,moving_seconds=3261,raw={'source':'sparkyfitness','sparkyfitness':item,'sparkyfitness_external_id':'walk'})
        garmin=Activity(user_id=user.id,garmin_activity_id=100,name='Garmin',sport_type='walking',started_at=stamp,raw={'sparkyfitness':item,'minHR':90})
        foreign=Activity(user_id=other.id,garmin_activity_id=-999,name='Other',started_at=stamp,raw={'source':'sparkyfitness','sparkyfitness':item})
        db.add_all([a,garmin,foreign]);await db.flush();aid=a.id
        feedback=ActivityFeedback(user_id=user.id,activity_id=a.id,data={'feeling':'right'});db.add(feedback);await db.flush()
        assert await _repair_activity_times(db,user.id,user.timezone)==1
        assert a.id==aid and a.started_at.hour==7 and a.started_at.minute==24
        assert a.moving_seconds is None and a.sport_type=='walking'
        assert garmin.started_at==stamp and foreign.started_at==stamp
        assert await _repair_activity_times(db,user.id,user.timezone)==0
        await db.commit()
        outcome,newid=await _merge_activity(db,user.id,item,'walk',user.timezone)
        assert outcome=='updated' and newid==aid
        saved_feedback=await db.scalar(select(ActivityFeedback).where(ActivityFeedback.activity_id==aid))
        assert saved_feedback.data=={'feeling':'right'} and saved_feedback.user_id==user.id
        assert len((await db.scalars(select(Activity))).all())==3
        assert _summary(a)['time_precision']=='second'
        assert _activity_garmin(a)['heart_rate']['min_bpm']==96
        class HistoryClient:
            async def request(self,path,params=None):
                local_item={k:v for k,v in item.items() if k!='record_timezone'}
                return {'sessions':[local_item]} if path.endswith('/history') else local_item
        result=await _sync_activities(db,HistoryClient(),user.id,None)
        assert result['activities_updated']==1 and result['activities_created']==0
        source=await db.scalar(select(SourceRecord).where(SourceRecord.user_id==user.id))
        assert source.observed_at.hour==7 and source.observed_at.minute==24
        assert source.record_date==date(2026,10,17)
        assert a.id==aid and len((await db.scalars(select(Activity))).all())==3
    await engine.dispose()

def test_date_only_excluded_from_four_hour_match_but_manual_allowed():
    user=SimpleNamespace(timezone='Europe/Berlin');info=resolve_activity_time({'entry_date':'2026-10-17'},user.timezone)
    a=SimpleNamespace(id=uuid.uuid4(),name='Walking',sport_type='walking',started_at=info.timestamp,duration_seconds=1800,avg_hr=None,avg_power=None,
        raw={'source':'sparkyfitness','sparkyfitness':{'entry_date':'2026-10-17'},'_sparkyfitness_time':info.metadata()})
    planned={'id':'s','date':'2026-10-17','start_time':'00:30','sport':'walking','duration_min':30,'steps':[]}
    result=compare_v2([planned],[a],user)[0]
    assert result['activity_id'] is None and not result['candidates'][0]['within_window']
    assert result['candidates'][0]['hours_difference'] is None
    assert compare_v2([planned],[a],user,confirmed={'s':SimpleNamespace(activity_id=a.id,state='matched')})[0]['activity_id']==str(a.id)
    assert compare_v2([{**planned,'start_time':None}],[a],user)[0]['activity_id']==str(a.id)


def test_unknown_clock_is_explicit_in_api_and_coach_context():
    info=resolve_activity_time({'entry_date':'2026-10-17'},'Europe/Berlin')
    a=Activity(id=uuid.uuid4(),garmin_activity_id=-100,started_at=info.timestamp,sport_type='walking',
        raw={'source':'sparkyfitness','sparkyfitness':{'entry_date':'2026-10-17'},'_sparkyfitness_time':info.metadata()})
    assert _summary(a)['time_precision']=='date' and _summary(a)['activity_date']=='2026-10-17'
    context=_activity_garmin(a)
    assert context['started_at'] is None and context['time_precision']=='date'
    assert context['activity_date']=='2026-10-17'
