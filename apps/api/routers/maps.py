"""Personal, encrypted credentials for optional activity panoramas.

No provider is contacted here. Credentials are released to the owner's browser
only after an explicit per-view consent, never through the settings GET.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.settings import _pref
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.db.models import User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.security.crypto import SecretBox

router = APIRouter(prefix="/settings/maps", tags=["maps"])
Provider = Literal["google", "apple"]
FIELDS = {"google": "google_key_ciphertext", "apple": "apple_token_ciphertext"}


class MapSettingsIn(BaseModel):
    map_enabled: bool = True
    preferred_provider: Provider = "google"
    google_api_key: SecretStr | None = None
    apple_maps_token: SecretStr | None = None


class PanoramaConsentIn(BaseModel):
    provider: Provider
    confirmed: bool = False


def _config(pref: UserPreference) -> dict:
    value = (pref.dashboard_config or {}).get("activity_maps")
    return dict(value) if isinstance(value, dict) else {}


def _public(config: dict) -> dict:
    return {
        "map_enabled": bool(config.get("map_enabled", True)),
        "preferred_provider": config.get("preferred_provider", "google"),
        "google_configured": bool(config.get(FIELDS["google"])),
        "apple_configured": bool(config.get(FIELDS["apple"])),
    }


def _store(pref: UserPreference, config: dict) -> None:
    pref.dashboard_config = {**(pref.dashboard_config or {}), "activity_maps": config}


def _secret_box() -> SecretBox:
    try:
        return SecretBox()
    except (RuntimeError, ValueError):
        raise HTTPException(status_code=503, detail="MAP_SECRET_STORAGE_UNAVAILABLE") from None


@router.get("")
async def map_settings(user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    return JSONResponse(_public(_config(await _pref(db, user))), headers={"Cache-Control": "no-store"})


@router.put("")
async def save_map_settings(payload: MapSettingsIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    # Validate everything before changing either credential; omitted/null means
    # preserve it. An explicit empty string deletes it, without requiring crypto.
    updates = {}
    for provider, secret, maximum in (
        ("google", payload.google_api_key, 256),
        ("apple", payload.apple_maps_token, 8192),
    ):
        if secret is None:
            continue
        value = secret.get_secret_value().strip()
        if len(value) > maximum or any(c.isspace() for c in value):
            raise HTTPException(status_code=422, detail="INVALID_MAP_CREDENTIAL")
        updates[FIELDS[provider]] = _secret_box().encrypt(value) if value else None
    pref = await _pref(db, user)
    config = _config(pref)
    config.update(map_enabled=payload.map_enabled, preferred_provider=payload.preferred_provider)
    for key, value in updates.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    _store(pref, config)
    await db.commit()
    return JSONResponse(_public(config), headers={"Cache-Control": "no-store"})


@router.delete("/credentials/{provider}")
async def delete_map_credential(provider: Provider, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    pref = await _pref(db, user)
    config = _config(pref)
    config.pop(FIELDS[provider], None)
    _store(pref, config)
    await db.commit()
    return JSONResponse(_public(config), headers={"Cache-Control": "no-store"})


@router.post("/panorama-access")
async def panorama_access(payload: PanoramaConsentIn, user: User = Depends(safety_confirmed_user), db: AsyncSession = Depends(get_db)):
    if not payload.confirmed:
        raise HTTPException(status_code=403, detail="PANORAMA_CONSENT_REQUIRED")
    pref = await _pref(db, user)
    ciphertext = _config(pref).get(FIELDS[payload.provider])
    if not ciphertext:
        raise HTTPException(status_code=409, detail="MAP_CREDENTIAL_NOT_CONFIGURED")
    try:
        credential = _secret_box().decrypt(ciphertext)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="MAP_CREDENTIAL_UNREADABLE") from None
    return JSONResponse({"provider": payload.provider, "credential": credential}, headers={
        "Cache-Control": "no-store, private", "Pragma": "no-cache", "Vary": "Cookie",
    })
