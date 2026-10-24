"""alpha.82: Today v2 (cards on/off and ordered), status menu, help page, sidebar update check, About in System."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.routers import settings
from pengucoach.coach.today import NEW_TODAY_CARDS, PREVIOUS_TODAY_CARDS, TODAY_CARDS, today_preferences

ROOT = Path(__file__).resolve().parents[1]


def prefs(raw):
    return today_preferences(SimpleNamespace(dashboard_config={'today': raw}))


def test_new_cards_are_visible_by_default_and_density_defaults():
    value = today_preferences(None)
    assert value['order'] == TODAY_CARDS and value['hidden'] == [] and value['density'] == 'comfortable'
    for key in NEW_TODAY_CARDS:
        assert key in value['order']


def test_old_layouts_keep_their_order_and_get_new_cards_in_place():
    custom = ['activities', 'metrics', 'trend', 'load', 'progress', 'preparation', 'weather', 'reflection']
    value = prefs({'order': custom, 'hidden': ['weather']})
    known = [k for k in value['order'] if k in custom]
    assert known == custom, "existing order must survive"
    assert value['order'][0] == 'readiness' and value['order'][1] == 'checkin'
    assert value['order'].index('dayphases') == value['order'].index('metrics') + 1
    assert value['hidden'] == ['weather'] and len(value['order']) == len(TODAY_CARDS)
    assert prefs({'order': PREVIOUS_TODAY_CARDS})['order'] == TODAY_CARDS


def test_settings_validation_accepts_new_cards_and_density():
    body = settings.TodaySettingsIn(order=['week', 'readiness'], hidden=['dayphases', 'checkin'], density='compact')
    assert body.order[:2] == ['week', 'readiness'] and set(body.order) == set(TODAY_CARDS)
    assert prefs(body.model_dump())['density'] == 'compact'
    with pytest.raises(ValidationError):
        settings.TodaySettingsIn(density='tiny')
    assert prefs({'density': 'tiny'})['density'] == 'comfortable'


def test_today_page_has_no_clutter_and_one_settings_entry():
    page = (ROOT / 'apps/web/app/today/page.tsx').read_text()
    assert '<TodayReadiness' in page and '<TodaySettings' in page and 'visibleCards(prefs)' in page
    for gone in ('SourceOverview', 'Coach frei öffnen', 'Messwerte auswählen', 'Ansicht aktualisiert', 'Aktivitäten öffnen'):
        assert gone not in page
    readiness = (ROOT / 'apps/web/components/TodayReadiness.tsx').read_text()
    assert 'ready-gauge' in readiness and 'Warum?' in readiness and 'today-checkin-trigger' in readiness


def test_status_menu_replaces_system_badge():
    shell = (ROOT / 'apps/web/components/AppShell.tsx').read_text()
    assert '<StatusMenu/>' in shell and 'health-live' not in shell
    assert 'href:"/settings/about"' not in shell and 'href:"/help"' in shell
    api = (ROOT / 'apps/api/routers/health.py').read_text()
    assert '"status": conn.status if conn else "disconnected"' in api


def test_update_check_stays_in_sidebar_until_result_is_clicked():
    notice = (ROOT / 'apps/web/components/UpdateNotice.tsx').read_text()
    body = notice.split('export default function UpdateNotice')[1]
    assert '<button type="button" className={`version-check' in body and 'onClick={()=>{setAsked(true);void check()}}' in body
    assert 'className={`update-result' in body


def test_about_lives_in_system_and_updates():
    system = (ROOT / 'apps/web/components/SystemMaintenance.tsx').read_text()
    assert '"about"' in system and '<AboutPenguCoach' in system
    updates = (ROOT / 'apps/web/app/settings/updates/page.tsx').read_text()
    assert '<AboutPenguCoach' in updates
    old = (ROOT / 'apps/web/app/settings/about/page.tsx').read_text()
    assert '/admin/system#about' in old and '/settings/updates#about' in old


def test_help_page_links_to_every_settings_page():
    help_data = (ROOT / 'apps/web/lib/help.ts').read_text()
    for href in ('/settings/garmin', '/settings/sparkyfitness', '/settings/appearance', '/settings/weather',
                 '/settings/maps', '/settings/privacy', '/settings/updates', '/admin/system'):
        assert f'href:"{href}' in help_data, href
    assert (ROOT / 'apps/web/app/help/page.tsx').exists()
