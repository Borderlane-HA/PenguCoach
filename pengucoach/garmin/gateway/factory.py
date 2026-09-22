import asyncio

from garminconnect import Garmin

from pengucoach.db.models import GarminConnection
from pengucoach.garmin.gateway.read_only import GarminReadOnlyGateway
from pengucoach.garmin.gateway.workouts import GarminWorkoutGateway
from pengucoach.security.crypto import SecretBox


async def gateway_from_connection(connection: GarminConnection) -> tuple[GarminReadOnlyGateway, Garmin]:
    if not connection.token_ciphertext:
        raise RuntimeError("Garmin connection has no token")
    token_blob = SecretBox().decrypt(connection.token_ciphertext)
    client = Garmin()
    await asyncio.to_thread(client.login, token_blob)
    return GarminReadOnlyGateway(client), client


async def workout_gateway_from_connection(connection: GarminConnection) -> tuple[GarminWorkoutGateway, Garmin]:
    if not connection.token_ciphertext:
        raise RuntimeError("Garmin connection has no token")
    token_blob = SecretBox().decrypt(connection.token_ciphertext)
    client = Garmin()
    await asyncio.to_thread(client.login, token_blob)
    return GarminWorkoutGateway(client), client


def serialize_refreshed_token(client: Garmin) -> str:
    return SecretBox().encrypt(client.client.dumps())
