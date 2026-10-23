import asyncio
import inspect
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from garminconnect import Garmin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import GarminConnection, GarminSyncSetting, User
from pengucoach.garmin.personal_api import PersonalApiGateway, PersonalApiSession, key_hint
from pengucoach.security.crypto import SecretBox


@dataclass
class PendingChallenge:
    user_id: str
    client: Garmin
    client_state: object
    expires_at: datetime


class GarminAuthService:
    """Two-step Garmin authentication with short-lived in-memory MFA state."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingChallenge] = {}
        self._lock = asyncio.Lock()

    async def _connection(self, db: AsyncSession, user: User) -> GarminConnection:
        connection = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
        if not connection:
            connection = GarminConnection(user_id=user.id)
            db.add(connection)
        connection.status = "connected"
        connection.last_validated_at = datetime.now(timezone.utc)
        connection.last_error_code = None
        connection.consecutive_errors = 0
        connection.cooldown_until = None
        return connection

    async def _finish(self, db: AsyncSession, user: User, connection: GarminConnection) -> dict:
        sync_setting = await db.get(GarminSyncSetting, user.id)
        if not sync_setting:
            sync_setting = GarminSyncSetting(user_id=user.id, interval_minutes=settings.garmin_default_interval_minutes)
            db.add(sync_setting)
        if connection.auth_mode == "personal_api":
            # The Personal API cannot write to Garmin; never leave the export switch on.
            sync_setting.workout_export_enabled = False
        await db.commit()
        return {
            "status": "connected",
            "connected": True,
            "auth_mode": connection.auth_mode,
            "display_name": connection.garmin_display_name,
            "read_only": True,
        }

    async def _save_connection(self, db: AsyncSession, user: User, client: Garmin) -> dict:
        encrypted = SecretBox().encrypt(client.client.dumps())
        connection = await self._connection(db, user)
        connection.auth_mode = "password"
        connection.token_ciphertext = encrypted
        # Switching back to the login removes a stored Personal API key.
        connection.api_key_ciphertext = None
        connection.api_key_hint = None
        connection.api_key_expires_on = None
        connection.garmin_display_name = getattr(client, "display_name", None)
        connection.garmin_profile_id = str(getattr(client, "profile_id", "") or "") or None
        return await self._finish(db, user, connection)

    async def connect_personal_api(self, db: AsyncSession, user: User, api_key: str, expires_on: date | None = None) -> dict:
        """Validate a Garmin personal API key and store it encrypted.

        Validation = key exchange plus one profile read, so a key without data
        access is rejected here and not at the first background sync.
        """
        session = PersonalApiSession(api_key)
        gateway = PersonalApiGateway(session)
        await asyncio.to_thread(session.token)
        try:
            await asyncio.to_thread(gateway.get_user_profile)
        except Exception:
            # The token exchange worked; a profile hiccup must not block connecting.
            pass
        box = SecretBox()
        connection = await self._connection(db, user)
        previous_name = connection.garmin_display_name if connection.auth_mode == "personal_api" else None
        connection.auth_mode = "personal_api"
        connection.api_key_ciphertext = box.encrypt(api_key.strip())
        connection.api_key_hint = key_hint(api_key)
        connection.api_key_expires_on = expires_on
        connection.token_ciphertext = box.encrypt(session.dumps())
        connection.garmin_display_name = gateway.display_name or previous_name or "Garmin Personal API"
        connection.garmin_profile_id = None
        api_key = ""
        return await self._finish(db, user, connection)

    async def start(self, db: AsyncSession, user: User, email: str, password: str) -> dict:
        client = Garmin(email=email, password=password, return_on_mfa=True)
        result1, result2 = await asyncio.to_thread(client.login)
        # Do not store or log the password. The Garmin client itself clears it after success.
        password = ""
        if result1 == "needs_mfa":
            challenge_id = secrets.token_urlsafe(32)
            async with self._lock:
                self._prune()
                self._pending[challenge_id] = PendingChallenge(
                    user_id=str(user.id), client=client, client_state=result2,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                )
            return {"status": "mfa_required", "connected": False, "challenge_id": challenge_id, "expires_in": 600, "read_only": True}
        return await self._save_connection(db, user, client)

    async def complete_mfa(self, db: AsyncSession, user: User, challenge_id: str, code: str) -> dict:
        async with self._lock:
            self._prune()
            pending = self._pending.get(challenge_id)
        if not pending or pending.user_id != str(user.id):
            raise KeyError("challenge missing or expired")
        # python-garminconnect has used both a (client_state, mfa_code) wrapper
        # and a stateful one-argument resume style across auth implementations.
        # Detect the bound method signature instead of tying PenguCoach to one variant.
        resume = pending.client.resume_login
        parameter_count = len(inspect.signature(resume).parameters)
        if parameter_count >= 2:
            await asyncio.to_thread(resume, pending.client_state, code.strip())
        else:
            await asyncio.to_thread(resume, code.strip())
        result = await self._save_connection(db, user, pending.client)
        async with self._lock:
            self._pending.pop(challenge_id, None)
        return result

    async def disconnect(self, db: AsyncSession, user: User) -> None:
        connection = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
        if connection:
            connection.status = "disconnected"
            connection.token_ciphertext = None
            connection.api_key_ciphertext = None
            connection.api_key_hint = None
            connection.api_key_expires_on = None
            connection.cooldown_until = None
            connection.next_sync_at = None
            await db.commit()

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        for key in [k for k, v in self._pending.items() if v.expires_at <= now]:
            self._pending.pop(key, None)


garmin_auth_service = GarminAuthService()
