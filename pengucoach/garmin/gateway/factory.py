import asyncio
import json

from garminconnect import Garmin

from pengucoach.db.models import GarminConnection
from pengucoach.garmin.gateway.read_only import GarminReadOnlyGateway
from pengucoach.garmin.gateway.workouts import GarminWorkoutGateway
from pengucoach.garmin.personal_api import PersonalApiGateway, PersonalApiSession
from pengucoach.security.crypto import SecretBox

AUTH_PASSWORD = "password"
AUTH_PERSONAL_API = "personal_api"


class WorkoutExportNeedsLogin(RuntimeError):
    """The Personal API is read-only; workout export needs the Garmin login."""

    def __init__(self) -> None:
        super().__init__("GARMIN_WORKOUT_EXPORT_NEEDS_LOGIN")


def auth_mode(connection: GarminConnection | None) -> str:
    return getattr(connection, "auth_mode", None) or AUTH_PASSWORD


def personal_session(connection: GarminConnection) -> PersonalApiSession:
    if not connection.api_key_ciphertext:
        raise RuntimeError("Garmin connection has no personal API key")
    box = SecretBox()
    cached = None
    if connection.token_ciphertext:
        try:
            cached = json.loads(box.decrypt(connection.token_ciphertext))
        except Exception:
            cached = None
    return PersonalApiSession(box.decrypt(connection.api_key_ciphertext), cached)


async def gateway_from_connection(connection: GarminConnection):
    if auth_mode(connection) == AUTH_PERSONAL_API:
        session = personal_session(connection)
        # The key exchange is a network call; keep it off the event loop.
        await asyncio.to_thread(session.token)
        return PersonalApiGateway(session), session
    if not connection.token_ciphertext:
        raise RuntimeError("Garmin connection has no token")
    token_blob = SecretBox().decrypt(connection.token_ciphertext)
    client = Garmin()
    await asyncio.to_thread(client.login, token_blob)
    return GarminReadOnlyGateway(client), client


def workout_token(connection: GarminConnection | None) -> str | None:
    """Encrypted Garmin login tokens usable for writing workouts, if any."""
    if connection is None:
        return None
    if auth_mode(connection) == AUTH_PASSWORD:
        return connection.token_ciphertext
    if getattr(connection, "export_status", None) == "connected":
        return getattr(connection, "export_token_ciphertext", None)
    return None


def workout_export_available(connection: GarminConnection | None) -> bool:
    """True when workouts can be written: Garmin login, or API key plus export login."""
    return bool(connection and connection.status == "connected" and workout_token(connection))


async def workout_gateway_from_connection(connection: GarminConnection) -> tuple[GarminWorkoutGateway, Garmin]:
    token = workout_token(connection)
    if not token:
        if auth_mode(connection) != AUTH_PASSWORD:
            raise WorkoutExportNeedsLogin()
        raise RuntimeError("Garmin connection has no token")
    client = Garmin()
    await asyncio.to_thread(client.login, SecretBox().decrypt(token))
    return GarminWorkoutGateway(client), client


def store_workout_token(connection: GarminConnection, client: Garmin) -> None:
    """Persist refreshed login tokens after a workout write in the right column."""
    encrypted = SecretBox().encrypt(client.client.dumps())
    if auth_mode(connection) == AUTH_PASSWORD:
        connection.token_ciphertext = encrypted
    else:
        # Never overwrite the cached Personal API bearer token with OAuth tokens.
        connection.export_token_ciphertext = encrypted


def serialize_refreshed_token(client) -> str:
    if getattr(client, "kind", None) == AUTH_PERSONAL_API:
        return SecretBox().encrypt(client.dumps())
    return SecretBox().encrypt(client.client.dumps())
