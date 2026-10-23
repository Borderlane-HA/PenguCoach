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


async def workout_gateway_from_connection(connection: GarminConnection) -> tuple[GarminWorkoutGateway, Garmin]:
    if auth_mode(connection) != AUTH_PASSWORD:
        raise WorkoutExportNeedsLogin()
    if not connection.token_ciphertext:
        raise RuntimeError("Garmin connection has no token")
    token_blob = SecretBox().decrypt(connection.token_ciphertext)
    client = Garmin()
    await asyncio.to_thread(client.login, token_blob)
    return GarminWorkoutGateway(client), client


def serialize_refreshed_token(client) -> str:
    if getattr(client, "kind", None) == AUTH_PERSONAL_API:
        return SecretBox().encrypt(client.dumps())
    return SecretBox().encrypt(client.client.dumps())
