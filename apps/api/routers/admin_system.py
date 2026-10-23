"""Admin-only bridge to the host's independent maintenance service."""
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from pengucoach.auth.dependencies import admin_user
from pengucoach.db.models import User
from pengucoach.maintenance import client
from pengucoach.maintenance.engine import identifier

router = APIRouter(prefix='/admin/system',tags=['admin-system'])
MAX_CHUNK = 8*1024**2


class JobIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['update','backup','inspect','restore','export','recover']
    password: str = Field(default='',max_length=1024)
    backup_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    confirmation: str = Field(default='',max_length=20)


class UploadIn(BaseModel):
    size: int = Field(gt=0,le=100*1024**3,strict=True)


async def proxy(method,path,**kwargs):
    try:return await client.request(method,path,**kwargs)
    except httpx.HTTPStatusError as exc:
        try:detail = exc.response.json().get('detail','MAINTENANCE_FAILED')
        except ValueError:detail = 'MAINTENANCE_FAILED'
        raise HTTPException(exc.response.status_code,detail) from None
    except httpx.HTTPError:
        raise HTTPException(503,'MAINTENANCE_AGENT_UNAVAILABLE') from None


@router.get('/status')
async def status(_:User=Depends(admin_user)):
    try:return await proxy('GET','/status')
    except HTTPException as exc:
        if exc.status_code == 503:return {'available':False,'jobs':[],'backups':[],
                                         'reason':'MAINTENANCE_AGENT_UNAVAILABLE','setup':client.setup_status()}
        raise


@router.get('/update')
async def update_preview(refresh:bool=Query(default=False),_:User=Depends(admin_user)):
    # The host agent resolves the newest eligible release tag; no request data reaches Git.
    return await proxy('GET','/update?refresh=1' if refresh else '/update',timeout=25)


@router.post('/jobs',status_code=202)
async def start_job(payload:JobIn,user:User=Depends(admin_user)):
    # Running background work is drained by the host agent (maintenance mode), which
    # sees every Celery task instead of only database-tracked AI jobs.
    return await proxy('POST','/jobs',json={**payload.model_dump(),'actor':str(user.id)})


@router.post('/uploads',status_code=201)
async def begin_upload(payload:UploadIn,_:User=Depends(admin_user)):
    return await proxy('POST','/uploads',json=payload.model_dump())


@router.get('/uploads/{upload_id}')
async def upload_status(upload_id:str,_:User=Depends(admin_user)):
    try:identifier(upload_id)
    except ValueError:raise HTTPException(400,'INVALID_ID') from None
    return await proxy('GET',f'/uploads/{upload_id}')


@router.post('/uploads/{upload_id}')
async def upload_chunk(upload_id:str,request:Request,offset:int=Query(ge=0),_:User=Depends(admin_user)):
    try:identifier(upload_id)
    except ValueError:raise HTTPException(400,'INVALID_ID') from None
    data = bytearray()
    async for block in request.stream():
        data.extend(block)
        if len(data)>MAX_CHUNK:raise HTTPException(413,'UPLOAD_CHUNK_TOO_LARGE')
    return await proxy('POST',f'/uploads/{upload_id}?offset={offset}',content=bytes(data))


@router.post('/uploads/{upload_id}/complete')
async def finish_upload(upload_id:str,_:User=Depends(admin_user)):
    try:identifier(upload_id)
    except ValueError:raise HTTPException(400,'INVALID_ID') from None
    return await proxy('POST',f'/uploads/{upload_id}/complete',json={})


@router.get('/backups/{backup_id}/download')
async def download(backup_id:str,_:User=Depends(admin_user)):
    try:identifier(backup_id)
    except ValueError:raise HTTPException(400,'INVALID_ID') from None
    connection = client.client()
    try:
        response = await connection.send(connection.build_request('GET',f'/backups/{backup_id}/download'),stream=True)
        response.raise_for_status()
    except httpx.HTTPError:
        await connection.aclose()
        raise HTTPException(503,'BACKUP_DOWNLOAD_UNAVAILABLE') from None
    async def blocks():
        try:
            async for block in response.aiter_bytes():yield block
        finally:await response.aclose();await connection.aclose()
    return StreamingResponse(blocks(),media_type='application/octet-stream',headers={
        'Content-Disposition':f'attachment; filename="PenguCoach-{backup_id}.pcbackup"',
        'Content-Length':response.headers['Content-Length'],'Cache-Control':'no-store'})


@router.delete('/backups/{backup_id}')
async def delete_backup(backup_id:str,confirmation:Literal['DELETE']=Query(),_:User=Depends(admin_user)):
    try:identifier(backup_id)
    except ValueError:raise HTTPException(400,'INVALID_ID') from None
    return await proxy('DELETE',f'/backups/{backup_id}',json={'confirmation':confirmation})
