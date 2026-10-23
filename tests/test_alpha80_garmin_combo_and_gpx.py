"""alpha.80: Personal API key + export-only Garmin login, greyed features, cleaner GPX/track handling."""
import asyncio
import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from cryptography.fernet import Fernet

from pengucoach.db.models import Activity, GarminConnection, GarminSyncSetting
from pengucoach.fit import track
from pengucoach.garmin.gateway import factory
from pengucoach.imports import manual_activity as M
from pengucoach.security import crypto
from pengucoach.sparkyfitness import telemetry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(crypto.settings, "encryption_key", Fernet.generate_key().decode())


class FakeOAuth:
    def __init__(self, blob="oauth-new"):
        self.client = SimpleNamespace(dumps=lambda: blob)
        self.display_name = "Pengu Login"


# -- workout token routing ------------------------------------------------------

def test_workout_token_follows_the_connection_method():
    password = GarminConnection(user_id=uuid.uuid4(), auth_mode="password", status="connected", token_ciphertext="oauth")
    assert factory.workout_token(password) == "oauth" and factory.workout_export_available(password)
    api_only = GarminConnection(user_id=uuid.uuid4(), auth_mode="personal_api", status="connected", token_ciphertext="bearer-cache")
    assert factory.workout_token(api_only) is None and not factory.workout_export_available(api_only)
    both = GarminConnection(user_id=uuid.uuid4(), auth_mode="personal_api", status="connected", token_ciphertext="bearer-cache",
                            export_token_ciphertext="oauth-export", export_status="connected")
    assert factory.workout_token(both) == "oauth-export" and factory.workout_export_available(both)
    both.export_status = "reauth_required"
    assert not factory.workout_export_available(both)
    with pytest.raises(factory.WorkoutExportNeedsLogin):
        asyncio.run(factory.workout_gateway_from_connection(api_only))


def test_refreshed_login_tokens_never_overwrite_the_api_cache(key):
    box = crypto.SecretBox()
    both = GarminConnection(user_id=uuid.uuid4(), auth_mode="personal_api", status="connected", token_ciphertext="bearer-cache",
                            export_token_ciphertext="old", export_status="connected")
    factory.store_workout_token(both, FakeOAuth("fresh"))
    assert both.token_ciphertext == "bearer-cache"
    assert box.decrypt(both.export_token_ciphertext) == "fresh"
    password = GarminConnection(user_id=uuid.uuid4(), auth_mode="password", status="connected", token_ciphertext="old")
    factory.store_workout_token(password, FakeOAuth("fresh"))
    assert box.decrypt(password.token_ciphertext) == "fresh"


# -- auth service ---------------------------------------------------------------

class FakeDb:
    def __init__(self, connection=None, setting=None, rows=()):
        self.connection, self.setting, self.rows, self.commits = connection, setting, list(rows), 0

    async def scalar(self, _query):
        return self.connection

    async def scalars(self, _query):
        return SimpleNamespace(all=lambda: self.rows)

    async def get(self, _model, _key):
        return self.setting

    def add(self, obj):
        if isinstance(obj, GarminConnection):
            self.connection = obj

    async def commit(self):
        self.commits += 1


def test_export_login_requires_an_api_connection_before_contacting_garmin():
    from pengucoach.garmin.auth.service import GarminAuthService
    user = SimpleNamespace(id=uuid.uuid4())
    db = FakeDb(GarminConnection(user_id=user.id, auth_mode="password", status="connected"))
    with pytest.raises(KeyError):
        asyncio.run(GarminAuthService().start(db, user, "a@b.de", "pw", purpose="export"))


def test_export_login_is_stored_separately(key):
    from pengucoach.garmin.auth.service import GarminAuthService
    user = SimpleNamespace(id=uuid.uuid4())
    conn = GarminConnection(user_id=user.id, auth_mode="personal_api", status="connected", token_ciphertext="bearer-cache")
    db = FakeDb(conn)
    result = asyncio.run(GarminAuthService()._save_export_login(db, user, FakeOAuth("oauth-export")))
    assert result["purpose"] == "export"
    assert conn.token_ciphertext == "bearer-cache" and conn.auth_mode == "personal_api"
    assert crypto.SecretBox().decrypt(conn.export_token_ciphertext) == "oauth-export"
    assert conn.export_status == "connected" and conn.export_display_name == "Pengu Login"
    setting = GarminSyncSetting(user_id=user.id, workout_export_enabled=True)
    db.setting = setting
    asyncio.run(GarminAuthService().disconnect_export(db, user))
    assert conn.export_token_ciphertext is None and conn.export_status is None
    assert setting.workout_export_enabled is False


@pytest.mark.parametrize("keep", [True, False])
def test_switching_to_api_key_can_keep_the_login_for_export(key, monkeypatch, keep):
    from pengucoach.garmin import personal_api as P
    from pengucoach.garmin.auth import service

    class Http:
        def post(self, url, headers=None, timeout=None):
            import base64
            enc = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip("=")
            body = f"{enc({'alg': 'none'})}.{enc({'exp': 9e9})}.s".encode()
            return SimpleNamespace(ok=True, status_code=200, text=body.decode(), content=body)

        def get(self, url, headers=None, params=None, timeout=None):
            return SimpleNamespace(ok=True, status_code=200, content=b"{}", text="{}", json=lambda: {})

    monkeypatch.setattr(service, "PersonalApiSession", lambda api_key: P.PersonalApiSession(api_key, http=Http()))
    user = SimpleNamespace(id=uuid.uuid4())
    conn = GarminConnection(user_id=user.id, auth_mode="password", status="connected", token_ciphertext="oauth-old", garmin_display_name="Pengu")
    setting = GarminSyncSetting(user_id=user.id, workout_export_enabled=True)
    db = FakeDb(conn, setting)
    asyncio.run(service.GarminAuthService().connect_personal_api(db, user, "pk_test_key_1234", None, keep))
    assert conn.auth_mode == "personal_api"
    if keep:
        assert conn.export_token_ciphertext == "oauth-old" and conn.export_status == "connected"
        assert setting.workout_export_enabled is True
    else:
        assert conn.export_token_ciphertext is None and conn.export_status is None
        assert setting.workout_export_enabled is False


# -- GPX / track ----------------------------------------------------------------

def gpx(points, typ="running"):
    body = "".join(
        f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}">' + (f"<ele>{ele:.1f}</ele>" if ele is not None else "") + (f"<time>{t}</time>" if t else "") + "</trkpt>"
        for lat, lon, ele, t in points)
    return (f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Lauf</name><type>{typ}</type>'
            f"<trkseg>{body}</trkseg></trk></gpx>").encode()


def run_points(seconds=1800, speed=3.0, pause_at=900, pause_s=300, noise=3.0, fmt=None, step=1):
    random.seed(7)
    t = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    lat, lon, ex, ey = 48.0, 11.0, 0.0, 0.0
    out = []
    for i in range(0, seconds, step):
        if i == pause_at:
            t += timedelta(seconds=pause_s)
        t += timedelta(seconds=step)
        lat += speed * step / 111_111.0
        ex = 0.9 * ex + random.gauss(0, noise * 0.44)
        ey = 0.9 * ey + random.gauss(0, noise * 0.44)
        stamp = fmt(t, i) if fmt else t.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append((lat + ex / 111_111.0, lon + ey / (111_111.0 * math.cos(math.radians(48))), 500.0, stamp))
    return out


def test_mixed_timestamp_formats_all_parse():
    fmt = lambda t, i: t.strftime("%Y-%m-%dT%H:%M:%S") + (".250Z" if i % 3 else "Z")
    df, session, _, _ = M.parse_gpx_bytes(gpx(run_points(fmt=fmt)))
    assert df["timestamp"].notna().all()
    assert str(df["timestamp"].dtype).startswith("datetime64")
    assert isinstance(session["start_time"], datetime)


def test_gps_noise_no_longer_inflates_distance_and_speed():
    df, session, _, _ = M.parse_gpx_bytes(gpx(run_points()))
    true_distance = 3.0 * 1800
    assert abs(session["total_distance"] - true_distance) / true_distance < 0.04
    speeds = pd.to_numeric(df["speed"], errors="coerce").dropna()
    assert speeds.quantile(0.99) < 3.0 * 1.6, "speed spikes from single GPS fixes"


def test_moving_time_excludes_pauses():
    df, _, _, _ = M.parse_gpx_bytes(gpx(run_points()))
    assert M._duration_from_df(df) == 2099
    assert abs(track.moving_seconds(df) - 1799) <= 5


def test_sparse_tracks_are_not_smoothed_into_shortcuts():
    # A circle sampled every 15 s: smoothing would cut the curve noticeably.
    pts, t = [], datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    for i in range(41):
        a = 2 * math.pi * i / 40
        pts.append((48 + 0.004 * math.cos(a), 11 + 0.006 * math.sin(a), None, (t + timedelta(seconds=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    df, session, _, _ = M.parse_gpx_bytes(gpx(pts))
    raw = sum(track.haversine_m(*pts[i][:2], *pts[i + 1][:2]) for i in range(40))
    assert abs(session["total_distance"] - raw) < 1.0


def test_gps_jump_is_ignored():
    pts = run_points(seconds=120, pause_at=-1, noise=0)
    lat, lon, ele, stamp = pts[60]
    pts[60] = (lat + 0.05, lon, ele, stamp)  # 5.5 km away for one second
    df, session, _, _ = M.parse_gpx_bytes(gpx(pts))
    assert session["total_distance"] < 3.0 * 120 * 1.1


@pytest.mark.parametrize("raw,expected", [
    ("road_biking", "road_biking"), ("Biking", "cycling"), ("mountain biking", "mountain_biking"), ("e-bike ride", "cycling"),
    ("trail_running", "trail_running"), ("Jogging", "running"), ("9", "running"), ("1", "cycling"),
    ("hiking", "hiking"), ("walking", "walking"), ("open water swimming", "open_water_swimming"), ("", "other"),
])
def test_sport_detection(raw, expected):
    assert M.gpx_sport(raw) == expected


def test_routes_without_recording_are_rejected():
    planned = [(48 + i / 10_000, 11.0, 500.0, None) for i in range(50)]
    df, _, _, _ = M.parse_gpx_bytes(gpx(planned))
    assert M._track_problem(df) == "ROUTE_WITHOUT_TIMES"
    empty, _, _, _ = M.parse_gpx_bytes(b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><rte><rtept lat="48" lon="11"/></rte></gpx>')
    assert M._track_problem(empty) == "NO_TRACK_POINTS"
    good, _, _, _ = M.parse_gpx_bytes(gpx(run_points(seconds=60, pause_at=-1)))
    assert M._track_problem(good) is None


def test_tcx_device_distance_is_kept():
    tcx = b'''<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Activities><Activity Sport="Biking"><Id>2026-10-01T08:00:00Z</Id>
    <Lap StartTime="2026-10-01T08:00:00Z"><TotalTimeSeconds>20</TotalTimeSeconds><DistanceMeters>200</DistanceMeters><Track>''' + b"".join(
        f'<Trackpoint><Time>2026-10-01T08:00:{i:02d}Z</Time><Position><LatitudeDegrees>{48 + i / 100000}</LatitudeDegrees><LongitudeDegrees>11</LongitudeDegrees></Position><DistanceMeters>{i * 10}</DistanceMeters></Trackpoint>'.encode()
        for i in range(21)) + b"</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
    df, session, _, sport = M.parse_tcx_bytes(tcx)
    assert sport == "cycling"
    assert df["distance"].max() == 200 and session["total_distance"] == 200
    assert df["timestamp"].notna().all()


# -- SparkyFitness telemetry ----------------------------------------------------

def sparky_raw(points):
    return {"sparkyfitness": {telemetry.KEY: {"version": 1, "gps": points}}}


def test_sparky_track_without_dist_gets_a_distance_axis():
    t = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    pts = [{"t": (t + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"), "lat": 48 + i * 3 / 111_111, "lon": 11.0} for i in range(300)]
    df = telemetry.frame(sparky_raw(pts))
    assert abs(df["distance"].max() - 3 * 299) < 10
    assert pd.to_numeric(df["speed"], errors="coerce").dropna().between(2.5, 3.5).mean() > 0.95


def test_sparky_device_distance_wins():
    t = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    pts = [{"t": (t + timedelta(seconds=i)).isoformat(), "lat": 48 + i * 3 / 111_111, "lon": 11.0, "dist": i * 2.5, "speed": 2.5} for i in range(100)]
    df = telemetry.frame(sparky_raw(pts))
    assert df["distance"].max() == 99 * 2.5
    assert (df["speed"] == 2.5).all()


# -- overlap with existing activities -------------------------------------------

def test_overlap_detection_matches_same_workout_only():
    start = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    same = Activity(id=uuid.uuid4(), user_id=uuid.uuid4(), started_at=start + timedelta(minutes=1), duration_seconds=1750)
    later = Activity(id=uuid.uuid4(), user_id=same.user_id, started_at=start + timedelta(minutes=50), duration_seconds=1800)
    found = asyncio.run(M.find_overlapping_activity(FakeDb(rows=[later, same]), same.user_id, start, 1800))
    assert found is same
    assert asyncio.run(M.find_overlapping_activity(FakeDb(rows=[later]), same.user_id, start, 1800)) is None
    no_duration = Activity(id=uuid.uuid4(), user_id=same.user_id, started_at=start + timedelta(minutes=2), duration_seconds=None)
    assert asyncio.run(M.find_overlapping_activity(FakeDb(rows=[no_duration]), same.user_id, start, 1800)) is no_duration


# -- wiring -----------------------------------------------------------------------

def test_wiring():
    migration = (ROOT / "db/migrations/versions/0017_garmin_export_login.py").read_text()
    assert "down_revision = '0016_garmin_personal_api'" in migration and "export_token_ciphertext" in migration
    router = (ROOT / "apps/api/routers/garmin.py").read_text()
    assert '@router.post("/auth/export/start")' in router and '@router.post("/auth/export/disconnect")' in router
    assert '"export_login": _export_login_info(conn)' in router and 'snapshot["auth_mode"]' in router
    tasks = (ROOT / "worker/tasks/garmin_workouts.py").read_text()
    assert "serialize_refreshed_token" not in tasks and tasks.count("store_workout_token(connection, raw_client)") == 2
    activities = (ROOT / "apps/api/routers/activities.py").read_text()
    assert '"ACTIVITY_OVERLAP"' in activities and "allow_overlap=allow_overlap" in activities
    page = (ROOT / "apps/web/app/settings/garmin/page.tsx").read_text()
    assert "<GarminExportLogin" in page
    today = (ROOT / "apps/web/app/today/page.tsx").read_text()
    assert 'featureUnavailable(garminMode,"training_readiness")' in today
    upload = (ROOT / "apps/web/app/activities/page.tsx").read_text()
    assert "ROUTE_WITHOUT_TIMES" in upload and 'body.append("allow_overlap","true")' in upload
