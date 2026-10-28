import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import admin_user
from pengucoach.auth.passwords import hash_password
from pengucoach.db.models import GarminConnection, User, UserPreference
from pengucoach.db.session import get_db

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    locale: str = Field(default="de-DE", pattern=r"^(de-DE|en-US)$")
    role: str = Field(default="user", pattern=r"^(user|admin)$")


@router.get("")
async def list_users(_: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(User).order_by(User.username))).all(); result=[]
    for x in rows:
        conn = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == x.id))
        result.append({"id": str(x.id), "username": x.username, "email": x.email, "role": x.role, "status": x.status, "locale": x.locale, "last_login_at": x.last_login_at, "garmin": conn.status if conn else "disconnected"})
    return result


@router.post("")
async def create_user(payload: UserIn, _: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    exists = await db.scalar(select(User.id).where((User.username == payload.username) | (User.email == str(payload.email).lower())))
    if exists: raise HTTPException(status_code=409, detail="USER_EXISTS")
    row = User(username=payload.username, email=str(payload.email).lower(), password_hash=hash_password(payload.password), locale=payload.locale, role=payload.role)
    db.add(row); await db.flush(); db.add(UserPreference(user_id=row.id)); await db.commit(); return {"id": str(row.id)}
