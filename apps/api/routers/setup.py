from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.passwords import hash_password
from pengucoach.db.models import User, UserPreference
from pengucoach.db.session import get_db

router = APIRouter(prefix="/setup", tags=["setup"])


class AdminSetup(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    locale: str = Field(default="de-DE", pattern=r"^(de-DE|en-US)$")


@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    count = await db.scalar(select(func.count()).select_from(User))
    return {"setup_required": not bool(count)}


@router.post("/admin", status_code=status.HTTP_201_CREATED)
async def create_first_admin(payload: AdminSetup, db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count()).select_from(User))
    if count:
        raise HTTPException(status_code=409, detail="SETUP_ALREADY_COMPLETED")
    user = User(username=payload.username.strip(), email=str(payload.email).lower(), password_hash=hash_password(payload.password), role="admin", status="active", locale=payload.locale)
    db.add(user); await db.flush(); db.add(UserPreference(user_id=user.id))
    await db.commit()
    return {"created": True, "user_id": str(user.id)}
