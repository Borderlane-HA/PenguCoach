from pathlib import Path
import json
import tomllib


def test_alpha461_versions_and_display_fallback():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    package = json.loads(Path("apps/web/package.json").read_text())
    assert project["project"]["version"] == "0.1.0-alpha.83"
    assert package["version"] == "0.1.0-alpha.83"
    config = Path("pengucoach/common/config.py").read_text()
    about = Path("apps/web/app/settings/about/page.tsx").read_text()
    assert 'app_version: str = "0.1.0-alpha.83"' in config
    assert '0.1.0-alpha.83' in about


def test_today_hero_is_compact_and_has_no_decorative_artwork():
    # alpha.82: the hero became a compact header with greeting, plan line and one settings button.
    page = Path("apps/web/app/today/page.tsx").read_text()
    css = Path("apps/web/app/globals.css").read_text()
    assert "today-focus-hero.svg" not in page
    assert 'className="today-header"' in page and "<TodaySettings" in page
    assert "SourceOverview" not in page and "Coach frei öffnen" not in page
    assert ".today-header{" in css and ".today-grid{" in css


def test_checkin_controls_are_theme_safe_and_explained():
    companion = Path("apps/web/components/DailyCompanion.tsx").read_text()
    css = Path("apps/web/app/globals.css").read_text()
    assert 'bi(lang,"Verfügbare Zeit heute","Available time today")' in companion
    assert 'Wie viel Zeit hast du heute realistisch für Training oder Bewegung?' in companion
    assert 'Wie fit fühlst du dich heute?' in companion
    assert 'Wie stark merkst du die letzte Belastung?' in companion
    assert 'className={`energy-choice ${active?"active":""}`}' in companion
    assert 'className={`choice-chip ${active?"active":""}`}' in companion
    assert ".energy-scale button.energy-choice{color:var(--text)!important" in css
    assert "button.choice-chip{color:var(--text)!important" in css
    assert "button.choice-chip.active{color:var(--accent-strong)!important" in css
