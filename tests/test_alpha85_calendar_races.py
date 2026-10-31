"""alpha.85: calendar (heatmap, streaks, moving/cancelling sessions, iCalendar feed), race mode, Node.js 22 move."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from pengucoach.coach import races
from pengucoach.coach.calendar_view import active_week_streaks, ics_calendar, step_goal_streaks
from pengucoach.coach.companion import scheduled_sessions
from pengucoach.coach.today import TODAY_CARDS, today_preferences
from pengucoach.training_plan.calendar import select_session_rows
from pengucoach.training_plan.structured import TrainingPlanDocument, TrainingSession

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"
TODAY = date(2026, 10, 31)  # a Saturday


def d(text):
    return date.fromisoformat(text)


def test_active_weeks_ignore_rest_days_and_the_unfinished_week():
    days = [d("2026-10-05"), d("2026-10-07"), d("2026-10-13"), d("2026-10-15"), d("2026-10-20"), d("2026-10-23"), d("2026-10-29")]
    value = active_week_streaks(days, TODAY, minimum=2)
    assert value["current"] == 3 and value["best"] == 3 and value["this_week_days"] == 1
    assert active_week_streaks(days + [d("2026-10-31")], TODAY)["current"] == 4  # this week reached now counts


def test_step_streak_counts_today_only_when_reached():
    steps = {TODAY - timedelta(days=i): 9000 for i in range(1, 5)} | {TODAY: 3000, TODAY - timedelta(days=6): 9000}
    value = step_goal_streaks(steps, lambda _d: 8000, TODAY)
    assert value["current"] == 4 and value["best"] == 4
    steps[TODAY] = 8500
    assert step_goal_streaks(steps, lambda _d: 8000, TODAY)["current"] == 5


def test_ics_is_valid_folded_and_escaped():
    text = ics_calendar([
        {"uid": "a", "title": "🏃 Lauf, locker; Z2", "date": d("2026-11-03"), "description": "Zeile 1\nZeile 2 " + "x" * 120},
        {"uid": "b", "title": "Intervalle", "start": datetime(2026, 11, 4, 17, 30, tzinfo=timezone.utc), "minutes": 55},
    ], name="PenguCoach")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert r"SUMMARY:🏃 Lauf\, locker\; Z2" in text and "DESCRIPTION:Zeile 1\\nZeile 2" in text
    assert "DTSTART;VALUE=DATE:20261103" in text and "DTEND;VALUE=DATE:20261104" in text
    assert "DTSTART:20261104T173000Z" in text and "DTEND:20261104T182500Z" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def race(**kw):
    base = dict(id="r", name="HM", date=d("2026-12-20"), sport="running", distance_km=21.0975, target_seconds=6600, priority="A")
    return SimpleNamespace(**{**base, **kw})


def test_phases_and_taper_length_depend_on_distance():
    assert races.taper_days("running", 10) == 7 and races.taper_days("running", 21.1) == 10 and races.taper_days("running", 42.2) == 14
    assert races.phase(d("2026-12-20"), d("2026-12-12"), "running", 21.1)["key"] == "taper"
    assert races.phase(d("2026-12-20"), d("2026-11-25"), "running", 21.1)["key"] == "peak"
    assert races.phase(d("2026-12-20"), d("2026-10-31"), "running", 21.1)["key"] == "build"
    assert races.phase(d("2026-12-20"), d("2026-08-01"), "running", 21.1)["key"] == "base"
    assert races.phase(d("2026-12-20"), d("2026-12-20"), "running", 21.1)["key"] == "race"
    assert races.phase(d("2026-12-20"), d("2026-12-22"), "running", 21.1)["key"] == "done"


def run(km, minutes, day, sport="running"):
    return SimpleNamespace(id=f"{km}-{day}", sport_type=sport, started_at=datetime.fromisoformat(f"{day}T08:00:00+00:00"),
                           distance_m=km * 1000, moving_seconds=minutes * 60, duration_seconds=minutes * 60, name="Lauf")


def test_prognosis_uses_fast_recent_long_enough_runs():
    acts = [run(10, 50, "2026-10-20"), run(12, 66, "2026-10-10"), run(3, 12, "2026-10-25"), run(15, 75, "2026-06-01")]
    p = races.prognosis(race(), acts, TODAY)
    assert p["basis_count"] == 2  # 3 km too short, June too old
    riegel = 50 * 60 * (21.0975 / 10) ** 1.06
    assert abs(p["low_seconds"] - riegel * 0.99) < 2 and p["low_seconds"] < p["high_seconds"]
    assert p["target_reachable"] is True  # ~1:49 projected, target 1:50
    assert races.prognosis(race(sport="hiking"), acts, TODAY) is None


def test_result_finds_the_race_recording():
    acts = [run(21.1, 108, "2026-12-20"), run(5, 30, "2026-12-20")]
    r = races.result(race(), acts)
    assert r["distance_km"] == 21.1 and r["target_delta_seconds"] == 108 * 60 - 6600


def test_taper_proposal_shortens_keeps_intensity_and_cancels_race_day():
    sessions = [
        {"id": "a", "date": "2026-12-05", "name": "Long", "duration_min": 120},
        {"id": "b", "date": "2026-12-12", "name": "Intervals", "duration_min": 60,
         "steps": [{"type": "warmup", "duration_seconds": 900}, {"type": "repeat", "repeat": 6, "steps": [{"type": "interval", "distance_meters": 800}]}]},
        {"id": "c", "date": "2026-12-18", "name": "Easy", "duration_min": 50},
        {"id": "d", "date": "2026-12-19", "name": "Shakeout", "duration_min": 40},
        {"id": "e", "date": "2026-12-20", "name": "Long", "duration_min": 130},
    ]
    changes = {c["session_id"]: c for c in races.taper_proposal(race(), sessions, d("2026-12-01"))}
    assert "a" not in changes  # before the 10-day window
    assert changes["b"]["after_minutes"] == 35 and changes["b"]["update"]["steps"][1]["repeat"] == 4
    assert changes["b"]["update"]["steps"][0]["duration_seconds"] == 540
    assert changes["b"]["update"]["steps"][1]["steps"][0]["distance_meters"] == 800  # interval length stays
    assert changes["c"]["after_minutes"] == 20 and changes["d"]["after_minutes"] == 15
    assert changes["e"]["action"] == "skip"
    assert not races.taper_proposal(race(), sessions, d("2026-12-21"))


def test_plan_context_tells_the_generator_where_the_race_is():
    value = races.plan_context(race(), d("2026-10-05"), 12)
    assert value["race_week_in_plan"] == 11 and value["taper_days"] == 10
    assert value["phases_by_week"]["taper_from_week"] <= 10 and "backwards" in value["instruction"]


def plan_run():
    sessions = [{"id": f"s{i}", "week": 1, "day": i, "name": f"S{i}", "sport": "running", "duration_min": 30} for i in (1, 3, 5)]
    plan = TrainingPlanDocument.model_validate({"title": "P", "weeks": 1, "sessions": sessions})
    return SimpleNamespace(metadata_json={"structured_plan": plan.model_dump(mode="json")}), plan


def test_cancelled_sessions_leave_plans_exports_and_comparisons():
    run_, plan = plan_run()
    schedule = SimpleNamespace(start_date=d("2026-11-02"), overrides={"s3": {**plan.sessions[1].model_dump(), "skipped": True}})
    assert [s["id"] for s in scheduled_sessions(run_, schedule)] == ["s1", "s5"]
    assert [s["id"] for s in scheduled_sessions(run_, schedule, include_skipped=True)] == ["s1", "s3", "s5"]
    rows = [TrainingSession.model_validate(schedule.overrides.get(s.id) or s.model_dump()) for s in plan.sessions]
    assert [s.id for s in select_session_rows(rows, None)] == ["s1", "s5"]


def test_routes_and_wiring():
    main = (ROOT / "apps/api/main.py").read_text()
    assert "calendar.router" in main and "races.router" in main
    cal = (ROOT / "apps/api/routers/calendar.py").read_text()
    for route in ('@router.get("/overview")', '@router.get("/month")', '@router.patch("/plans/{run_id}/sessions/{session_id}")',
                  '@router.get("/export.ics")', '@router.get("/feed/{user_id}/{token}.ics")', '@router.delete("/feed")'):
        assert route in cal
    assert "hmac.compare_digest" in cal and "SecretBox().encrypt(token)" in cal
    assert "swapped_with" in cal and "EXPORTED_SESSION_LOCKED" not in cal  # guard comes from companion.guard_exported
    assert (ROOT / "db/migrations/versions/0019_race_events.py").is_file()
    assert 'context["goal"]["race"] = plan_context(' in (ROOT / "worker/tasks/ai.py").read_text()
    assert "race_id: uuid.UUID | None = None" in (ROOT / "apps/api/routers/coach.py").read_text()


def test_today_has_a_race_card_that_hides_without_a_race():
    assert TODAY_CARDS.index("race") == TODAY_CARDS.index("checkin") + 1
    old = today_preferences(SimpleNamespace(dashboard_config={"today": {"order": [k for k in TODAY_CARDS if k != "race"]}}))
    assert old["order"].index("race") == old["order"].index("checkin") + 1
    page = (WEB / "app/today/page.tsx").read_text()
    assert 'race:raceQuery.data?.race?<RaceCountdown' in page and "layout.filter(({key})=>blocks[key]!=null)" in page


def test_calendar_page_navigation_and_help():
    shell = (WEB / "components/AppShell.tsx").read_text()
    assert 'href:"/calendar"' in shell
    page = (WEB / "app/calendar/page.tsx").read_text()
    assert "onDrop=" in page and "draggable=" in page and "setMoving(" in page and "skipped:!session.skipped" in page
    assert "webcal:" in page and "/calendar/export.ics" in page
    help_text = (WEB / "lib/help.ts").read_text()
    assert 'id:"calendar"' in help_text and "Heimnetz" in help_text and "Tapering" in help_text


def test_node_22_is_installed_and_old_node_only_warns():
    from pengucoach.maintenance.engine import Engine
    req = json.loads((ROOT / "install/release-requirements.json").read_text())
    assert req["node_min"] == "20.0.0" and req["node_recommended"] == "22.23.4"
    engine = Engine.__new__(Engine)
    driver = SimpleNamespace(tool_versions=lambda: {"node": "20.19.2", "python": "3.13.5"})
    checks = engine.requirement_checks(driver, req, "0.1.0-alpha.84")
    advisory = next(c for c in checks if c["key"] == "node_recommended")
    assert advisory["ok"] is False and advisory["advisory"] is True
    assert all(c["ok"] for c in checks if not c.get("advisory"))
    step = (ROOT / "install/host-steps/085-nodejs-22.native.sh").read_text()
    assert "setup_22.x" in step and "exit 0" in step and 'WANT="22.23.4"' in step
    installer = (ROOT / "install/proxmox/install-app.sh").read_text()
    assert '"22.23.4"' in installer and "setup_22.x" in installer
