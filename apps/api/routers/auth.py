from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import current_user
from pengucoach.auth.jwt import create_safety_token, create_session_token, valid_safety_token
from pengucoach.auth.passwords import verify_password
from pengucoach.common.config import settings
from pengucoach.db.models import SafetyAcceptance, User
from pengucoach.db.session import get_db
from pengucoach.safety.notice import NOTICE_VERSION

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class NoticeAcceptRequest(BaseModel):
    version: str = Field(pattern=r"^health-notice-[0-9]+\.[0-9]+$")
    locale: str = Field(pattern=r"^(de-DE|en-US)$")


@router.post("/login")
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == payload.username.strip()))
    if not user or user.status != "active" or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_CREDENTIALS")
    user.last_login_at = datetime.now(timezone.utc)
    token = create_session_token(str(user.id))
    response.set_cookie(
        key="pengucoach_session",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/",
    )
    await db.commit()
    response.delete_cookie("pengucoach_safety", path="/")
    return {
        "authenticated": True,
        "user": {"id": str(user.id), "username": user.username, "role": user.role, "locale": user.locale},
        "safety_required": True,
        "notice_version": NOTICE_VERSION,
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("pengucoach_session", path="/")
    response.delete_cookie("pengucoach_safety", path="/")
    return {"authenticated": False}


@router.get("/me")
async def me(
    user: User = Depends(current_user),
    pengucoach_safety: str | None = Cookie(default=None),
):
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "locale": user.locale,
        "safety_required": not valid_safety_token(pengucoach_safety, str(user.id)),
        "notice_version": NOTICE_VERSION,
    }


@router.get("/safety-notice")
async def safety_notice(user: User = Depends(current_user)):
    from pengucoach.safety.notice import NOTICE
    return {"version": NOTICE_VERSION, "content": NOTICE, "preferred_locale": user.locale}


@router.post("/safety-notice/accept")
async def accept_notice(
    payload: NoticeAcceptRequest,
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.version != NOTICE_VERSION:
        raise HTTPException(status_code=409, detail="NOTICE_VERSION_MISMATCH")
    # Every new login requires a new confirmation. Keep an audit history instead
    # of using historical acceptance to skip the gate.
    db.add(
        SafetyAcceptance(
            user_id=user.id,
            notice_version=payload.version,
            locale=payload.locale,
            application_version=settings.app_version,
        )
    )
    await db.commit()
    response.set_cookie(
        key="pengucoach_safety",
        value=create_safety_token(str(user.id)),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/",
    )
    return {"accepted": True, "version": payload.version}
