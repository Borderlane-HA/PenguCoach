from datetime import datetime, timedelta, timezone

import jwt

from pengucoach.common.config import settings
from pengucoach.safety.notice import NOTICE_VERSION


def create_session_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "typ": "session", "iat": now, "exp": now + timedelta(days=settings.session_days)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def create_safety_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "typ": "safety", "notice": NOTICE_VERSION, "iat": now, "exp": now + timedelta(days=settings.session_days)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_token(token: str, expected_type: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def decode_session_token(token: str) -> str:
    return str(decode_token(token, "session")["sub"])

def valid_safety_token(token: str | None, user_id: str) -> bool:
    if not token:
        return False
    try:
        payload = decode_token(token, "safety")
    except jwt.PyJWTError:
        return False
    return str(payload.get("sub")) == user_id and payload.get("notice") == NOTICE_VERSION
