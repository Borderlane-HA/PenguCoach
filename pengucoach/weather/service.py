from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import User, UserPreference

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "precipitation_probability_max",
    "precipitation_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "uv_index_max",
    "sunrise",
    "sunset",
)
CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "wind_gusts_10m",
)


def default_weather_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "location_name": "",
        "latitude": None,
        "longitude": None,
        "timezone": "auto",
        "country_code": "",
        "admin1": "",
        "include_in_training_plans": True,
        "include_in_coach": True,
    }


def weather_config(pref: UserPreference | None) -> dict[str, Any]:
    cfg = dict(pref.dashboard_config or {}) if pref else {}
    raw = cfg.get("weather") if isinstance(cfg.get("weather"), dict) else {}
    return {**default_weather_config(), **raw}


async def search_locations(query: str, language: str = "de") -> list[dict[str, Any]]:
    params = {"name": query.strip(), "count": 8, "language": language[:2].lower(), "format": "json"}
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(GEOCODING_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "elevation": row.get("elevation"),
            "timezone": row.get("timezone") or "auto",
            "country": row.get("country"),
            "country_code": row.get("country_code") or "",
            "admin1": row.get("admin1") or "",
        }
        for row in rows
        if row.get("name") and row.get("latitude") is not None and row.get("longitude") is not None
    ]


async def fetch_forecast(latitude: float, longitude: float, timezone: str = "auto", days: int = 16) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone or "auto",
        "forecast_days": max(1, min(16, int(days))),
        "current": ",".join(CURRENT_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(FORECAST_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    daily = payload.get("daily") if isinstance(payload, dict) else None
    units = payload.get("daily_units") if isinstance(payload, dict) else None
    dates = daily.get("time") if isinstance(daily, dict) else None
    rows: list[dict[str, Any]] = []
    if isinstance(dates, list):
        for index, day in enumerate(dates):
            item: dict[str, Any] = {"date": day}
            for field in DAILY_FIELDS:
                values = daily.get(field)
                item[field] = values[index] if isinstance(values, list) and index < len(values) else None
            rows.append(item)
    return {
        "available": True,
        "provider": "Open-Meteo",
        "provider_url": "https://open-meteo.com/",
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "timezone": payload.get("timezone") or timezone,
        "timezone_abbreviation": payload.get("timezone_abbreviation"),
        "current": payload.get("current") or {},
        "current_units": payload.get("current_units") or {},
        "daily": rows,
        "daily_units": units or {},
        "fetched_at": datetime.now(dt_timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


async def build_training_weather_context(
    db: AsyncSession,
    user: User,
    *,
    include: bool | None = None,
    plan_start_date: date | None = None,
) -> dict[str, Any] | None:
    pref = await db.get(UserPreference, user.id)
    config = weather_config(pref)
    should_include = config.get("include_in_training_plans", True) if include is None else bool(include)
    if not should_include or not config.get("enabled"):
        return None
    latitude = config.get("latitude")
    longitude = config.get("longitude")
    if latitude is None or longitude is None:
        return None
    try:
        result = await fetch_forecast(float(latitude), float(longitude), str(config.get("timezone") or "auto"), 16)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "available": False,
            "provider": "Open-Meteo",
            "location": config.get("location_name") or "",
            "plan_start_date": plan_start_date.isoformat() if plan_start_date else None,
            "note": f"Weather forecast unavailable at generation time ({type(exc).__name__}). Continue without weather assumptions.",
        }
    result["location"] = config.get("location_name") or ""
    result["plan_start_date"] = plan_start_date.isoformat() if plan_start_date else None
    result["forecast_limit_days"] = 16
    result["planning_note"] = (
        "Use only listed calendar dates. Weather is short-range context, not a promise. "
        "Never infer weather for plan dates outside this forecast."
    )
    return result


def coach_weather_relevant(message: str) -> bool:
    """Return whether short-range weather can materially improve a Coach answer.

    The classifier is deliberately deterministic and conservative: explicit weather
    questions always qualify, while training questions require either a near-term
    date reference or recommendation/decision wording. This avoids spending context
    on weather for retrospective questions such as "How was my training week?".
    """
    import re

    text = " ".join(str(message or "").casefold().split())
    if not text:
        return False

    past_terms = ("wie war", "how was", "gestern", "yesterday", "letzte woche", "last week", "letzten monat", "last month")
    if any(term in text for term in past_terms):
        return False

    weather_terms = (
        "wetter", "weather", "regen", "rain", "wind", "sturm", "storm",
        "gewitter", "thunder", "temperatur", "temperature", "hitze", "heat",
        "kälte", "kaelte", "cold", "schnee", "snow", "uv", "vorhersage", "forecast",
    )
    if any(term in text for term in weather_terms):
        return True

    activity_terms = (
        "train", "lauf", "run", "jogg", "rennrad", "radfahr", "cycling", "bike",
        "wander", "hiking", "walk", "gehen", "outdoor", "intervall", "interval",
        "long run", "longrun",
    )
    limited_time = bool(re.search(r"\b(?:nur|only)\s+\d{1,3}\s*(?:minuten|minutes)\b", text))
    if not any(term in text for term in activity_terms) and not limited_time:
        return False

    near_term = (
        "heute", "today", "morgen", "tomorrow", "übermorgen", "uebermorgen",
        "day after tomorrow", "wochenende", "weekend", "kommenden tage",
        "nächsten tage", "naechsten tage", "next days", "diese woche", "this week",
        "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    )
    decision_terms = (
        "was soll", "soll ich", "sollte ich", "kann ich", "wann", "welcher tag",
        "welchen tag", "empfiehl", "empfehl", "beste tag", "bester tag",
        "what should", "should i", "can i", "when", "which day", "recommend", "best day",
    )
    return any(term in text for term in near_term) or any(term in text for term in decision_terms) or limited_time or bool(
        re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text)
    )


async def build_coach_weather_context(
    db: AsyncSession,
    user: User,
    message: str,
    *,
    days: int = 8,
) -> dict[str, Any] | None:
    """Fetch bounded Open-Meteo context only when the current Coach question needs it."""
    pref = await db.get(UserPreference, user.id)
    config = weather_config(pref)
    if not config.get("enabled") or not config.get("include_in_coach", True):
        return None
    if not coach_weather_relevant(message):
        return None
    latitude = config.get("latitude")
    longitude = config.get("longitude")
    if latitude is None or longitude is None:
        return None
    forecast_days = max(1, min(8, int(days)))
    try:
        result = await fetch_forecast(
            float(latitude), float(longitude), str(config.get("timezone") or "auto"), forecast_days
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "available": False,
            "provider": "Open-Meteo",
            "location": config.get("location_name") or "",
            "forecast_limit_days": forecast_days,
            "note": (
                f"Weather was relevant to this Coach question but unavailable at answer time "
                f"({type(exc).__name__}). Do not invent current conditions or a forecast."
            ),
        }
    result["location"] = config.get("location_name") or ""
    result["forecast_limit_days"] = forecast_days
    result["planning_note"] = (
        "Use only the supplied current conditions and listed forecast dates. Treat forecasts as uncertain. "
        "Never claim weather access beyond this supplied snapshot and never invent weather for other dates."
    )
    return result
