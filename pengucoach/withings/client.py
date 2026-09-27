from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


API_BASE = "https://wbsapi.withings.net"
AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
DEFAULT_SCOPES = ("user.info", "user.metrics", "user.activity")


class WithingsError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None, api_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.api_status = api_status


def authorization_url(client_id: str, redirect_uri: str, state: str, *, scopes: tuple[str, ...] = DEFAULT_SCOPES) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id.strip(),
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri.strip(),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _signature(client_secret: str, *, action: str, client_id: str, nonce: str | None = None, timestamp: int | None = None) -> str:
    # Withings signs the values of action/client_id plus nonce or timestamp,
    # ordered alphabetically by parameter name and joined by commas.
    values: list[str] = [action, client_id]
    if nonce is not None:
        values.append(str(nonce))
    elif timestamp is not None:
        values.append(str(timestamp))
    payload = ",".join(values).encode()
    return hmac.new(client_secret.encode(), payload, hashlib.sha256).hexdigest()


def _body(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WithingsError("WITHINGS_RESPONSE_NOT_JSON")
    status = payload.get("status")
    if status not in (None, 0):
        raise WithingsError(f"WITHINGS_API_STATUS_{status}", api_status=int(status))
    body = payload.get("body")
    return body if isinstance(body, dict) else {}


@dataclass
class TokenSet:
    userid: str
    access_token: str
    refresh_token: str
    scope: str
    expires_in: int


class WithingsOAuthClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, *, timeout_seconds: float = 30.0) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.redirect_uri = redirect_uri.strip()
        self.timeout_seconds = timeout_seconds
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise ValueError("WITHINGS_OAUTH_SETTINGS_REQUIRED")

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.post(f"{API_BASE}{path}", data=data, headers={"Accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise WithingsError("WITHINGS_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise WithingsError("WITHINGS_UNREACHABLE") from exc
        if response.status_code >= 400:
            raise WithingsError(f"WITHINGS_HTTP_{response.status_code}", status_code=response.status_code)
        try:
            return _body(response.json())
        except ValueError as exc:
            raise WithingsError("WITHINGS_RESPONSE_NOT_JSON", status_code=response.status_code) from exc

    async def nonce(self) -> str:
        timestamp = int(time.time())
        data = {
            "action": "getnonce",
            "client_id": self.client_id,
            "timestamp": timestamp,
        }
        data["signature"] = _signature(
            self.client_secret, action="getnonce", client_id=self.client_id, timestamp=timestamp
        )
        body = await self._post("/v2/signature", data)
        nonce = body.get("nonce")
        if not nonce:
            raise WithingsError("WITHINGS_NONCE_MISSING")
        return str(nonce)

    async def exchange_code(self, code: str) -> TokenSet:
        nonce = await self.nonce()
        data = {
            "action": "requesttoken",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code": code,
            "grant_type": "authorization_code",
            "nonce": nonce,
        }
        data["signature"] = _signature(
            self.client_secret, action="requesttoken", client_id=self.client_id, nonce=nonce
        )
        return self._token_set(await self._post("/v2/oauth2", data))

    async def refresh(self, refresh_token: str) -> TokenSet:
        nonce = await self.nonce()
        data = {
            "action": "requesttoken",
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "nonce": nonce,
        }
        data["signature"] = _signature(
            self.client_secret, action="requesttoken", client_id=self.client_id, nonce=nonce
        )
        return self._token_set(await self._post("/v2/oauth2", data))

    @staticmethod
    def _token_set(body: dict[str, Any]) -> TokenSet:
        access_token = body.get("access_token")
        refresh_token = body.get("refresh_token")
        userid = body.get("userid")
        if not access_token or not refresh_token or userid in (None, ""):
            raise WithingsError("WITHINGS_TOKEN_RESPONSE_INCOMPLETE")
        return TokenSet(
            userid=str(userid),
            access_token=str(access_token),
            refresh_token=str(refresh_token),
            scope=str(body.get("scope") or ""),
            expires_in=max(60, int(body.get("expires_in") or 10800)),
        )


class WithingsApiClient:
    def __init__(self, access_token: str, *, timeout_seconds: float = 45.0) -> None:
        self.access_token = access_token.strip()
        self.timeout_seconds = timeout_seconds
        if not self.access_token:
            raise ValueError("WITHINGS_ACCESS_TOKEN_REQUIRED")

    async def request(self, path: str, *, action: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"action": action, **(data or {})}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.post(
                    f"{API_BASE}/{path.lstrip('/')}",
                    data=payload,
                    headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise WithingsError("WITHINGS_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise WithingsError("WITHINGS_UNREACHABLE") from exc
        if response.status_code in {401, 403}:
            raise WithingsError("WITHINGS_AUTH_OR_PERMISSION_DENIED", status_code=response.status_code)
        if response.status_code >= 400:
            raise WithingsError(f"WITHINGS_HTTP_{response.status_code}", status_code=response.status_code)
        try:
            return _body(response.json())
        except ValueError as exc:
            raise WithingsError("WITHINGS_RESPONSE_NOT_JSON", status_code=response.status_code) from exc

    async def user(self) -> dict[str, Any]:
        return await self.request("v2/user", action="get")
