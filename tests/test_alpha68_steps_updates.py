from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from test_alpha61_continuation import data  # noqa: F401
from apps.api.routers import health, settings
from pengucoach.common import releases
from pengucoach.db.models import DailyHealth, User, UserPreference
from pengucoach.health import steps

TODAY = date(2026, 10, 18)


def config(target=8000, adaptive=False):
    return {"configured": True, "daily_target": target, "adaptive": adaptive,
            "history": [{"from": "2026-09-01", "target": target}]}


def rows(values):
    return [SimpleNamespace(date=TODAY - timedelta(days=i + 1), steps=value) for i, value in enumerate(values)]


def test_period_progress_uses_actual_goals_and_known_days():
    cfg = config()
    cfg["history"].append({"from": "2026-10-16", "target": 10000})
    result = steps.summarize_steps(rows([10000, 5000, None, 8000]), cfg, today=TODAY, period_days=7)
    assert result["recorded_days"] == 3 and result["period_days"] == 7
    assert result["total_steps"] == 23000 and result["goal_total"] == 28000
    assert result["percent"] == 82.1 and result["achieved_days"] == 2


def test_zero_is_a_recorded_day_unknown_and_future_are_excluded():
    result = steps.summarize_steps(rows([0, None]) + [SimpleNamespace(date=TODAY+timedelta(days=1), steps=8000)], config(), today=TODAY)
    assert result["percent"] == 0 and result["recorded_days"] == 1
    assert steps.summarize_steps(rows([None]), config(), today=TODAY)["percent"] is None
    assert steps.summarize_steps(rows([16000]), config(), today=TODAY)["percent"] == 200


def test_unconfigured_goal_is_not_an_invented_target():
    cfg = steps.goal_config(None)
    assert not cfg["configured"]
    assert steps.summarize_steps(rows([8000]), cfg, today=TODAY)["percent"] is None


def test_first_target_is_an_explicit_reference_for_older_days():
    cfg = config()
    cfg["history"] = [{"from": TODAY.isoformat(), "target": 8000}]
    result = steps.summarize_steps(rows([8000, 8000]), cfg, today=TODAY)
    assert result["reference_days"] == 2 and result["percent"] == 100


@pytest.mark.parametrize("values,direction,target", [([9000]*14, "up", 8500), ([2000]*14, "down", 7250)])
def test_optional_suggestions_are_small_and_exclude_incomplete_today(values, direction, target):
    cfg = config(adaptive=True)
    suggestion = steps.goal_suggestion(rows(values)+[SimpleNamespace(date=TODAY, steps=0)], cfg, TODAY)
    assert suggestion["direction"] == direction and suggestion["daily_target"] == target
    assert suggestion["recorded_days"] == 14
    assert cfg["daily_target"] == 8000


def test_suggestions_need_coverage_and_settling_time():
    cfg = config(adaptive=True)
    assert steps.goal_suggestion(rows([9000]*9), cfg, TODAY) is None
    assert steps.goal_suggestion(rows([9000]*5+[None]*9), cfg, TODAY) is None
    cfg["history"][-1]["from"] = "2026-10-17"
    assert steps.goal_suggestion(rows([9000]*14), cfg, TODAY) is None
    assert steps.goal_suggestion(rows([9000]*14), config(adaptive=False), TODAY) is None


@pytest.mark.parametrize("target", [0, 999, 50001, 2.5, True, "8000"])
def test_invalid_target_is_rejected(target):
    with pytest.raises(ValidationError):
        settings.StepGoalIn(daily_target=target)


async def test_goal_save_is_owned_persistent_and_preserves_history_and_other_settings(data, monkeypatch):
    factory, uid, _, _ = data
    monkeypatch.setattr(settings, "user_today", lambda user: TODAY)
    monkeypatch.setattr(steps, "user_today", lambda user: TODAY)
    async with factory() as db:
        user = await db.get(User, uid)
        pref = await db.get(UserPreference, uid)
        pref.dashboard_config = {"today": {"hidden": ["weather"]}, "step_goal": config()}
        await db.commit()
        result = await settings.save_step_goal(settings.StepGoalIn(daily_target=10000, adaptive=True), user, db)
        assert result["daily_target"] == 10000 and result["adaptive"]
        assert result["history"] == [{"from": "2026-09-01", "target": 8000}, {"from": "2026-10-18", "target": 10000}]
        await settings.save_step_goal(settings.StepGoalIn(daily_target=9000), user, db)
        await db.refresh(pref)
        assert pref.dashboard_config["today"] == {"hidden": ["weather"]}
        assert len(pref.dashboard_config["step_goal"]["history"]) == 2
        assert steps.target_on(steps.goal_config(pref), TODAY-timedelta(days=1)) == 8000


async def test_lightweight_today_does_not_calculate_vo2_history(data, monkeypatch):
    factory, uid, _, _ = data
    monkeypatch.setattr(health, "user_today", lambda user: TODAY)
    heavy = AsyncMock(side_effect=AssertionError("VO2 history on critical path"))
    monkeypatch.setattr(health, "_vo2_payload", heavy)
    async with factory() as db:
        pref = await db.get(UserPreference, uid)
        pref.dashboard_config = {"step_goal": config()}
        db.add(DailyHealth(user_id=uid, date=TODAY, steps=4000))
        await db.commit()
        result = await health.today(await db.get(User, uid), db, include_vo2=False)
        assert result["steps"] == 4000 and result["step_goal"]["percent"] == 50
        heavy.assert_not_called()


@pytest.mark.parametrize("bad", ["red", "#fff", "#123456;background:url(test)", "#00000000"])
def test_custom_theme_only_accepts_six_digit_colors(bad):
    with pytest.raises(ValidationError):
        settings.CustomThemeIn(accent=bad)


async def test_custom_theme_round_trip_preserves_assets_and_goal(data):
    factory, uid, _, _ = data
    async with factory() as db:
        pref = await db.get(UserPreference, uid)
        pref.dashboard_config = {"step_goal": config(), "avatar_file": "avatar.png"}
        await db.commit()
        user = await db.get(User, uid)
        payload = settings.AppearanceIn(theme="custom", custom_theme=settings.CustomThemeIn(mode="dark", accent="#af72d9"))
        saved = await settings.update_appearance(payload, user, db)
        assert saved["theme"] == "custom" and saved["custom_theme"]["accent"] == "#af72d9" and saved["has_avatar"]
        await settings.update_appearance(settings.AppearanceIn(theme="alpine"), user, db)
        restored = await settings.update_appearance(settings.AppearanceIn(theme="custom"), user, db)
        assert restored["custom_theme"]["accent"] == "#af72d9"
        assert (await db.get(UserPreference, uid)).dashboard_config["step_goal"] == config()


def release(version, **kw):
    return {"tag_name": version, "html_url": releases.RELEASES_URL+"/tag/"+version, **kw}


def test_release_comparison_handles_alpha_numbers_and_patch_components():
    assert releases.version_key("v0.1.0-alpha.68") > releases.version_key("0.1.0-alpha.9")
    assert releases.version_key("0.1.0-alpha.46.1") > releases.version_key("0.1.0-alpha.46")
    assert releases.version_key("0.1.0") > releases.version_key("0.1.0-rc.99")
    assert releases.version_key("main") is None


def test_release_selection_does_not_trust_order_drafts_or_other_urls():
    items = [release("v0.1.0-alpha.9"), release("v0.1.0-alpha.69", draft=True), release("v0.1.0-alpha.68", prerelease=True), release("v9.0.0", html_url="https://other.test/tag")]
    result = releases.select_release(items, "0.1.0-alpha.67")
    assert result["status"] == "available" and result["latest_version"] == "v0.1.0-alpha.68"
    assert releases.select_release(items, "0.1.0-alpha.68")["status"] == "current"
    assert releases.select_release(items, "0.1.0")["status"] == "unknown"
    assert releases.select_release(items, "dev")["status"] == "unknown"


async def test_release_fetch_is_anonymous_bounded_cached_and_failure_safe(monkeypatch):
    releases._cache.clear()
    client = httpx.AsyncClient
    seen = []
    def handler(request):
        seen.append(request)
        assert "authorization" not in request.headers
        assert request.url.params["per_page"] == "100"
        return httpx.Response(200, json=[release("v0.1.0-alpha.68", prerelease=True)], headers={"etag": '"release-68"'})
    monkeypatch.setattr(releases.httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(handler)))
    assert (await releases.update_status("0.1.0-alpha.67"))["status"] == "available"
    assert (await releases.update_status("0.1.0-alpha.68"))["status"] == "current"
    assert len(seen) == 1
    releases._cache.clear()
    def offline(request):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(releases.httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(offline)))
    assert (await releases.update_status("0.1.0-alpha.67"))["status"] == "unavailable"
    releases._cache.clear()


async def test_release_etag_and_stale_failure_keep_last_known_release(monkeypatch):
    releases._cache.clear()
    releases._cache.update(items=[release("v0.1.0-alpha.68", prerelease=True)], etag='"release-68"', expires=0)
    client = httpx.AsyncClient
    def unchanged(request):
        assert request.headers["If-None-Match"] == '"release-68"'
        return httpx.Response(304)
    monkeypatch.setattr(releases.httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(unchanged)))
    result = await releases.update_status("0.1.0-alpha.67")
    assert result["status"] == "available" and result["stale"] is False
    releases._cache["expires"] = 0
    def failed(request):
        return httpx.Response(503)
    monkeypatch.setattr(releases.httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(failed)))
    result = await releases.update_status("0.1.0-alpha.67")
    assert result["status"] == "available" and result["stale"] is True
    releases._cache.clear()
