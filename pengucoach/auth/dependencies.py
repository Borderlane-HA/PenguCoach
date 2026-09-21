import uuid

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.jwt import decode_session_token, valid_safety_token
from pengucoach.db.models import User
from pengucoach.db.session import get_db


async def current_user(pengucoach_session: str | None = Cookie(default=None), db: AsyncSession = Depends(get_db)) -> User:
    if not pengucoach_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="NOT_AUTHENTICATED")
    try:
        user_id = uuid.UUID(decode_session_token(pengucoach_session))
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_SESSION") from exc
    user = await db.get(User, user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_SESSION")
    return user


async def safety_confirmed_user(user: User = Depends(current_user), pengucoach_safety: str | None = Cookie(default=None)) -> User:
    if not valid_safety_token(pengucoach_safety, str(user.id)):
        raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED, detail="SAFETY_NOTICE_REQUIRED")
    return user


async def admin_user(user: User = Depends(safety_confirmed_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN_REQUIRED")
    return user
