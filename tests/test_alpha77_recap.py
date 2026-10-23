"""Alpha.77 activity recap ("Rückblick")."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from pengucoach.coach import recap


def row(day, sport='running', distance=None, duration=None, elevation=None, calories=None, power=None, name=None):
    return {'id':uuid.uuid4(),'name':name,'sport_type':sport,'day':day,'distance_m':distance,'duration_s':duration,
            'elevation_m':elevation,'calories':calories,'avg_power':power}


@pytest.mark.parametrize('period,today,start,prev_start,prev_end',[
    ('today',date(2026,10,23),date(2026,10,23),date(2026,10,22),date(2026,10,22)),
    ('week',date(2026,10,23),date(2026,10,19),date(2026,10,12),date(2026,10,16)),
    ('month',date(2026,3,31),date(2026,3,1),date(2026,2,1),date(2026,2,28)),
    ('month',date(2026,10,23),date(2026,10,1),date(2026,9,1),date(2026,9,23)),
    ('year',date(2028,12,31),date(2028,1,1),date(2027,1,1),date(2027,12,31)),
])
def test_periods_compare_with_the_same_elapsed_span(period,today,start,prev_start,prev_end):
    bounds=recap.period_bounds(period,today)
    assert (bounds['start'],bounds['previous_start'],bounds['previous_end'])==(start,prev_start,prev_end)


def test_all_time_has_no_comparison_and_invalid_period_is_rejected():
    assert recap.period_bounds('all',date(2026,1,1))['previous_start'] is None
    with pytest.raises(ValueError):recap.period_bounds('decade',date(2026,1,1))


def test_totals_skip_missing_values_instead_of_counting_zero():
    rows=[row(date(2026,10,1),distance=10000,duration=3000,elevation=100,calories=700),
          row(date(2026,10,2),sport='strength_training',duration=1800,calories=None),
          row(date(2026,10,2),distance=float('nan'),elevation=-5)]
    t=recap.totals(rows)
    assert t['count']==3 and t['distance_m']==10000 and t['elevation_m']==100 and t['duration_s']==4800
    assert (t['with_distance'],t['with_elevation'],t['with_calories'])==(1,1,1)


def test_summary_streaks_sports_highlights_and_change():
    today=date(2026,10,23)
    rows=[row(today,distance=5000,duration=1500,name='Kurz'),row(today-timedelta(days=1),distance=12000,duration=4300,elevation=240,name='Lang'),
          row(today-timedelta(days=2),sport='road_biking',distance=40000,duration=5400,elevation=600,power=215),
          row(today-timedelta(days=5),sport='lap_swimming',distance=1500,duration=2400)]
    previous=[row(date(2026,9,10),distance=29250,duration=6800)]
    result=recap.summarize(rows,period='month',today=today,previous=previous)
    assert result['active_days']==4 and result['streaks']=={'longest':3,'current':3}
    assert [s['sport'] for s in result['sports']]==['run','ride','swim']  # sorted by time
    h=result['highlights']
    assert h['longest_distance']['value']==40000 and h['biggest_climb']['value']==600
    assert h['fastest_run']['name']=='Kurz' and h['fastest_run']['pace_s_per_km']==300.0
    assert h['strongest_ride']['value']==215
    assert result['change']['distance_m']==100.0 and result['change']['elevation_m'] is None
    days=result['series']['items']
    assert result['series']['granularity']=='day' and len(days)==23 and days[-1]['count']==1


def test_current_streak_continues_from_yesterday_but_breaks_after_a_gap():
    today=date(2026,10,23)
    assert recap.summarize([row(today-timedelta(days=1)),row(today-timedelta(days=2))],period='week',today=today)['streaks']['current']==2
    assert recap.summarize([row(today-timedelta(days=3))],period='week',today=today)['streaks']['current']==0


def test_full_history_is_bucketed_by_month_and_empty_periods_are_valid():
    result=recap.summarize([row(date(2025,11,30),distance=1000),row(date(2026,1,2),distance=2000)],period='all',today=date(2026,2,10))
    assert result['series']['granularity']=='month'
    assert [i['key'] for i in result['series']['items']]==['2025-11','2025-12','2026-01','2026-02']
    assert result['start']=='2025-11-30' and result['change']=={}
    empty=recap.summarize([],period='year',today=date(2026,2,10))
    assert empty['totals']['count']==0 and empty['highlights']=={} and len(empty['series']['items'])==41


def test_routes_are_thinned_but_keep_start_and_finish():
    points=[(48+i*1e-4,11+i*1e-4) for i in range(1000)]+[(None,None),(0.0,0.0)]
    route=recap.downsample(points,limit=50)
    assert len(route)==50 and route[0]==[48.0,11.0] and route[-1]==[round(48+999e-4,5),round(11+999e-4,5)]
    assert recap.downsample([(1.0,1.0)])==[]


async def test_recap_endpoint_uses_journal_filters_time_zone_and_previous_period(tmp_path,monkeypatch):
    import pandas as pd
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
    from sqlalchemy.ext.compiler import compiles
    from apps.api.routers import activities as router
    from pengucoach.db.base import Base
    from pengucoach.db.models import Activity,FitFile,User
    @compiles(JSONB,'sqlite')
    def sqlite_json(type_,compiler,**kw):return 'JSON'
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/recap.sqlite')
    async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    berlin_now=datetime.now(timezone.utc)
    async with factory() as db:
        user=User(username='sv',email='sv@host',password_hash='x',timezone='Europe/Berlin');db.add(user);await db.flush()
        other=User(username='other',email='o@host',password_hash='x');db.add(other);await db.flush()
        def act(owner,started,**kw):
            return Activity(user_id=owner.id,garmin_activity_id=abs(hash((owner.username,started)))%10**9+1,started_at=started,fit_status='parsed',raw={},**kw)
        mine=act(user,berlin_now-timedelta(minutes=5),name='Heute',sport_type='running',distance_m=8000,moving_seconds=2400,elevation_gain=50,calories=500)
        old=act(user,berlin_now-timedelta(days=400),name='Alt',sport_type='running',distance_m=5000,moving_seconds=1500)
        foreign=act(other,berlin_now-timedelta(minutes=5),name='Fremd',sport_type='running',distance_m=99000)
        db.add_all([mine,old,foreign]);await db.flush()
        parquet=tmp_path/'route.parquet'
        pd.DataFrame({'position_lat':[48.1,48.11,48.12],'position_long':[11.5,11.51,11.52]}).to_parquet(parquet)
        db.add(FitFile(user_id=user.id,activity_id=mine.id,original_path='x',parquet_path=str(parquet),file_size=1,sha256='0'*64,status='parsed'))
        await db.commit()
        today=await router.activity_recap(period='today',q=None,sport=None,source=None,routes=True,user=user,db=db)
        assert today['totals']['count']==1 and today['totals']['distance_m']==8000
        assert today['routes'][0]['points'][0]==[48.1,11.5] and today['timezone']=='Europe/Berlin'
        everything=await router.activity_recap(period='all',q=None,sport=None,source=None,routes=False,user=user,db=db)
        assert everything['totals']['count']==2 and everything['routes']==[]
        searched=await router.activity_recap(period='all',q='Alt',sport=None,source=None,routes=False,user=user,db=db)
        assert searched['totals']['count']==1 and searched['query']=='Alt'
    await engine.dispose()
