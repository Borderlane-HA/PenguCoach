import json
import uuid

import httpx
import pandas as pd
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.main import app
from apps.api.routers import maps
from pengucoach.auth.dependencies import safety_confirmed_user
from pengucoach.common.config import settings
from pengucoach.db.models import User, UserPreference
from pengucoach.db.session import get_db
from pengucoach.fit.activity_detail import serialize_series
from pengucoach.imports.manual_activity import parse_gpx_bytes


@compiles(JSONB, "sqlite")
def compile_json(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
async def data(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: User.__table__.create(sync))
        await connection.run_sync(lambda sync: UserPreference.__table__.create(sync))
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        users = [User(id=uuid.uuid4(), username=name, email=f"{name}@example.test", password_hash="x") for name in ("first", "second")]
        db.add_all(users)
        await db.commit()
        yield db, *users
    await engine.dispose()


def body(response):
    return json.loads(response.body)


async def test_keys_are_encrypted_owned_masked_and_preserved(data):
    db, first, second = data
    saved = await maps.save_map_settings(maps.MapSettingsIn(google_api_key="my-google-key", apple_maps_token="my-apple-token"), first, db)
    assert body(saved)["google_configured"] and body(saved)["apple_configured"]
    pref = await db.get(UserPreference, first.id)
    raw = json.dumps(pref.dashboard_config)
    assert "my-google-key" not in raw and "my-apple-token" not in raw
    assert "my-google-key" not in saved.body.decode()
    config = body(await maps.map_settings(second, db))
    assert not config["google_configured"] and not config["apple_configured"]
    with pytest.raises(HTTPException) as error:
        await maps.panorama_access(maps.PanoramaConsentIn(provider="google", confirmed=True), second, db)
    assert error.value.status_code == 409
    before = dict(pref.dashboard_config["activity_maps"])
    await maps.save_map_settings(maps.MapSettingsIn(map_enabled=False, preferred_provider="apple"), first, db)
    assert pref.dashboard_config["activity_maps"]["google_key_ciphertext"] == before["google_key_ciphertext"]
    assert not pref.dashboard_config["activity_maps"]["map_enabled"]
    await maps.save_map_settings(maps.MapSettingsIn(google_api_key="replacement"), first, db)
    access = await maps.panorama_access(maps.PanoramaConsentIn(provider="google", confirmed=True), first, db)
    assert body(access)["credential"] == "replacement"
    assert body(await maps.panorama_access(maps.PanoramaConsentIn(provider="apple", confirmed=True), first, db))["credential"] == "my-apple-token"


async def test_consent_is_required_and_plaintext_is_never_cacheable(data):
    db, user, _ = data
    await maps.save_map_settings(maps.MapSettingsIn(google_api_key="private-browser-key"), user, db)
    with pytest.raises(HTTPException) as error:
        await maps.panorama_access(maps.PanoramaConsentIn(provider="google"), user, db)
    assert error.value.status_code == 403
    response = await maps.panorama_access(maps.PanoramaConsentIn(provider="google", confirmed=True), user, db)
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["vary"] == "Cookie"
    assert "no-store" in (await maps.map_settings(user, db)).headers["cache-control"]
    assert "private-browser-key" not in repr(maps.MapSettingsIn(google_api_key="private-browser-key"))


async def test_invalid_and_unreadable_credentials_do_not_destroy_existing_settings(data, monkeypatch):
    db, user, _ = data
    await maps.save_map_settings(maps.MapSettingsIn(google_api_key="saved", apple_maps_token="saved-token"), user, db)
    with pytest.raises(HTTPException):
        await maps.save_map_settings(maps.MapSettingsIn(google_api_key="replacement", apple_maps_token="invalid token"), user, db)
    assert body(await maps.panorama_access(maps.PanoramaConsentIn(provider="google", confirmed=True), user, db))["credential"] == "saved"
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    with pytest.raises(HTTPException) as error:
        await maps.panorama_access(maps.PanoramaConsentIn(provider="google", confirmed=True), user, db)
    assert error.value.detail == "MAP_CREDENTIAL_UNREADABLE"
    monkeypatch.setattr(settings, "encryption_key", "")
    with pytest.raises(HTTPException) as error:
        await maps.save_map_settings(maps.MapSettingsIn(google_api_key="new"), user, db)
    assert error.value.detail == "MAP_SECRET_STORAGE_UNAVAILABLE"
    assert not body(await maps.delete_map_credential("google", user, db))["google_configured"]
    assert body(await maps.map_settings(user, db))["apple_configured"]
    assert not body(await maps.save_map_settings(maps.MapSettingsIn(apple_maps_token=""), user, db))["apple_configured"]


async def test_real_http_routes_require_auth_and_isolate_users(data):
    db, first, second = data
    current = [first]
    async def user(): return current[0]
    async def database(): yield db
    app.dependency_overrides[safety_confirmed_user] = user
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = await client.put("/api/v1/settings/maps", json={"google_api_key": "first-key"})
            assert result.status_code == 200 and "first-key" not in result.text
            denied = await client.post("/api/v1/settings/maps/panorama-access", json={"provider": "google"})
            assert denied.status_code == 403
            current[0] = second
            denied = await client.post("/api/v1/settings/maps/panorama-access", json={"provider": "google", "confirmed": True})
            assert denied.status_code == 409
            assert (await client.delete("/api/v1/settings/maps/credentials/google")).status_code == 200
            current[0] = first
            result = await client.post("/api/v1/settings/maps/panorama-access", json={"provider": "google", "confirmed": True})
            assert result.json()["credential"] == "first-key"
            assert (await client.post("/api/v1/settings/maps/panorama-access", json={"provider": "unknown", "confirmed": True})).status_code == 422
    finally:
        app.dependency_overrides.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/settings/maps")).status_code in (401, 403)


def test_gpx_without_time_has_real_distance_but_no_invented_time_or_speed():
    frame, *_ = parse_gpx_bytes(b'<gpx><trk><trkseg><trkpt lat="48" lon="11"><ele>400</ele></trkpt><trkpt lat="48.001" lon="11"><ele>410</ele></trkpt><trkpt lat="48.002" lon="11"><ele>420</ele></trkpt></trkseg></trk></gpx>')
    rows = serialize_series(frame)
    assert rows[-1]["distance_km"] > .2
    assert all(row["elapsed_s"] is None for row in rows)
    assert all(row["speed_kmh"] is None for row in rows)
    assert all("heart_rate" not in row and "power" not in row for row in rows)


def test_gpx_segments_and_missing_measurements_survive_serialization():
    frame, *_ = parse_gpx_bytes(b'<gpx><trk><trkseg><trkpt lat="48" lon="11"><time>2026-10-10T10:00:00Z</time><extensions><hr>150</hr><power>0</power></extensions></trkpt><trkpt lat="48.001" lon="11"><time>2026-10-10T10:00:10Z</time></trkpt></trkseg><trkseg><trkpt lat="49" lon="12"><time>2026-10-10T11:00:00Z</time></trkpt></trkseg></trk></gpx>')
    rows = serialize_series(frame)
    assert [row["track_segment"] for row in rows] == [0, 0, 1]
    assert rows[0]["heart_rate"] == 150 and rows[0]["power"] == 0
    assert rows[1]["heart_rate"] is None and rows[1]["power"] is None
    assert rows[2]["distance"] == rows[1]["distance"]
    assert rows[2]["speed_kmh"] is None
    sparse = serialize_series(pd.DataFrame({"distance": [0, 10, 20, 30], "altitude": [400, 401, None, 402]}))
    assert sparse[2]["altitude_m"] is None and sparse[2]["grade_pct"] is None
