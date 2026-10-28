from pathlib import Path

PAGE = Path("apps/web/app/health/page.tsx")
INSIGHTS = Path("apps/web/lib/healthInsights.ts")


def test_health_periods_are_a_compact_rolling_choice():
    # alpha.83 replaced the dropdown with a segmented control of rolling windows,
    # so the first and second half of every period can be compared fairly.
    insights = INSIGHTS.read_text()
    for value in ('id:"7"', 'id:"30"', 'id:"90"', 'id:"180"', 'id:"365"', 'id:"all"'):
        assert value in insights
    assert 'role="radiogroup"' in PAGE.read_text()


def test_health_summary_cards_average_available_values_only():
    insights = INSIGHTS.read_text()
    assert "export function summarize" in insights
    assert "Number.isFinite" in insights


def test_periods_translate_to_rolling_day_query_without_api_breakage():
    page = PAGE.read_text()
    assert 'const suffix=p.days===0?"?all=true":`?days=${p.days}`' in page


def test_current_body_cards_are_not_mislabelled_as_period_average():
    page = PAGE.read_text()
    assert 'className="period-badge">{bi(lang,"Aktuell","Current")}' in page
    assert "body_latest" in page
