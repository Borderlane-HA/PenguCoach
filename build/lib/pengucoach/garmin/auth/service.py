import asyncio
import inspect
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from garminconnect import Garmin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.common.config import settings
from pengucoach.db.models import GarminConnection, GarminSyncSetting, User
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

    async def _save_connection(self, db: AsyncSession, user: User, client: Garmin) -> dict:
        token_blob = client.client.dumps()
        encrypted = SecretBox().encrypt(token_blob)
        connection = await db.scalar(select(GarminConnection).where(GarminConnection.user_id == user.id))
        if not connection:
            connection = GarminConnection(user_id=user.id)
            db.add(connection)
        connection.status = "connected"
        connection.token_ciphertext = encrypted
        connection.last_validated_at = datetime.now(timezone.utc)
        connection.last_error_code = None
        connection.consecutive_errors = 0
        connection.cooldown_until = None
        connection.garmin_display_name = getattr(client, "display_name", None)
        connection.garmin_profile_id = str(getattr(client, "profile_id", "") or "") or None
        sync_setting = await db.get(GarminSyncSetting, user.id)
        if not sync_setting:
            db.add(GarminSyncSetting(user_id=user.id, interval_minutes=settings.garmin_default_interval_minutes))
        await db.commit()
        return {
            "status": "connected",
            "connected": True,
            "display_name": connection.garmin_display_name,
            "read_only": True,
        }

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
            connection.cooldown_until = None
            connection.next_sync_at = None
            await db.commit()

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        for key in [k for k, v in self._pending.items() if v.expires_at <= now]:
            self._pending.pop(key, None)


garmin_auth_service = GarminAuthService()
