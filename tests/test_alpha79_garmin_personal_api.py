"""alpha.79: Garmin Personal API key as an alternative to the password login."""
import asyncio
import base64
import json
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

from pengucoach.db.models import GarminConnection, GarminSyncSetting
from pengucoach.garmin import personal_api as P
from pengucoach.garmin.gateway import factory
from pengucoach.security import crypto

ROOT = Path(__file__).resolve().parents[1]


def jwt(exp: float) -> str:
    def enc(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc({'exp': exp})}.sig"


class Resp:
    def __init__(self, status=200, body=b"", json_body=None):
        self.status_code = status
        self.content = json.dumps(json_body).encode() if json_body is not None else body
        self.text = self.content.decode(errors="ignore")

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return json.loads(self.content)


class FakeHttp:
    def __init__(self, routes=None, token_status=200, now=1_000_000.0):
        self.routes = routes or {}
        self.token_status = token_status
        self.now = now
        self.posts = []
        self.gets = []
        self.reject_bearer_once = False

    def post(self, url, headers=None, timeout=None):
        self.posts.append((url, headers))
        if self.token_status != 200:
            return Resp(self.token_status, b'{"detail":"secret ApiKey echo"}')
        return Resp(200, (jwt(self.now + 24 * 3600) + "\n").encode())

    def get(self, url, headers=None, params=None, timeout=None):
        path = url.split(".com", 1)[1]
        self.gets.append((path, dict(params or {}), headers))
        if self.reject_bearer_once:
            self.reject_bearer_once = False
            return Resp(401)
        route = self.routes.get(path)
        if callable(route):
            return route(params or {})
        if isinstance(route, Resp):
            return route
        return Resp(200, json_body=route) if route is not None else Resp(404)


def session(http, cached=None, clock=None):
    return P.PersonalApiSession("pk_test_key_1234", cached, http=http, clock=clock or (lambda: http.now))


# -- token exchange -----------------------------------------------------------

def test_exchange_uses_apikey_header_and_caches_until_refresh_window():
    http = FakeHttp()
    s = session(http)
    token = s.token()
    assert http.posts[0][0].endswith(P.TOKEN_PATH)
    assert http.posts[0][1]["Authorization"] == "ApiKey pk_test_key_1234"
    assert token.count(".") == 2 and not token.endswith("\n")
    s.token()
    assert len(http.posts) == 1
    # Less than one hour left: exchange again.
    http.now += 23.5 * 3600
    s.token()
    assert len(http.posts) == 2


def test_cached_token_survives_serialisation():
    http = FakeHttp()
    first = session(http)
    first.token()
    cached = json.loads(first.dumps())
    assert cached["kind"] == "personal_api" and cached["expires_at"] > http.now
    second = session(http, cached)
    second.token()
    assert len(http.posts) == 1
    # A cache of the password login (other kind) is ignored.
    third = session(http, {"kind": "garth", "access_token": "x", "expires_at": http.now + 9e9})
    third.token()
    assert len(http.posts) == 2


def test_rejected_key_maps_to_reauth_and_hides_response_body():
    with pytest.raises(GarminConnectAuthenticationError) as raised:
        session(FakeHttp(token_status=401)).token()
    assert "secret" not in str(raised.value)
    with pytest.raises(GarminConnectTooManyRequestsError):
        session(FakeHttp(token_status=429)).token()
    with pytest.raises(P.PersonalApiError) as other:
        session(FakeHttp(token_status=503)).token()
    assert str(other.value) == "GARMIN_API_HTTP_503" and "secret" not in str(other.value)


def test_non_jwt_answer_is_rejected():
    http = FakeHttp()
    http.post = lambda url, headers=None, timeout=None: Resp(200, b"not-a-jwt")
    with pytest.raises(P.PersonalApiError):
        session(http).token()


def test_revoked_bearer_token_is_exchanged_once_more():
    http = FakeHttp({"/x": {"ok": True}})
    s = session(http)
    s.token()
    http.reject_bearer_once = True
    assert s.get("/x") == {"ok": True}
    assert len(http.posts) == 2
    assert http.gets[-1][2]["Authorization"].startswith("Bearer ")


def test_persistent_401_raises_authentication_error():
    http = FakeHttp({"/x": Resp(401)})
    with pytest.raises(GarminConnectAuthenticationError):
        session(http).get("/x")


def test_empty_key_is_refused():
    with pytest.raises(P.PersonalApiError):
        P.PersonalApiSession("   ")
    assert P.key_hint("abcdefgh1234") == "…1234"
    assert P.key_hint("short") == "…"


# -- gateway ------------------------------------------------------------------

def activity_route(total):
    def route(params):
        start, limit = int(params["start"]), int(params["limit"])
        assert limit <= P.ACTIVITY_PAGE_SIZE
        return Resp(200, json_body=[{"activityId": i + 1} for i in range(start, min(total, start + limit))])
    return route


def test_activity_pages_never_exceed_garmin_page_size():
    http = FakeHttp({"/activitylist-service/activities/search/activities": activity_route(130)})
    gw = P.PersonalApiGateway(session(http))
    rows = gw.get_activities_page(0, 1000)
    assert len(rows) == 130
    assert [g[1]["limit"] for g in http.gets] == [50, 50, 50]
    http.gets.clear()
    assert len(gw.get_activities_page(100, 20)) == 20
    assert http.gets[0][1] == {"start": 100, "limit": 20}


def test_activities_by_date_pages_with_date_filter():
    http = FakeHttp({"/activitylist-service/activities/search/activities": activity_route(60)})
    rows = P.PersonalApiGateway(session(http)).get_activities_by_date(date(2026, 10, 1), date(2026, 10, 2))
    assert len(rows) == 60
    assert all(g[1]["startDate"] == "2026-10-01" and g[1]["endDate"] == "2026-10-02" for g in http.gets)


def test_daily_summary_picks_the_requested_day():
    day = date(2026, 10, 22)
    payload = {"data": [{"calendarDate": "2026-10-21", "movement": {"steps": 1}}, {"calendarDate": "2026-10-22", "movement": {"steps": 9876}}]}
    http = FakeHttp({"/usersummary-service/v2/dailysummaries": payload})
    summary = P.PersonalApiGateway(session(http)).get_user_summary(day)
    assert summary["movement"]["steps"] == 9876
    assert http.gets[0][1] == {"startDate": "2026-10-22", "endDate": "2026-10-22"}


def test_endpoints_follow_the_official_client():
    day = date(2026, 10, 22)
    http = FakeHttp({
        "/sleep-service/sleep/dailySleep": {"dailySleepDTO": {"sleepTimeSeconds": 28000}},
        "/hrv-service/hrv/2026-10-22": {"hrvSummary": {"lastNightAvg": 51}},
        "/usersummary-service/stats/stress/daily/2026-10-22/2026-10-22": [{"values": {"overallStressLevel": 30}}],
        "/wellness-service/wellness/bodyBattery/reports/daily": [{"bodyBatteryValuesArray": [[1, 80]]}],
        "/weight-service/weight/range/2026-10-22/2026-10-22": {"dateWeightList": []},
        "/biometric-service/heartRateZones/v2": [{"sport": "DEFAULT"}],
        "/userprofile-service/userprofile/settings": {"displayName": "Pengu", "userData": {"height": 180}},
        "/download-service/files/activity/42": Resp(200, b"PK\x03\x04zip"),
    })
    gw = P.PersonalApiGateway(session(http))
    assert gw.get_sleep_data(day)["dailySleepDTO"]["sleepTimeSeconds"] == 28000
    assert http.gets[-1][1] == {"date": "2026-10-22"}
    assert gw.get_hrv_data(day)["hrvSummary"]["lastNightAvg"] == 51
    assert gw.get_stress_data(day)[0]["values"]["overallStressLevel"] == 30
    assert gw.get_body_battery(day)
    assert gw.get_stats_and_body(day) == {"dateWeightList": []}
    assert http.gets[-1][1] == {"includeAll": "true"}
    assert gw.get_heart_rate_zones()
    gw.get_user_profile()
    assert gw.display_name == "Pengu"
    assert gw.download_activity_fit(42).startswith(b"PK")
    assert "zip" in http.gets[-1][2]["Accept"]
    with pytest.raises(P.PersonalApiError):
        gw.download_activity_fit(0)


@pytest.mark.parametrize("name,args", [
    ("get_training_readiness", (date.today(),)), ("get_training_status", (date.today(),)),
    ("get_max_metrics", (date.today(),)), ("get_power_zones", ()), ("get_respiration_data", (date.today(),)),
    ("count_activities", ()),
])
def test_missing_domains_raise_unsupported(name, args):
    gw = P.PersonalApiGateway(session(FakeHttp()))
    with pytest.raises(P.PersonalApiUnsupported):
        getattr(gw, name)(*args)


def test_gateway_offers_every_read_only_method():
    from pengucoach.garmin.gateway.read_only import GarminReadOnlyGateway
    wanted = {n for n in dir(GarminReadOnlyGateway) if not n.startswith("_")}
    offered = {n for n in dir(P.PersonalApiGateway) if not n.startswith("_")}
    assert wanted <= offered


def test_sync_treats_unsupported_domain_as_unavailable_not_failed():
    from pengucoach.garmin.sync.service import _call
    domains = {}

    def missing():
        raise P.PersonalApiUnsupported("training_status")

    assert asyncio.run(_call("training_status", missing, domains)) is None
    assert domains["training_status"] == {"ok": True, "available": False, "unsupported": True}


# -- factory and auth service -------------------------------------------------

@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(crypto.settings, "encryption_key", Fernet.generate_key().decode())


def test_factory_builds_personal_gateway_and_serialises_cache(key, monkeypatch):
    http = FakeHttp()
    monkeypatch.setattr(factory, "PersonalApiSession", lambda api_key, cached: P.PersonalApiSession(api_key, cached, http=http, clock=lambda: http.now))
    box = crypto.SecretBox()
    conn = GarminConnection(user_id=uuid.uuid4(), auth_mode="personal_api", api_key_ciphertext=box.encrypt("pk_test_key_1234"), token_ciphertext=None)
    gateway, raw = asyncio.run(factory.gateway_from_connection(conn))
    assert isinstance(gateway, P.PersonalApiGateway) and len(http.posts) == 1
    conn.token_ciphertext = factory.serialize_refreshed_token(raw)
    asyncio.run(factory.gateway_from_connection(conn))
    assert len(http.posts) == 1, "cached bearer token must be reused"
    with pytest.raises(factory.WorkoutExportNeedsLogin):
        asyncio.run(factory.workout_gateway_from_connection(conn))


def test_password_connections_keep_the_old_path():
    assert factory.auth_mode(GarminConnection(user_id=uuid.uuid4())) == "password"
    assert factory.auth_mode(GarminConnection(user_id=uuid.uuid4(), auth_mode="password")) == "password"
    assert factory.auth_mode(None) == "password"


class FakeDb:
    def __init__(self, connection=None, setting=None):
        self.connection, self.setting, self.added, self.commits = connection, setting, [], 0

    async def scalar(self, _query):
        return self.connection

    async def get(self, _model, _key):
        return self.setting

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, GarminConnection):
            self.connection = obj

    async def commit(self):
        self.commits += 1


def test_connect_personal_api_stores_key_encrypted_and_disables_export(key, monkeypatch):
    from pengucoach.garmin.auth import service
    http = FakeHttp({"/userprofile-service/userprofile/settings": {"displayName": "Pengu"}})
    monkeypatch.setattr(service, "PersonalApiSession", lambda api_key: P.PersonalApiSession(api_key, http=http, clock=lambda: http.now))
    user = SimpleNamespace(id=uuid.uuid4())
    setting = GarminSyncSetting(user_id=user.id, workout_export_enabled=True)
    existing = GarminConnection(user_id=user.id, auth_mode="password", token_ciphertext="old-oauth")
    db = FakeDb(existing, setting)
    expires = date.today() + timedelta(days=365)
    result = asyncio.run(service.GarminAuthService().connect_personal_api(db, user, "  pk_test_key_1234 ", expires))
    assert result["auth_mode"] == "personal_api" and result["connected"]
    box = crypto.SecretBox()
    assert existing.api_key_ciphertext != "pk_test_key_1234"
    assert box.decrypt(existing.api_key_ciphertext) == "pk_test_key_1234"
    assert json.loads(box.decrypt(existing.token_ciphertext))["kind"] == "personal_api"
    assert existing.api_key_hint == "…1234" and existing.api_key_expires_on == expires
    assert existing.garmin_display_name == "Pengu" and existing.status == "connected"
    assert setting.workout_export_enabled is False and db.commits == 1


def test_rejected_key_does_not_touch_the_connection(key, monkeypatch):
    from pengucoach.garmin.auth import service
    http = FakeHttp(token_status=403)
    monkeypatch.setattr(service, "PersonalApiSession", lambda api_key: P.PersonalApiSession(api_key, http=http))
    existing = GarminConnection(user_id=uuid.uuid4(), auth_mode="password", token_ciphertext="old-oauth", status="connected")
    db = FakeDb(existing)
    with pytest.raises(GarminConnectAuthenticationError):
        asyncio.run(service.GarminAuthService().connect_personal_api(db, SimpleNamespace(id=existing.user_id), "pk_bad_key_0000"))
    assert existing.token_ciphertext == "old-oauth" and existing.auth_mode == "password" and db.commits == 0


# -- wiring -------------------------------------------------------------------

def test_migration_adds_columns_idempotently():
    text = (ROOT / "db/migrations/versions/0016_garmin_personal_api.py").read_text()
    assert "down_revision = '0015_training_reviews'" in text
    for column in ("auth_mode", "api_key_ciphertext", "api_key_hint", "api_key_expires_on"):
        assert f"'{column}'" in text
    assert "get_columns('garmin_connections')" in text


def test_routes_expose_mode_and_block_workout_writes():
    garmin = (ROOT / "apps/api/routers/garmin.py").read_text()
    assert '@router.post("/auth/personal-api")' in garmin
    assert '"GARMIN_API_KEY_REJECTED"' in garmin and '"auth_mode": mode' in garmin
    assert 'values["workout_export_enabled"] = False' in garmin
    workouts = (ROOT / "apps/api/routers/garmin_workouts.py").read_text()
    assert workouts.count('"GARMIN_WORKOUT_EXPORT_NEEDS_LOGIN"') == 2
    assert '"export_available": available' in workouts


def test_settings_page_offers_both_methods_with_guide():
    component = (ROOT / "apps/web/components/GarminConnect.tsx").read_text()
    assert "/garmin/auth/personal-api" in component and "/garmin/auth/start" in component and "/garmin/auth/mfa" in component
    assert "Anleitung" in component and "settingsUrl" in component
    page = (ROOT / "apps/web/app/settings/garmin/page.tsx").read_text()
    assert "<GarminConnect" in page and "Key erneuern" in page
    lib = (ROOT / "apps/web/lib/garminAuth.ts").read_text()
    assert P.KEY_SETTINGS_URL in lib
