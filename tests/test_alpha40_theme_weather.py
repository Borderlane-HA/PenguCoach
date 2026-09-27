import asyncio
from pathlib import Path
from types import SimpleNamespace

from pengucoach.weather import service as weather

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_theme_is_restored_before_first_paint_and_cached_on_change():
    layout = text("apps/web/app/layout.tsx")
    shell = text("apps/web/components/AppShell.tsx")
    appearance = text("apps/web/app/settings/appearance/page.tsx")
    assert "pengucoach_theme" in layout
    assert "document.documentElement.dataset.theme=t" in layout
    assert "<head><script" in layout
    assert "localStorage.setItem(\"pengucoach_theme\",theme)" in shell
    assert "localStorage.setItem(\"pengucoach_theme\",theme)" in appearance


def test_theme_palette_additions_and_nordic_metric_contrast_guard():
    appearance = text("apps/web/app/settings/appearance/page.tsx")
    css = text("apps/web/app/globals.css")
    api = text("apps/api/routers/settings.py")
    for theme in ("alpine", "arctic", "espresso", "ember", "mono"):
        assert f'id:"{theme}"' in appearance
        assert f'data-theme="{theme}"' in css
        assert theme in api
    assert ".tone-steps" in css and "color-mix" in css
    assert ".health-metric-card:after{background:transparent!important" in css
    assert 'html[data-theme="slate"]' in css


def test_weather_defaults_are_private_opt_in_and_keyless():
    cfg = weather.default_weather_config()
    assert cfg["enabled"] is False
    assert cfg["include_in_training_plans"] is True
    assert cfg["latitude"] is None and cfg["longitude"] is None
    service = text("pengucoach/weather/service.py")
    assert "api.open-meteo.com/v1/forecast" in service
    assert "geocoding-api.open-meteo.com/v1/search" in service
    assert "apikey" not in service.lower()


def test_open_meteo_daily_payload_is_normalized(monkeypatch):
    payload = {
        "latitude": 48.76,
        "longitude": 11.42,
        "timezone": "Europe/Berlin",
        "current": {"temperature_2m": 18.2, "weather_code": 2},
        "current_units": {"temperature_2m": "°C"},
        "daily_units": {"temperature_2m_max": "°C"},
        "daily": {
            "time": ["2026-09-28", "2026-09-29"],
            "weather_code": [2, 61],
            "temperature_2m_max": [20.0, 17.0],
            "temperature_2m_min": [9.0, 8.0],
        },
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, params):
            assert params["forecast_days"] == 16
            assert "weather_code" in params["daily"]
            return Response()

    monkeypatch.setattr(weather.httpx, "AsyncClient", Client)
    result = asyncio.run(weather.fetch_forecast(48.76, 11.42, "Europe/Berlin", 16))
    assert result["provider"] == "Open-Meteo"
    assert len(result["daily"]) == 2
    assert result["daily"][1]["weather_code"] == 61
    assert result["daily"][0]["wind_speed_10m_max"] is None


def test_training_weather_context_is_bounded_and_failure_safe(monkeypatch):
    pref = SimpleNamespace(
        dashboard_config={
            "weather": {
                "enabled": True,
                "location_name": "Test City",
                "latitude": 48.7,
                "longitude": 11.4,
                "timezone": "Europe/Berlin",
                "include_in_training_plans": True,
            }
        }
    )

    class DB:
        async def get(self, _model, _id):
            return pref

    async def ok(*_args, **_kwargs):
        return {"available": True, "provider": "Open-Meteo", "daily": [{"date": "2026-09-28"}]}

    monkeypatch.setattr(weather, "fetch_forecast", ok)
    result = asyncio.run(
        weather.build_training_weather_context(
            DB(), SimpleNamespace(id="u"), plan_start_date=__import__("datetime").date(2026, 9, 28)
        )
    )
    assert result["forecast_limit_days"] == 16
    assert result["plan_start_date"] == "2026-09-28"
    assert "Never infer weather" in result["planning_note"]

    async def fail(*_args, **_kwargs):
        raise weather.httpx.ConnectError("offline")

    monkeypatch.setattr(weather, "fetch_forecast", fail)
    failed = asyncio.run(weather.build_training_weather_context(DB(), SimpleNamespace(id="u")))
    assert failed["available"] is False
    assert "Continue without weather assumptions" in failed["note"]


def test_training_planner_sends_plan_start_and_weather_and_requires_monday():
    page = text("apps/web/app/training/page.tsx")
    coach = text("apps/api/routers/coach.py")
    worker = text("worker/tasks/ai.py")
    llm = text("pengucoach/llm/service.py")
    assert "start_date:planStart" in page
    assert "include_weather:includeWeather" in page
    assert "function isMonday" in page
    assert "PLAN_START_MUST_BE_MONDAY" in coach
    assert '"weather_forecast"' in coach and '"weather_forecast"' in worker
    assert "never invent weather for later plan weeks" in llm
    assert "goal.start_date" in llm
