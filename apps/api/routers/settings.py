from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.common.config import settings
from pengucoach.db.models import User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.coach.today import TODAY_CARDS, today_preferences
from pengucoach.common.dates import user_today
from pengucoach.health.steps import goal_config, step_goal_payload

router = APIRouter(prefix="/settings", tags=["settings"])

THEMES = {
    "light", "dark", "ocean", "forest", "lavender", "sand", "rose", "slate", "aurora",
    "alpine", "arctic", "espresso", "ember", "mono", "custom",
}
MAX_IMAGE_BYTES = 3 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class PrivacyIn(BaseModel):
    local_ai_only: bool
    cloud_health_ai_allowed: bool


class CustomThemeIn(BaseModel):
    mode: Literal["light", "dark"] = "light"
    background: str = Field(default="#f2f7f5", pattern=r"^#[0-9a-fA-F]{6}$")
    surface: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#287b6e", pattern=r"^#[0-9a-fA-F]{6}$")


class AppearanceIn(BaseModel):
    theme: str = Field(pattern=r"^(light|dark|ocean|forest|lavender|sand|rose|slate|aurora|alpine|arctic|espresso|ember|mono|custom)$")
    custom_theme: CustomThemeIn | None = None


class AiPreferencesIn(BaseModel):
    coach_chat: Literal["very_low", "low", "standard", "high"] = "standard"
    activity_analysis: Literal["very_low", "low", "standard", "high"] = "standard"
    training_plan: Literal["very_low", "low", "standard", "high"] = "standard"
    monthly_budget_eur: float | None = Field(default=None, ge=0, le=100000)


def _asset_root(user_id) -> Path:
    path = Path(settings.data_dir) / "user-assets" / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _asset_info(pref: UserPreference | None) -> dict:
    cfg = dict(pref.dashboard_config or {}) if pref else {}
    return {
        "theme": (pref.theme if pref and pref.theme in THEMES else "light"),
        "custom_theme": CustomThemeIn.model_validate(cfg.get("custom_theme") or {}).model_dump(),
        "has_avatar": bool(cfg.get("avatar_file")),
        "has_app_icon": bool(cfg.get("app_icon_file")),
        "avatar_version": cfg.get("avatar_version"),
        "app_icon_version": cfg.get("app_icon_version"),
    }


async def _pref(db: AsyncSession, user: User) -> UserPreference:
    pref = await db.get(UserPreference, user.id)
    if not pref:
        pref = UserPreference(user_id=user.id, theme="light", dashboard_config={})
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    elif pref.theme not in THEMES:
        # Older installs used "system". Alpha.7 intentionally defaults to the
        # current bright health theme unless the user explicitly chooses dark.
        pref.theme = "light"
        await db.commit()
    return pref


@router.get("/privacy")
async def privacy(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    return {
        "local_ai_only": pref.local_ai_only,
        "cloud_health_ai_allowed": pref.cloud_health_ai_allowed,
        "default": "Cloud AI access to health/training data is disabled until explicitly enabled by the user.",
    }


@router.put("/privacy")
async def update_privacy(payload: PrivacyIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    pref.local_ai_only = payload.local_ai_only
    pref.cloud_health_ai_allowed = payload.cloud_health_ai_allowed
    await db.commit()
    return {"saved": True}


@router.get("/ai-preferences")
async def ai_preferences(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    cfg = dict(pref.dashboard_config or {})
    profiles = cfg.get("ai_quality_profiles") if isinstance(cfg.get("ai_quality_profiles"), dict) else {}
    return {
        "coach_chat": profiles.get("coach_chat", "standard"),
        "activity_analysis": profiles.get("activity_analysis", "standard"),
        "training_plan": profiles.get("training_plan", "standard"),
        "monthly_budget_eur": cfg.get("ai_monthly_budget_eur"),
    }


@router.put("/ai-preferences")
async def update_ai_preferences(payload: AiPreferencesIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    cfg = dict(pref.dashboard_config or {})
    cfg["ai_quality_profiles"] = {
        "coach_chat": payload.coach_chat,
        "activity_analysis": payload.activity_analysis,
        "training_plan": payload.training_plan,
    }
    if payload.monthly_budget_eur is None:
        cfg.pop("ai_monthly_budget_eur", None)
    else:
        cfg["ai_monthly_budget_eur"] = payload.monthly_budget_eur
    pref.dashboard_config = cfg
    await db.commit()
    return {"saved": True, **payload.model_dump()}


@router.get("/appearance")
async def appearance(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    return _asset_info(pref)


@router.put("/appearance")
async def update_appearance(payload: AppearanceIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    await db.refresh(pref, with_for_update=True)
    pref.theme = payload.theme
    if payload.custom_theme is not None:
        pref.dashboard_config = {**(pref.dashboard_config or {}), "custom_theme": payload.custom_theme.model_dump()}
    await db.commit()
    return {"saved": True, **_asset_info(pref)}


@router.get("/update-status")
async def get_update_status(user: User = Depends(safety_confirmed_user)):
    from pengucoach.common.releases import update_status
    return await update_status(settings.resolved_app_version)


@router.get("/update-check")
async def check_update_now(user: User = Depends(safety_confirmed_user)):
    from pengucoach.common.releases import update_status
    return await update_status(settings.resolved_app_version, refresh=True)


@router.get("/changelog")
async def get_changelog(refresh: bool = Query(default=False), user: User = Depends(safety_confirmed_user)):
    from pengucoach.common.changelog import changelog
    return await changelog(refresh=refresh)


class StepGoalIn(BaseModel):
    daily_target: int = Field(ge=1000, le=50000, strict=True)
    adaptive: bool = False


@router.get("/step-goal")
async def get_step_goal(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await step_goal_payload(db, user)


@router.put("/step-goal")
async def save_step_goal(payload: StepGoalIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    await db.refresh(pref, with_for_update=True)
    cfg = dict(pref.dashboard_config or {})
    current = goal_config(pref)
    today = user_today(user).isoformat()
    history = current["history"]
    if not current["configured"] or current["daily_target"] != payload.daily_target:
        history = [item for item in history if item["from"] != today]
        history.append({"from": today, "target": payload.daily_target})
    cfg["step_goal"] = {"configured": True, **payload.model_dump(), "history": history}
    pref.dashboard_config = cfg
    await db.commit()
    return await step_goal_payload(db, user)


async def _save_image(kind: str, upload: UploadFile, user: User, db: AsyncSession) -> dict:
    content_type = (upload.content_type or "").lower()
    suffix = ALLOWED_IMAGE_TYPES.get(content_type)
    if not suffix:
        raise HTTPException(status_code=415, detail="IMAGE_TYPE_NOT_SUPPORTED")
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="IMAGE_TOO_LARGE")
    if not data:
        raise HTTPException(status_code=400, detail="EMPTY_IMAGE")

    pref = await _pref(db, user)
    cfg = dict(pref.dashboard_config or {})
    root = _asset_root(user.id)
    key = "avatar_file" if kind == "avatar" else "app_icon_file"
    version_key = "avatar_version" if kind == "avatar" else "app_icon_version"

    old = cfg.get(key)
    if old:
        try:
            (root / old).unlink(missing_ok=True)
        except OSError:
            pass

    filename = f"{kind}{suffix}"
    (root / filename).write_bytes(data)
    cfg[key] = filename
    cfg[version_key] = int(cfg.get(version_key) or 0) + 1
    pref.dashboard_config = cfg
    await db.commit()
    return {"saved": True, **_asset_info(pref)}


async def _serve_image(kind: str, user: User, db: AsyncSession):
    pref = await _pref(db, user)
    cfg = dict(pref.dashboard_config or {})
    key = "avatar_file" if kind == "avatar" else "app_icon_file"
    name = cfg.get(key)
    if not name:
        raise HTTPException(status_code=404, detail="IMAGE_NOT_SET")
    path = _asset_root(user.id) / Path(name).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="IMAGE_NOT_FOUND")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


async def _delete_image(kind: str, user: User, db: AsyncSession):
    pref = await _pref(db, user)
    cfg = dict(pref.dashboard_config or {})
    key = "avatar_file" if kind == "avatar" else "app_icon_file"
    version_key = "avatar_version" if kind == "avatar" else "app_icon_version"
    name = cfg.pop(key, None)
    cfg[version_key] = int(cfg.get(version_key) or 0) + 1
    if name:
        try:
            (_asset_root(user.id) / Path(name).name).unlink(missing_ok=True)
        except OSError:
            pass
    pref.dashboard_config = cfg
    await db.commit()
    return {"deleted": True, **_asset_info(pref)}


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _save_image("avatar", file, user, db)


@router.get("/avatar")
async def avatar(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _serve_image("avatar", user, db)


@router.delete("/avatar")
async def delete_avatar(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _delete_image("avatar", user, db)


@router.post("/app-icon")
async def upload_app_icon(file: UploadFile = File(...), user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _save_image("app-icon", file, user, db)


@router.get("/app-icon")
async def app_icon(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _serve_image("app-icon", user, db)


@router.delete("/app-icon")
async def delete_app_icon(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return await _delete_image("app-icon", user, db)


class TodaySettingsIn(BaseModel):
    order: list[Literal['preparation','weather','reflection','progress','load','metrics','trend','activities']] = Field(default_factory=lambda: list(TODAY_CARDS), max_length=8)
    hidden: list[Literal['preparation','weather','reflection','progress','load','metrics','trend','activities']] = Field(default_factory=list, max_length=8)
    pinned_metrics: list[Literal['steps','sleep','resting_hr','hrv','stress','hydration','body_battery_high','weight','body_fat','training_readiness','vo2max']] = Field(default_factory=lambda: ['steps','sleep','resting_hr','hrv','weight','stress'], min_length=1, max_length=11)
    preferred_start_hour: int = Field(default=7, ge=0, le=23)
    preferred_end_hour: int = Field(default=21, ge=1, le=24)

    @model_validator(mode='after')
    def validate_layout(self):
        if self.preferred_end_hour <= self.preferred_start_hour:
            raise ValueError('TIME_WINDOW_END_MUST_FOLLOW_START')
        for values in [self.order, self.hidden, self.pinned_metrics]:
            if len(values) != len(set(values)):
                raise ValueError('DUPLICATE_TODAY_ITEMS')
        self.order += [k for k in TODAY_CARDS if k not in self.order]
        return self


@router.get('/today')
async def get_today_settings(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return today_preferences(await db.get(UserPreference, user.id))


@router.put('/today')
async def save_today_settings(payload: TodaySettingsIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    pref.dashboard_config = {**(pref.dashboard_config or {}), 'today': payload.model_dump()}
    await db.commit()
    return today_preferences(pref)
