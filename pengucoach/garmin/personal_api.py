"""Garmin Personal API (official, key based) as an alternative to the password login.

Garmin issues a *personal API key* in Garmin Connect
(https://connect.garmin.com/app/settings/personalApiToken). The key is exchanged
for a short-lived JWT bearer token, which then reads the user's own data from
``personal.connectapi.garmin.com``. The flow follows Garmin's reference client
(github.com/garmin/connect-personal-api-python, Apache-2.0).

The gateway below offers the same method names as :class:`GarminReadOnlyGateway`
so the existing sync, FIT and zone code works unchanged. Endpoints the Personal
API does not offer raise :class:`PersonalApiUnsupported`; the sync records such a
domain as unavailable instead of failing the day. HTTP 401/403 and 429 are mapped
to the garminconnect exceptions the sync already handles (re-auth, cool-down).
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import date
from typing import Any, Callable

import requests
from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

BASE_URL = os.environ.get("GARMIN_PERSONAL_API_BASE_URL", "https://personal.connectapi.garmin.com").rstrip("/")
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
KEY_SETTINGS_URL = "https://connect.garmin.com/app/settings/personalApiToken"
REFRESH_WINDOW_SECONDS = 60 * 60
TIMEOUT_SECONDS = 30
# Garmin answers larger activity pages with HTTP 400/500.
ACTIVITY_PAGE_SIZE = 50
MAX_ACTIVITY_PAGES = 400


class PersonalApiError(Exception):
    """A Personal API request failed for a reason other than auth or rate limits."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PersonalApiUnsupported(Exception):
    """The Personal API has no endpoint for this data domain."""


def _jwt_expiration(token: str) -> float:
    try:
        part = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return float(payload["exp"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise PersonalApiError("GARMIN_API_TOKEN_INVALID") from exc


def key_hint(api_key: str) -> str:
    key = api_key.strip()
    return f"…{key[-4:]}" if len(key) >= 8 else "…"


def _raise_for(response: requests.Response, *, exchange: bool = False) -> None:
    if response.ok:
        return
    code = response.status_code
    if code in (401, 403):
        raise GarminConnectAuthenticationError("GARMIN_API_KEY_REJECTED" if exchange else "GARMIN_API_TOKEN_REJECTED")
    if code == 429:
        raise GarminConnectTooManyRequestsError("GARMIN_RATE_LIMITED")
    # Never include the response body: it could echo a token.
    raise PersonalApiError(f"GARMIN_API_HTTP_{code}", code)


class PersonalApiSession:
    """Key exchange, bearer-token cache and HTTP access.

    ``dumps()`` returns the cache that PenguCoach stores encrypted in
    ``garmin_connections.token_ciphertext`` – the same place the password login
    keeps its OAuth tokens – so callers can keep using ``serialize_refreshed_token``.
    """

    kind = "personal_api"

    def __init__(
        self,
        api_key: str,
        cached: dict[str, Any] | None = None,
        *,
        http: requests.Session | None = None,
        clock: Callable[[], float] = time.time,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key or not api_key.strip():
            raise PersonalApiError("GARMIN_API_KEY_MISSING")
        self._key = api_key.strip()
        self._http = http or requests.Session()
        self._clock = clock
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._expires_at = 0.0
        if isinstance(cached, dict) and cached.get("kind") == self.kind:
            token, expires = cached.get("access_token"), cached.get("expires_at")
            if isinstance(token, str) and isinstance(expires, (int, float)):
                self._token, self._expires_at = token, float(expires)
        self.exchanges = 0

    # -- token -----------------------------------------------------------------
    def token(self, *, force: bool = False) -> str:
        if not force and self._token and self._expires_at - self._clock() > REFRESH_WINDOW_SECONDS:
            return self._token
        response = self._http.post(
            f"{self.base_url}{TOKEN_PATH}",
            headers={"Accept": "*/*", "Authorization": f"ApiKey {self._key}"},
            timeout=TIMEOUT_SECONDS,
        )
        _raise_for(response, exchange=True)
        token = response.text.strip()
        self._expires_at = _jwt_expiration(token)
        self._token = token
        self.exchanges += 1
        return token

    @property
    def token_expires_at(self) -> float:
        return self._expires_at

    def dumps(self) -> str:
        return json.dumps({"kind": self.kind, "access_token": self._token, "expires_at": self._expires_at})

    # -- requests --------------------------------------------------------------
    def _request(self, path: str, params: dict[str, Any] | None, accept: str) -> requests.Response:
        for attempt in (0, 1):
            response = self._http.get(
                f"{self.base_url}{path}",
                headers={"Accept": accept, "Authorization": f"Bearer {self.token(force=attempt == 1)}"},
                params=params,
                timeout=TIMEOUT_SECONDS,
            )
            # A cached bearer token can be revoked before its exp claim: exchange once more.
            if response.status_code == 401 and attempt == 0:
                continue
            _raise_for(response)
            return response
        raise AssertionError("unreachable")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._request(path, params, "application/json")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise PersonalApiError("GARMIN_API_INVALID_JSON") from exc

    def download(self, path: str) -> bytes:
        response = self._request(path, None, "application/zip, application/x-zip-compressed, application/octet-stream")
        if not response.content:
            raise PersonalApiError("GARMIN_API_EMPTY_DOWNLOAD")
        return response.content


def _iso(day: date) -> str:
    return day.isoformat()


def _first_text(payload: Any, *keys: str) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _first_text(value, *keys)
            if found:
                return found
    return None


def _day_entry(payload: Any, day: date) -> Any:
    """Pick the entry for ``day`` from a range response; fall back to the payload."""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(rows, list):
        items = [row for row in rows if isinstance(row, dict)]
        for row in items:
            if str(row.get("calendarDate") or row.get("date") or "")[:10] == day.isoformat():
                return row
        return items[0] if len(items) == 1 else (payload if items else None)
    return payload


def _activities(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        rows = payload.get("activityList") or payload.get("activities") or payload.get("data") or []
        return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
    return []


class PersonalApiGateway:
    """Read-only allow-list over the Personal API, mirroring GarminReadOnlyGateway."""

    def __init__(self, session: PersonalApiSession) -> None:
        self.__session = session
        self._display_name: str | None = None

    @property
    def display_name(self) -> str | None:
        return self._display_name

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.__session.get(path, params)

    @staticmethod
    def _unsupported(domain: str):
        raise PersonalApiUnsupported(domain)

    # -- profile ---------------------------------------------------------------
    def get_user_profile(self) -> Any:
        payload = self._get("/userprofile-service/userprofile/settings")
        self._display_name = _first_text(payload, "displayName", "fullName", "userName") or self._display_name
        return payload

    # -- daily wellness --------------------------------------------------------
    def get_user_summary(self, day: date) -> Any:
        return _day_entry(self._get("/usersummary-service/v2/dailysummaries", {"startDate": _iso(day), "endDate": _iso(day)}), day)

    def get_heart_rates(self, day: date) -> Any:
        return self._get("/wellness-service/wellness/dailyHeartRate", {"date": _iso(day)})

    def get_sleep_data(self, day: date) -> Any:
        return self._get("/sleep-service/sleep/dailySleep", {"date": _iso(day)})

    def get_hrv_data(self, day: date) -> Any:
        return self._get(f"/hrv-service/hrv/{_iso(day)}")

    def get_stress_data(self, day: date) -> Any:
        return self._get(f"/usersummary-service/stats/stress/daily/{_iso(day)}/{_iso(day)}")

    def get_body_battery(self, day: date) -> Any:
        return self._get("/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": _iso(day), "endDate": _iso(day)})

    def get_hydration_data(self, day: date) -> Any:
        return self._get(f"/usersummary-service/stats/hydration/daily/{_iso(day)}/{_iso(day)}")

    def get_spo2_data(self, day: date) -> Any:
        return self._get(f"/wellness-service/wellness/daily/spo2acclimation/{_iso(day)}")

    def get_respiration_data(self, day: date) -> Any:
        self._unsupported("respiration")

    def get_intensity_minutes_data(self, day: date) -> Any:
        # Intensity minutes are part of the daily summary; the sync reads them from there.
        self._unsupported("intensity")

    def get_floors(self, day: date) -> Any:
        self._unsupported("floors")

    def get_training_readiness(self, day: date) -> Any:
        self._unsupported("training_readiness")

    def get_training_status(self, day: date) -> Any:
        self._unsupported("training_status")

    def get_max_metrics(self, day: date) -> Any:
        self._unsupported("max_metrics")

    # -- body ------------------------------------------------------------------
    def get_body_composition(self, start: date, end: date) -> Any:
        return self._get(f"/weight-service/weight/range/{_iso(start)}/{_iso(end)}", {"includeAll": "true"})

    def get_stats_and_body(self, day: date) -> Any:
        return self.get_body_composition(day, day)

    def get_weigh_ins(self, start: date, end: date) -> Any:
        return self.get_body_composition(start, end)

    def get_blood_pressure(self, start: date, end: date) -> Any:
        self._unsupported("blood_pressure")

    def get_endurance_score(self, start: date, end: date) -> Any:
        self._unsupported("endurance_score")

    def get_hill_score(self, start: date, end: date) -> Any:
        self._unsupported("hill_score")

    def get_race_predictions(self) -> Any:
        self._unsupported("race_predictions")

    # -- zones -----------------------------------------------------------------
    def get_heart_rate_zones(self) -> Any:
        return self._get("/biometric-service/heartRateZones/v2")

    def get_power_zones(self) -> Any:
        self._unsupported("power_zones")

    def get_power_zones_for_sport(self, sport: str) -> Any:
        self._unsupported("power_zones")

    # -- activities ------------------------------------------------------------
    def count_activities(self) -> int:
        self._unsupported("activity_count")

    def _search(self, offset: int, limit: int, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return _activities(self._get("/activitylist-service/activities/search/activities", {"start": offset, "limit": limit, **(extra or {})}))

    def get_activities_page(self, start: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        """Return up to ``limit`` activities from ``start`` using pages Garmin accepts."""
        rows: list[dict[str, Any]] = []
        offset, wanted = max(0, int(start)), max(1, int(limit))
        while len(rows) < wanted:
            size = min(ACTIVITY_PAGE_SIZE, wanted - len(rows))
            page = self._search(offset, size)
            rows.extend(page)
            if len(page) < size:
                break
            offset += len(page)
        return rows

    def get_activities_by_date(self, start: date, end: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        extra = {"startDate": _iso(start), "endDate": _iso(end)}
        for page_no in range(MAX_ACTIVITY_PAGES):
            page = self._search(page_no * ACTIVITY_PAGE_SIZE, ACTIVITY_PAGE_SIZE, extra)
            rows.extend(page)
            if len(page) < ACTIVITY_PAGE_SIZE:
                break
        return rows

    def get_activity(self, activity_id: int) -> Any:
        return self._get(f"/activity-service/activity/{int(activity_id)}")

    def get_activity_details(self, activity_id: int) -> Any:
        self._unsupported("activity_details")

    def get_activity_splits(self, activity_id: int) -> Any:
        return None

    def get_activity_weather(self, activity_id: int) -> Any:
        return None

    def get_activity_gear(self, activity_id: int) -> Any:
        self._unsupported("gear")

    def get_devices(self) -> Any:
        self._unsupported("devices")

    def get_gear(self) -> Any:
        self._unsupported("gear")

    def download_activity_fit(self, activity_id: int) -> bytes:
        activity = int(activity_id)
        if activity <= 0:
            raise PersonalApiError("GARMIN_ACTIVITY_ID_INVALID")
        # ZIP with the original FIT file; pengucoach.fit.service extracts it.
        return self.__session.download(f"/download-service/files/activity/{activity}")
