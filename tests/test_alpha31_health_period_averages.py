from pathlib import Path


def test_health_period_menu_uses_calendar_friendly_choices():
    page = Path("apps/web/app/health/page.tsx").read_text()
    for value in ("today", "last7", "week", "month", "year", "all"):
        assert f'<option value="{value}">' in page
    for label in ("Heute", "Letzte 7 Tage", "Diese Woche", "Dieser Monat", "Dieses Jahr", "Alle"):
        assert label in page
    assert 'const[period,setPeriod]=useState("last7")' in page


def test_health_summary_cards_average_available_values_only():
    page = Path("apps/web/app/health/page.tsx").read_text()
    assert "function metricValues" in page
    assert 'if(raw===null||raw===undefined||raw==="")continue' in page
    assert "if(Number.isFinite(value))values.push(value)" in page
    assert "function metricAverage" in page
    assert 'metricAverage(data.health??[],"hydration_ml")' in page
    assert 'metricAverage(data.health??[],"steps")' in page
    assert 'metricAverage(data.sleep??[],"duration_seconds")' in page
    assert 'metricAverage(data.hrv??[],"overnight_average")' in page
    assert '`${bi(lang,"Ø aus","Avg of")} ${count} ${unit}' in page


def test_calendar_periods_translate_to_rolling_day_query_without_api_breakage():
    page = Path("apps/web/app/health/page.tsx").read_text()
    assert 'if(period==="today")return 1' in page
    assert 'if(period==="last7")return 7' in page
    assert 'if(period==="week")return ((now.getDay()+6)%7)+1' in page
    assert 'if(period==="month")return now.getDate()' in page
    assert 'Date.UTC(now.getFullYear(),0,1)' in page
    assert 'const suffix=period==="all"?"?all=true":`?days=${periodDays(period)}`' in page


def test_current_body_cards_are_not_mislabelled_as_period_average():
    page = Path("apps/web/app/health/page.tsx").read_text()
    assert 'className="period-badge">{bi(lang,"Aktuell","Current")}' in page
    assert "body_latest" in page
