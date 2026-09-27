from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.weather.service import fetch_forecast, search_locations, weather_config

router = APIRouter(prefix="/weather", tags=["weather"])


class WeatherSettingsIn(BaseModel):
    enabled: bool = False
    location_name: str = Field(default="", max_length=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str = Field(default="auto", max_length=80)
    country_code: str = Field(default="", max_length=8)
    admin1: str = Field(default="", max_length=120)
    include_in_training_plans: bool = True


def _public(config: dict) -> dict:
    return {**config, "provider": "Open-Meteo", "api_key_required": False, "forecast_days": 16}


@router.get("/settings")
async def get_weather_settings(
    user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)
):
    return _public(weather_config(await db.get(UserPreference, user.id)))


@router.put("/settings")
async def put_weather_settings(
    payload: WeatherSettingsIn,
    user: User = Depends(safety_confirmed_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.enabled and (payload.latitude is None or payload.longitude is None or not payload.location_name.strip()):
        raise HTTPException(status_code=400, detail="WEATHER_LOCATION_REQUIRED")
    pref = await db.get(UserPreference, user.id)
    if not pref:
        pref = UserPreference(user_id=user.id, theme="light", dashboard_config={})
        db.add(pref)
        await db.flush()
    cfg = dict(pref.dashboard_config or {})
    cfg["weather"] = payload.model_dump()
    pref.dashboard_config = cfg
    await db.commit()
    return _public(weather_config(pref))


@router.get("/locations")
async def locations(
    query: str = Query(min_length=2, max_length=120),
    language: str = Query(default="de", pattern=r"^[a-zA-Z-]{2,12}$"),
    _: User = Depends(safety_confirmed_user),
):
    try:
        return {"results": await search_locations(query, language)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="WEATHER_GEOCODING_UNAVAILABLE") from exc


@router.get("/forecast")
async def forecast(
    user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)
):
    config = weather_config(await db.get(UserPreference, user.id))
    if not config.get("enabled") or config.get("latitude") is None or config.get("longitude") is None:
        raise HTTPException(status_code=409, detail="WEATHER_NOT_CONFIGURED")
    try:
        data = await fetch_forecast(
            float(config["latitude"]), float(config["longitude"]), str(config.get("timezone") or "auto"), 16
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="WEATHER_FORECAST_UNAVAILABLE") from exc
    return {**data, "location": config.get("location_name") or ""}
