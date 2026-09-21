from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User, UserPreference
from pengucoach.db.session import get_db

router = APIRouter(prefix="/settings", tags=["settings"])


class PrivacyIn(BaseModel):
    local_ai_only: bool
    cloud_health_ai_allowed: bool


@router.get("/privacy")
async def privacy(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await db.get(UserPreference, user.id)
    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
        await db.commit()
    return {
        "local_ai_only": pref.local_ai_only,
        "cloud_health_ai_allowed": pref.cloud_health_ai_allowed,
        "default": "Cloud AI access to health/training data is disabled until explicitly enabled by the user.",
    }


@router.put("/privacy")
async def update_privacy(payload: PrivacyIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await db.get(UserPreference, user.id)
    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.local_ai_only = payload.local_ai_only
    pref.cloud_health_ai_allowed = payload.cloud_health_ai_allowed
    await db.commit()
    return {"saved": True}
