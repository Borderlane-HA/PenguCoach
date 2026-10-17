"""Alpha.51: user-confirmed experiences, efforts, route notes and draft checks."""
import asyncio
import copy
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.routers.activities import _owned_activity
from apps.api.routers.companion import ScheduleIn, guard_exported, plan_owned, validate_overrides
from apps.api.routers.insights import _series
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.coach.companion import scheduled_sessions, sport_family
from pengucoach.coach.plan_evolution import comparison_data
from pengucoach.coach.session_features import alternative_days, best_efforts, experiences, route_briefing, route_plan_overlay
from pengucoach.coach.training_intelligence import _sessions_for_schedule, plan_conflicts
from pengucoach.coach.workout_review import number
from pengucoach.common.dates import user_today
from pengucoach.db.models import Activity, ActivityFeedback, AiRun, CoachProfile, FitFile, GarminWorkoutExport, PlanSchedule
from pengucoach.db.session import get_db

router=APIRouter(tags=['session-features'])


async def feedback_row(db, user, activity):
    row=await db.scalar(select(ActivityFeedback).where(ActivityFeedback.activity_id==activity.id,ActivityFeedback.user_id==user.id))
    if not row:
        row=ActivityFeedback(activity_id=activity.id,user_id=user.id,data={})
        db.add(row)
    return row


class ExperienceIn(BaseModel):
    text: str=Field(min_length=1,max_length=1000)
    kind: Literal['all','interval','endurance','strength']='all'
    enabled: bool=True


@router.get('/coach/experiences')
async def list_experiences(user=Depends(safety_confirmed_user),db=Depends(get_db)):
    return await experiences(db,user)


@router.put('/coach/experiences/{activity_id}')
async def save_experience(activity_id: uuid.UUID,payload: ExperienceIn,user=Depends(safety_confirmed_user),db=Depends(get_db)):
    activity=await _owned_activity(activity_id,user,db)
    if not payload.text.strip():
        raise HTTPException(422,'EXPERIENCE_EMPTY')
    existing=await experiences(db,user)
    if len(existing)>=50 and not any(e['activity_id']==str(activity.id) for e in existing):
        raise HTTPException(409,'EXPERIENCE_LIMIT_50')
    row=await feedback_row(db,user,activity)
    row.data={**(row.data or {}),'experience':{**payload.model_dump(),'text':payload.text.strip()}}
    await db.commit()
    return row.data['experience']


@router.delete('/coach/experiences/{activity_id}')
async def delete_experience(activity_id: uuid.UUID,user=Depends(safety_confirmed_user),db=Depends(get_db)):
    await _owned_activity(activity_id,user,db)
    row=await db.scalar(select(ActivityFeedback).where(ActivityFeedback.activity_id==activity_id,ActivityFeedback.user_id==user.id))
    if row:
        data=dict(row.data or {});data.pop('experience',None);row.data=data
        await db.commit()
    return {'deleted':True}


async def full_series(db,user,activity):
    fit=await db.scalar(select(FitFile).where(FitFile.activity_id==activity.id,FitFile.user_id==user.id,FitFile.status=='parsed'))
    from pengucoach.fit.service import load_recording_series
    return await asyncio.to_thread(load_recording_series, activity, fit, 100_000)


def read_full(fit):
    if not fit.parquet_path:
        return []
    import pandas as pd
    from pengucoach.fit.activity_detail import serialize_series
    frame=pd.read_parquet(fit.parquet_path)
    return serialize_series(frame,limit=max(1,len(frame)))


@router.get('/activities/{activity_id}/best-efforts')
async def activity_efforts(activity_id: uuid.UUID,user=Depends(safety_confirmed_user),db=Depends(get_db)):
    activity=await _owned_activity(activity_id,user,db)
    rows=await full_series(db,user,activity)
    items=await asyncio.to_thread(best_efforts,rows)
    return {'items':items,'sport':sport_family(activity.sport_type),'scope':'activity','method':'complete_sample_held_time_windows','origin_s':number(rows[0].get('elapsed_s')) if rows else 0}


@router.get('/coach/best-efforts')
async def personal_efforts(sport: Literal['running','cycling','swimming','walking','hiking','strength','other']='running',user=Depends(safety_confirmed_user),db=Depends(get_db)):
    from pengucoach.common.dates import user_zone
    now=datetime.now(timezone.utc)
    # Sport filtering happens before the bounded candidate window.
    records=(await db.execute(select(Activity,FitFile).join(FitFile,FitFile.activity_id==Activity.id).where(Activity.user_id==user.id,FitFile.user_id==user.id,FitFile.status=='parsed',Activity.started_at>=now-timedelta(days=365),Activity.started_at<=now).order_by(Activity.started_at.desc()))).all()
    candidates=[(a,f) for a,f in records if sport_family(a.sport_type)==sport][:50]
    def calculate():
        winners={};failed=0
        for activity,fit in candidates:
            try:
                rows=read_full(fit)
                efforts=best_efforts(rows)
            except (OSError,ValueError):
                failed+=1;continue
            at=activity.started_at
            if not at.tzinfo:at=at.replace(tzinfo=timezone.utc)
            for effort in efforts:
                key=(effort['metric'],effort['seconds'])
                if key not in winners or effort['value']>winners[key]['value']:
                    winners[key]={**effort,'activity_id':str(activity.id),'name':activity.name,'date':at.astimezone(user_zone(user)).date().isoformat(),'origin_s':number(rows[0].get('elapsed_s')) if rows else 0}
        return {'items':list(winners.values()),'sport':sport,'scope':'recent_recordings','window_days':365,'candidate_limit':50,'scanned':len(candidates),'failed':failed,'limited':len([a for a,f in records if sport_family(a.sport_type)==sport])>50}
    return await asyncio.to_thread(calculate)


class RouteNoteIn(BaseModel):
    text: str=Field(min_length=1,max_length=300)
    point_index: int=Field(ge=0,le=4999)
    id: uuid.UUID | None=None


@router.put('/activities/{activity_id}/route-notes')
async def save_route_note(activity_id: uuid.UUID,payload: RouteNoteIn,user=Depends(safety_confirmed_user),db=Depends(get_db)):
    activity=await _owned_activity(activity_id,user,db)
    rows=await _series(db,user,activity)
    if payload.point_index>=len(rows) or not payload.text.strip():
        raise HTTPException(422,'INVALID_ROUTE_POINT')
    point=rows[payload.point_index]
    lat,lon=number(point.get('position_lat')),number(point.get('position_long'))
    if lat is None or lon is None or abs(lat)>90 or abs(lon)>180:
        raise HTTPException(422,'ROUTE_POINT_NEEDS_GPS')
    row=await feedback_row(db,user,activity)
    notes=copy.deepcopy((row.data or {}).get('route_notes') or [])
    if payload.id and not any(n['id']==str(payload.id) for n in notes):
        raise HTTPException(404,'ROUTE_NOTE_NOT_FOUND')
    if not payload.id and len(notes)>=40:
        raise HTTPException(409,'ROUTE_NOTE_LIMIT_40')
    note={'id':str(payload.id or uuid.uuid4()),'text':payload.text.strip(),'point_index':payload.point_index,'start_s':number(point.get('elapsed_s')),'distance_km':number(point.get('distance_km')),'lat':lat,'lon':lon}
    notes=[n for n in notes if n['id']!=note['id']]+[note]
    row.data={**(row.data or {}),'route_notes':notes}
    await db.commit()
    return note


@router.delete('/activities/{activity_id}/route-notes/{note_id}')
async def delete_route_note(activity_id: uuid.UUID,note_id: uuid.UUID,user=Depends(safety_confirmed_user),db=Depends(get_db)):
    await _owned_activity(activity_id,user,db)
    row=await db.scalar(select(ActivityFeedback).where(ActivityFeedback.activity_id==activity_id,ActivityFeedback.user_id==user.id))
    if row:
        notes=[n for n in (row.data or {}).get('route_notes',[]) if n['id']!=str(note_id)]
        row.data={**row.data,'route_notes':notes};await db.commit()
    return {'deleted':True}


@router.get('/activities/{activity_id}/route-briefing')
async def get_route_briefing(activity_id: uuid.UUID,plan_id: uuid.UUID | None=None,session_id: str | None=Query(None,max_length=80),user=Depends(safety_confirmed_user),db=Depends(get_db)):
    activity=await _owned_activity(activity_id,user,db)
    rows=await _series(db,user,activity)
    result=await asyncio.to_thread(route_briefing,rows)
    feedback=await db.scalar(select(ActivityFeedback).where(ActivityFeedback.activity_id==activity_id,ActivityFeedback.user_id==user.id))
    result['notes']=(feedback.data or {}).get('route_notes',[]) if feedback else []
    today=user_today(user)
    schedules=(await db.execute(select(PlanSchedule,AiRun).join(AiRun,AiRun.id==PlanSchedule.plan_run_id).where(PlanSchedule.user_id==user.id,AiRun.user_id==user.id).order_by(PlanSchedule.updated_at.desc()).limit(5))).all()
    options=[]
    for schedule,run in schedules:
        compared=await comparison_data(db,user,run,schedule)
        completed={s["id"] for s in compared["items"] if s["status"]=="matched"}
        for session in _sessions_for_schedule(run,schedule):
            if session['id'] not in completed and sport_family(session['sport'])==sport_family(activity.sport_type) and today.isoformat()<=session['date']<=(today+timedelta(days=30)).isoformat():
                options.append({**session,'plan_id':str(run.id),'session_id':session['id']})
    # Explicit selection is resolved in the bounded, user-owned upcoming list.
    chosen=next((s for s in options if s['plan_id']==str(plan_id) and s['id']==session_id),None)
    if plan_id and not chosen:
        raise HTTPException(404,'UPCOMING_SESSION_NOT_FOUND')
    result['plans']=[{k:s[k] for k in ('plan_id','session_id','name','date','duration_min')} for s in options]
    result['overlay']=route_plan_overlay(rows,chosen) if chosen else None
    return result


@router.post('/coach/plans/{run_id}/schedule-check')
async def check_schedule(run_id: uuid.UUID,payload: ScheduleIn,user=Depends(safety_confirmed_user),db=Depends(get_db)):
    run=await plan_owned(db,user,run_id)
    saved=await db.get(PlanSchedule,run_id)
    if (saved.revision if saved else 0)!=payload.revision:
        raise HTTPException(409,'SCHEDULE_CHANGED_RELOAD')
    if payload.start_date.weekday()!=0:
        raise HTTPException(422,'START_DATE_MUST_BE_MONDAY')
    overrides=validate_overrides(run,payload.overrides)
    await guard_exported(db,user,run,saved,payload.start_date,overrides)
    virtual=PlanSchedule(plan_run_id=run.id,user_id=user.id,start_date=payload.start_date,overrides=overrides,revision=payload.revision)
    sessions=scheduled_sessions(run,virtual)
    profile=await db.get(CoachProfile,user.id)
    profile_data=(profile.data or {}) if profile else {}
    other_rows=(await db.execute(select(PlanSchedule,AiRun).join(AiRun,AiRun.id==PlanSchedule.plan_run_id).where(PlanSchedule.user_id==user.id,AiRun.user_id==user.id,PlanSchedule.plan_run_id!=run_id))).all()
    others=[s for schedule,other in other_rows for s in _sessions_for_schedule(other,schedule)]
    exports=(await db.scalars(select(GarminWorkoutExport).where(GarminWorkoutExport.user_id==user.id,GarminWorkoutExport.status=='exported'))).all()
    other_exports=[e for e in exports if e.plan_run_id!=run_id and e.scheduled_date]
    conflicts=plan_conflicts(sessions,profile_data,other_exports,others)
    # Export dates also block alternatives if their source plan has been removed.
    blocked=others+[{'id':str(e.id),'date':e.scheduled_date.isoformat(),'sport':'other','name':''} for e in other_exports]
    locked={e.session_id for e in exports if e.plan_run_id==run_id}
    alternatives=alternative_days(sessions,profile_data,payload.start_date,run.metadata_json['structured_plan']['weeks'],today=user_today(user),other_sessions=blocked,locked=locked)
    for c in conflicts:
        c['alternatives']=alternatives.get(c.get('session_id'),[]) if c['type']!='longer_than_typical' else []
    return {'conflicts':conflicts,'alternatives':alternatives,'sessions':{s['id']:{'date':s['date'],'conflicts':[c for c in conflicts if c.get('session_id')==s['id'] or s['id'] in c.get('session_ids',[])]} for s in sessions},'revision':payload.revision,'read_only':True}
