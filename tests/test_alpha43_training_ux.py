from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_training_page_uses_guided_progressive_disclosure():
    page = text("apps/web/app/training/page.tsx")
    assert "Trainingsplan-Assistent" in page
    assert "planner-stepper" in page
    assert "Ziel" in page and "Rahmen" in page and "Daten" in page and "Prüfen" in page
    assert "Erweiterte KI-Einstellungen" in page
    assert "planner-context-summary" in page
    assert "Was möchtest du machen?" in page


def test_existing_plans_start_collapsed_and_are_explicitly_opened():
    page = text("apps/web/app/training/page.tsx")
    assert "setPlanOpen(false)" in page
    assert "Beim Öffnen dieser Seite bleiben alle Pläne bewusst eingeklappt." in page
    assert "Plan öffnen" in page
    assert 'planOpen&&result' in page
    assert '<details className="training-calendar-details"' in page
    assert '<details className="training-plan-section">' in page


def test_calendar_adds_collapsed_week_level_between_plan_and_session():
    calendar = text("apps/web/components/TrainingPlanCalendar.tsx")
    assert "expandedWeeks" in calendar
    assert "setExpandedWeeks(new Set())" in calendar
    assert "toggleWeek" in calendar
    assert 'aria-expanded={weekOpen}' in calendar
    assert 'weekOpen&&<div className="training-week-grid">' in calendar
    assert 'aria-expanded={expanded.has(session.id)}' in calendar


def test_training_planner_has_phone_specific_layouts():
    css = text("apps/web/app/globals.css")
    assert "Alpha.43 Guided Training Planner" in css
    assert "@media(max-width:760px)" in css
    assert ".planner-stepper{grid-template-columns:repeat(2,minmax(0,1fr))}" in css
    assert ".training-assistant-actions{grid-template-columns:1fr}" in css
    assert "@media(max-width:480px)" in css
    assert ".planner-context-summary,.planner-review-grid,.planner-notes-review{grid-template-columns:1fr}" in css


def test_adaptive_coach_roadmap_stays_explicit_while_ui_is_simplified():
    roadmap = text("docs/ROADMAP.md")
    for item in [
        "Coach Memory v1",
        "Adaptive training plans",
        "Daily Readiness / traffic light",
        "Weather + training",
        "Coach chat with context",
        "Training load & trends",
        "Manual post-workout feedback",
        "Plan conflict detection",
        "AI Decision Log",
        "Coach Dashboard",
    ]:
        assert item in roadmap
    assert "progressive-disclosure" in roadmap
    assert "mobile" in roadmap.lower()
