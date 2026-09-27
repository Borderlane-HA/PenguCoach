from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import SourceRecord, User, WithingsConnection
from pengucoach.db.session import get_db
from pengucoach.security.crypto import SecretBox
from pengucoach.withings.client import WithingsApiClient, WithingsError, WithingsOAuthClient, authorization_url
from pengucoach.withings.sync import delete_local_withings_data
from worker.tasks.withings_sync import sync_user as sync_withings_user

router = APIRouter(prefix="/withings", tags=["withings"])


class OAuthStartRequest(BaseModel):
    client_id: str = Field(min_length=3, max_length=255)
    client_secret: str = Field(min_length=8, max_length=4096)
    redirect_uri: str = Field(min_length=12, max_length=2048)
    sync_days: int = Field(default=365, ge=0, le=36525)
    auto_sync_enabled: bool = True
    sync_interval_minutes: int = Field(default=60, ge=15, le=1440)
    sync_body: bool = True
    sync_daily_activity: bool = True
    sync_sleep: bool = True


class SettingsRequest(BaseModel):
    sync_days: int = Field(default=365, ge=0, le=36525)
    auto_sync_enabled: bool = True
    sync_interval_minutes: int = Field(default=60, ge=15, le=1440)
    sync_body: bool = True
    sync_daily_activity: bool = True
    sync_sleep: bool = True


async def _connection(db: AsyncSession, user_id) -> WithingsConnection | None:
    return await db.scalar(select(WithingsConnection).where(WithingsConnection.user_id == user_id))


def _settings(conn: WithingsConnection | None) -> dict:
    return {
        "sync_days": conn.sync_days if conn else 365,
        "auto_sync_enabled": conn.auto_sync_enabled if conn else True,
        "sync_interval_minutes": conn.sync_interval_minutes if conn else 60,
        "sync_body": conn.sync_body if conn else True,
        "sync_daily_activity": conn.sync_daily_activity if conn else True,
        "sync_sleep": conn.sync_sleep if conn else True,
    }


@router.get("/status")
async def status(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await _connection(db, user.id)
    counts = dict((await db.execute(select(SourceRecord.domain, func.count(SourceRecord.id)).where(
        SourceRecord.user_id == user.id,
        SourceRecord.source == "withings",
    ).group_by(SourceRecord.domain))).all())
    range_rows = (await db.execute(select(
        SourceRecord.domain, func.min(SourceRecord.record_date), func.max(SourceRecord.record_date)
    ).where(
        SourceRecord.user_id == user.id, SourceRecord.source == "withings"
    ).group_by(SourceRecord.domain))).all()
    ranges = {domain: {
        "oldest": oldest.isoformat() if oldest else None,
        "newest": newest.isoformat() if newest else None,
    } for domain, oldest, newest in range_rows}
    if not conn:
        return {
            "connected": False, "status": "disconnected", "read_only": True,
            "counts": counts, "ranges": ranges, "settings": _settings(None),
        }
    return {
        "connected": conn.status == "connected" and bool(conn.refresh_token_ciphertext),
        "status": conn.status,
        "read_only": True,
        "client_id": conn.client_id,
        "redirect_uri": conn.redirect_uri,
        "withings_user_id": conn.withings_user_id,
        "scope": conn.scope,
        "counts": counts,
        "ranges": ranges,
        "last_validated_at": conn.last_validated_at,
        "last_successful_sync_at": conn.last_successful_sync_at,
        "next_sync_at": conn.next_sync_at,
        "last_error_code": conn.last_error_code,
        "last_sync_summary": conn.last_sync_summary or {},
        "settings": _settings(conn),
    }


@router.post("/oauth/start")
async def oauth_start(payload: OAuthStartRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    if not payload.redirect_uri.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="WITHINGS_REDIRECT_URI_INVALID")
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn = await _connection(db, user.id)
    if not conn:
        conn = WithingsConnection(
            user_id=user.id,
            client_id=payload.client_id.strip(),
            client_secret_ciphertext=SecretBox().encrypt(payload.client_secret),
            redirect_uri=payload.redirect_uri.strip(),
        )
        db.add(conn)
    else:
        conn.client_id = payload.client_id.strip()
        conn.client_secret_ciphertext = SecretBox().encrypt(payload.client_secret)
        conn.redirect_uri = payload.redirect_uri.strip()
    conn.status = "authorizing"
    conn.oauth_state = state
    conn.oauth_state_created_at = now
    conn.sync_days = payload.sync_days
    conn.auto_sync_enabled = payload.auto_sync_enabled
    conn.sync_interval_minutes = payload.sync_interval_minutes
    conn.sync_body = payload.sync_body
    conn.sync_daily_activity = payload.sync_daily_activity
    conn.sync_sleep = payload.sync_sleep
    conn.last_error_code = None
    await db.commit()
    return {
        "authorization_url": authorization_url(conn.client_id, conn.redirect_uri, state),
        "redirect_uri": conn.redirect_uri,
        "scopes": ["user.info", "user.metrics", "user.activity"],
    }


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not state:
        return RedirectResponse(url="/settings/withings?error=WITHINGS_OAUTH_STATE_MISSING", status_code=303)
    conn = await db.scalar(select(WithingsConnection).where(WithingsConnection.oauth_state == state))
    if not conn:
        return RedirectResponse(url="/settings/withings?error=WITHINGS_OAUTH_STATE_INVALID", status_code=303)
    now = datetime.now(timezone.utc)
    if not conn.oauth_state_created_at or conn.oauth_state_created_at < now - timedelta(minutes=15):
        conn.oauth_state = None
        conn.oauth_state_created_at = None
        conn.status = "error"
        conn.last_error_code = "WITHINGS_OAUTH_STATE_EXPIRED"
        await db.commit()
        return RedirectResponse(url="/settings/withings?error=WITHINGS_OAUTH_STATE_EXPIRED", status_code=303)
    if error or not code:
        conn.status = "error"
        conn.last_error_code = f"WITHINGS_OAUTH_{(error or 'CODE_MISSING').upper()}"
        conn.oauth_state = None
        conn.oauth_state_created_at = None
        await db.commit()
        return RedirectResponse(url=f"/settings/withings?error={quote(conn.last_error_code)}", status_code=303)
    try:
        oauth = WithingsOAuthClient(
            conn.client_id,
            SecretBox().decrypt(conn.client_secret_ciphertext),
            conn.redirect_uri,
        )
        tokens = await oauth.exchange_code(code)
        box = SecretBox()
        conn.withings_user_id = tokens.userid
        conn.access_token_ciphertext = box.encrypt(tokens.access_token)
        conn.refresh_token_ciphertext = box.encrypt(tokens.refresh_token)
        conn.token_expires_at = now + timedelta(seconds=tokens.expires_in)
        conn.scope = tokens.scope
        conn.status = "connected"
        conn.last_validated_at = now
        conn.last_error_code = None
        conn.last_error_at = None
        conn.oauth_state = None
        conn.oauth_state_created_at = None
        conn.next_sync_at = now + timedelta(minutes=conn.sync_interval_minutes) if conn.auto_sync_enabled else None
        await db.commit()
        return RedirectResponse(url="/settings/withings?connected=1", status_code=303)
    except Exception as exc:
        conn.status = "error"
        conn.last_error_code = exc.code if isinstance(exc, WithingsError) else type(exc).__name__
        conn.last_error_at = now
        conn.oauth_state = None
        conn.oauth_state_created_at = None
        await db.commit()
        return RedirectResponse(url=f"/settings/withings?error={quote(conn.last_error_code)}", status_code=303)


@router.post("/test")
async def test_connection(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await _connection(db, user.id)
    if not conn or not conn.access_token_ciphertext:
        raise HTTPException(status_code=409, detail="WITHINGS_NOT_CONNECTED")
    try:
        # A full sync will refresh tokens when needed. For the lightweight test,
        # refresh proactively if the current token is near expiry.
        now = datetime.now(timezone.utc)
        box = SecretBox()
        if not conn.token_expires_at or conn.token_expires_at <= now + timedelta(minutes=5):
            oauth = WithingsOAuthClient(conn.client_id, box.decrypt(conn.client_secret_ciphertext), conn.redirect_uri)
            tokens = await oauth.refresh(box.decrypt(conn.refresh_token_ciphertext))
            conn.access_token_ciphertext = box.encrypt(tokens.access_token)
            conn.refresh_token_ciphertext = box.encrypt(tokens.refresh_token)
            conn.token_expires_at = now + timedelta(seconds=tokens.expires_in)
            conn.scope = tokens.scope
            conn.withings_user_id = tokens.userid
        client = WithingsApiClient(box.decrypt(conn.access_token_ciphertext))
        await client.user()
        conn.status = "connected"
        conn.last_validated_at = now
        conn.last_error_code = None
        conn.last_error_at = None
        await db.commit()
        return {"ok": True, "scope": conn.scope, "withings_user_id": conn.withings_user_id}
    except Exception as exc:
        conn.last_error_code = exc.code if isinstance(exc, WithingsError) else type(exc).__name__
        conn.last_error_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=400, detail=conn.last_error_code) from exc


@router.put("/settings")
async def update_settings(payload: SettingsRequest, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await _connection(db, user.id)
    if not conn:
        raise HTTPException(status_code=409, detail="WITHINGS_NOT_CONNECTED")
    prior_enabled = conn.auto_sync_enabled
    prior_interval = conn.sync_interval_minutes
    for field, value in payload.model_dump().items():
        setattr(conn, field, value)
    if not conn.auto_sync_enabled:
        conn.next_sync_at = None
    elif not prior_enabled or prior_interval != conn.sync_interval_minutes or conn.next_sync_at is None:
        conn.next_sync_at = datetime.now(timezone.utc) + timedelta(minutes=conn.sync_interval_minutes)
    await db.commit()
    return payload.model_dump()


@router.post("/sync/now")
async def sync_now(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await _connection(db, user.id)
    if not conn or conn.status != "connected":
        raise HTTPException(status_code=409, detail="WITHINGS_NOT_CONNECTED")
    task = sync_withings_user.apply_async(args=[str(user.id)], queue="maintenance")
    return {"queued": True, "task_id": task.id}


@router.post("/disconnect")
async def disconnect(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    conn = await _connection(db, user.id)
    if conn:
        await db.delete(conn)
        await db.commit()
    return {"disconnected": True, "local_data_preserved": True}


@router.delete("/local-data")
async def delete_local_data(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    result = await delete_local_withings_data(db, user.id)
    return {"deleted": True, "connection_preserved": True, "remote_untouched": True, **result}
