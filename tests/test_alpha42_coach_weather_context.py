import asyncio
from pathlib import Path
from types import SimpleNamespace

from pengucoach.llm.service import context_evidence
from pengucoach.weather import service as weather

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_coach_weather_classifier_is_relevant_not_global():
    assert weather.coach_weather_relevant("Was sagt das Wetter die Tage?")
    assert weather.coach_weather_relevant("Was soll ich heute trainieren?")
    assert weather.coach_weather_relevant("Soll ich morgen Rennrad fahren?")
    assert weather.coach_weather_relevant("Wann wäre diese Woche ein guter Tag zum Laufen?")
    assert weather.coach_weather_relevant("Ich habe heute nur 30 Minuten.")
    assert not weather.coach_weather_relevant("Wie war meine Trainingswoche?")
    assert not weather.coach_weather_relevant("Wie hat sich meine HRV entwickelt?")
    assert not weather.coach_weather_relevant("Wie war das Wetter gestern?")


def test_coach_weather_context_is_bounded_opt_out_and_failure_safe(monkeypatch):
    pref = SimpleNamespace(
        dashboard_config={
            "weather": {
                "enabled": True,
                "location_name": "Test City",
                "latitude": 48.7,
                "longitude": 11.4,
                "timezone": "Europe/Berlin",
                "include_in_training_plans": True,
                "include_in_coach": True,
            }
        }
    )

    class DB:
        async def get(self, _model, _id):
            return pref

    seen = {}

    async def ok(_lat, _lon, _tz, days):
        seen["days"] = days
        return {
            "available": True,
            "provider": "Open-Meteo",
            "current": {"temperature_2m": 14.1, "wind_speed_10m": 20.0},
            "daily": [{"date": "2026-09-28"}],
            "fetched_at": "2026-09-28T05:00:00Z",
        }

    monkeypatch.setattr(weather, "fetch_forecast", ok)
    result = asyncio.run(weather.build_coach_weather_context(DB(), SimpleNamespace(id="u"), "Was soll ich heute trainieren?"))
    assert seen["days"] == 8
    assert result["available"] is True
    assert result["location"] == "Test City"
    assert result["forecast_limit_days"] == 8

    assert asyncio.run(weather.build_coach_weather_context(DB(), SimpleNamespace(id="u"), "Wie war meine Trainingswoche?")) is None

    pref.dashboard_config["weather"]["include_in_coach"] = False
    assert asyncio.run(weather.build_coach_weather_context(DB(), SimpleNamespace(id="u"), "Wie ist das Wetter morgen?")) is None
    pref.dashboard_config["weather"]["include_in_coach"] = True

    async def fail(*_args, **_kwargs):
        raise weather.httpx.ConnectError("offline")

    monkeypatch.setattr(weather, "fetch_forecast", fail)
    failed = asyncio.run(weather.build_coach_weather_context(DB(), SimpleNamespace(id="u"), "Soll ich morgen laufen?"))
    assert failed["available"] is False
    assert "Do not invent" in failed["note"]


def test_weather_and_readiness_are_exposed_in_answer_evidence():
    evidence = context_evidence(
        {
            "from": "2026-09-22",
            "to": "2026-09-28",
            "data_inventory": {"activity_count": 2, "health_days": 7, "sleep_days": 7, "hrv_days": 6},
            "training_zones": {"running": {}},
            "personal_coaching": {
                "upcoming_sessions": [{"date": "2026-09-28"}],
                "readiness": {"score": 67, "status": "yellow", "available_factors": 5},
            },
            "weather_forecast": {
                "available": True,
                "provider": "Open-Meteo",
                "location": "Test City",
                "fetched_at": "2026-09-28T05:00:00Z",
                "current": {"temperature_2m": 14.1, "wind_speed_10m": 20.0},
                "daily": [{"date": "2026-09-28"}, {"date": "2026-09-29"}],
            },
        }
    )
    assert evidence["weather"]["location"] == "Test City"
    assert evidence["weather"]["forecast_days"] == 2
    assert evidence["readiness"]["score"] == 67
    assert evidence["upcoming_sessions"] == 1
    assert evidence["training_zones"] is True


def test_coach_ui_has_real_desktop_settings_toggle_and_weather_transparency():
    page = text("apps/web/app/coach/page.tsx")
    css = text("apps/web/app/globals.css")
    settings = text("apps/web/app/settings/weather/page.tsx")
    api = text("apps/api/routers/coach.py")
    worker = text("worker/tasks/ai.py")
    assert "pengucoach_coach_settings_collapsed" in page
    assert "settings-collapsed" in page and "settings-collapsed" in css
    assert 'id="coach-ai-settings"' in page
    assert "message-context-chips" in page and "Wetterkontext" in page
    assert "include_in_coach" in settings
    assert "build_coach_weather_context" in api and "build_coach_weather_context" in worker
