from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx


class SparkyFitnessError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def normalize_base_url(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("SPARKYFITNESS_URL_INVALID")
    path = parsed.path.rstrip("/")
    if path.endswith("/api"):
        return raw
    if path.endswith("/api/api-docs") or "/api/api-docs/" in path:
        base_path = path.split("/api/api-docs", 1)[0]
        return f"{parsed.scheme}://{parsed.netloc}{base_path}/api".rstrip("/")
    return f"{raw}/api"


@dataclass
class CapabilityResult:
    identity: bool = False
    activities: bool = False
    sleep: bool = False
    checkins: bool = False
    custom_metrics: bool = False
    dashboard: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "identity": self.identity,
            "activities": self.activities,
            "sleep": self.sleep,
            "checkins": self.checkins,
            "custom_metrics": self.custom_metrics,
            "dashboard": self.dashboard,
        }


class SparkyFitnessClient:
    """Small read-only client for SparkyFitness' public API-key surface."""

    def __init__(self, base_url: str, api_key: str, *, timeout_seconds: float = 30.0) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("SPARKYFITNESS_API_KEY_REQUIRED")
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        # v1.7.x documents x-api-key as the OpenAPI scheme. Bearer is also
        # accepted by SparkyFitness, but using one credential header keeps the
        # request surface explicit and easy to audit.
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    async def request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.get(url, headers=self._headers(), params=params)
        except httpx.TimeoutException as exc:
            raise SparkyFitnessError("SPARKYFITNESS_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise SparkyFitnessError("SPARKYFITNESS_UNREACHABLE") from exc
        if response.status_code in {401, 403}:
            raise SparkyFitnessError("SPARKYFITNESS_AUTH_OR_PERMISSION_DENIED", status_code=response.status_code)
        if response.status_code >= 400:
            raise SparkyFitnessError(f"SPARKYFITNESS_HTTP_{response.status_code}", status_code=response.status_code)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise SparkyFitnessError("SPARKYFITNESS_RESPONSE_NOT_JSON", status_code=response.status_code) from exc

    async def probe(self, path: str, *, params: dict[str, Any] | None = None) -> bool:
        try:
            await self.request(path, params=params)
            return True
        except SparkyFitnessError:
            return False

    async def capabilities(self) -> CapabilityResult:
        today = date.today().isoformat()
        # API keys can be permission-scoped. A successful identity call OR any
        # successful protected read endpoint proves the key is usable, while
        # each individual probe describes the data that PenguCoach may read.
        identity_endpoint = await self.probe("/identity/user")
        activities = await self.probe("/v2/exercise-entries/history", params={"page": 1, "pageSize": 1})
        sleep = await self.probe("/sleep/details", params={"startDate": today, "endDate": today}) or await self.probe("/sleep", params={"startDate": today, "endDate": today})
        checkins = await self.probe(f"/measurements/check-in-measurements-range/{today}/{today}")
        custom_metrics = await self.probe("/measurements/custom-categories")
        dashboard = await self.probe("/dashboard/stats", params={"date": today})
        return CapabilityResult(
            identity=identity_endpoint or activities or sleep or checkins or custom_metrics or dashboard,
            activities=activities,
            sleep=sleep,
            checkins=checkins,
            custom_metrics=custom_metrics,
            dashboard=dashboard,
        )
