"""alpha.83: customizable Health page, value explanations, coach per value, health recap, update banner, dark-safe colours."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.routers import settings
from pengucoach.health.layout import DEFAULT_HEALTH, HEALTH_METRICS, HEALTH_PERIODS, HEALTH_SECTIONS, health_preferences

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'apps/web'


def read(rel):
    return (WEB / rel).read_text()


def prefs(raw):
    return health_preferences(SimpleNamespace(dashboard_config={'health': raw}))


def test_defaults_and_cleanup_of_saved_health_layout():
    assert health_preferences(None) == DEFAULT_HEALTH
    value = prefs({'order': ['body', 'nope', 'body'], 'hidden': [], 'metrics': ['bogus'], 'period': '13'})
    assert value['order'][0] == 'body' and sorted(value['order']) == sorted(HEALTH_SECTIONS)
    assert value['hidden'] == [] and value['metrics'] == DEFAULT_HEALTH['metrics'] and value['period'] == '30'
    assert prefs({'order': ['trends']})['hidden'] == ['coverage']


def test_settings_validation_and_endpoints():
    body = settings.HealthLayoutIn(order=['body'], hidden=['trends'], metrics=['hrv', 'sleep'], period='90')
    assert body.order[0] == 'body' and set(body.order) == set(HEALTH_SECTIONS)
    for bad in ({'metrics': []}, {'period': '2'}, {'metrics': ['hrv', 'hrv']}, {'order': ['x']}):
        with pytest.raises(ValidationError):
            settings.HealthLayoutIn(**{'order': list(HEALTH_SECTIONS), 'hidden': [], 'metrics': ['hrv'], 'period': '30', **bad})
    source = (ROOT / 'apps/api/routers/settings.py').read_text()
    assert "@router.get('/health-layout')" in source and "@router.put('/health-layout')" in source


def test_web_and_api_know_the_same_sections_metrics_and_periods():
    insights = read('lib/healthInsights.ts')
    for key in HEALTH_SECTIONS:
        assert f'key:"{key}"' in insights
    for key in HEALTH_METRICS:
        assert f'key:"{key}"' in insights
    for key in HEALTH_PERIODS:
        assert f'id:"{key}"' in insights


def test_health_page_is_customizable_explains_with_info_tips_and_talks_to_the_coach():
    page = read('app/health/page.tsx')
    tile = read('components/HealthTile.tsx')
    assert '<HealthSettings' in page and '/settings/health-layout' in read('components/HealthSettings.tsx')
    assert '<HealthRecap' in page and '<InfoTip' in page
    assert 'coachPrompt(def,s,lang,periodLabel)' in tile and '/coach?prompt=' in tile
    assert 'overviewPrompt(' in page
    # No tool talk on the page: no API, sync or parser wording.
    visible = ' '.join(re.findall(r'bi\(lang,"([^"]+)"', page))
    for word in ('API', 'Sync', 'Parquet', 'Endpoint', 'Zwei Achsen'):
        assert word not in visible
    dev = read('components/HealthDevelopment.tsx')
    assert '<InfoTip' in dev and '<p hidden' not in dev


def test_info_tip_works_on_touch_and_keyboard():
    tip = read('components/InfoTip.tsx')
    assert 'onClick={toggle}' in tip and 'onFocus={show}' in tip and 'openedAt' in tip
    assert '"Escape"' in tip and 'pointerdown' in tip and 'role="tooltip"' in tip


def test_coach_starts_a_fresh_chat_for_a_handed_over_question():
    coach = read('app/coach/page.tsx')
    assert 'const fresh=!!prompt&&!job' in coach and 'if(id&&!fresh)await openConversation(id)' in coach


def test_update_banner_is_dismissible_per_version():
    notice = read('components/UpdateNotice.tsx')
    shell = read('components/AppShell.tsx')
    assert 'export function UpdateBanner' in notice and '<UpdateBanner/>' in shell
    assert 'pengucoach_update_banner_dismissed' in notice and 'dismissed===version' in notice
    assert 'try{localStorage' in notice


def test_dark_themes_keep_values_readable():
    css = read('app/globals.css')
    theme = read('lib/theme.ts')
    assert 'document.documentElement.dataset.colorMode="dark"' in theme
    assert 'html[data-theme="dark"] button:not(.ghost)' not in css
    for selector in ('.coverage-pills span{', '.chart-chip.active{', '.chart-readout>div{'):
        rules = [m.group(1) for m in re.finditer(re.escape(selector) + r'([^}]*)\}', css)]
        assert rules and not any(re.search(r'background:\s*#fff\b', r) for r in rules), selector
    assert '"isNew"' not in read('app/settings/appearance/page.tsx')


def test_today_tiles_balance_their_row():
    assert '"--cols":tileColumns(prefs.pinned_metrics.length)' in read('app/today/page.tsx')
    assert 'repeat(var(--cols),minmax(0,1fr))' in read('app/globals.css')


def test_help_explains_new_health_features():
    help_text = read('lib/help.ts')
    for word in ('Anpassen', 'Rückblick', 'Coach', 'Update verfügbar'):
        assert word in help_text
