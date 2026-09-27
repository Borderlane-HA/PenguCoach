from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def user_zone(user):
    try:
        return ZoneInfo(getattr(user, "timezone", None) or "Europe/Berlin")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def user_today(user) -> date:
    return datetime.now(user_zone(user)).date()


def day_start(day: date, user) -> datetime:
    return datetime.combine(day, time.min, tzinfo=user_zone(user)).astimezone(timezone.utc)
