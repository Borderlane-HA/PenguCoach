from types import SimpleNamespace

from apps.api.routers.settings import TodaySettingsIn
from pengucoach.coach.today import LEGACY_TODAY_ORDER, TODAY_CARDS, today_preferences


def test_previous_default_promotes_progress_without_changing_visibility_or_metrics():
    preference = SimpleNamespace(dashboard_config={'today': {
        'order': LEGACY_TODAY_ORDER,
        'hidden': ['weather'],
        'pinned_metrics': ['hrv'],
        'preferred_start_hour': 16,
        'preferred_end_hour': 22,
    }})
    value = today_preferences(preference)
    assert value['order'] == TODAY_CARDS
    assert value['hidden'] == ['weather']
    assert value['pinned_metrics'] == ['hrv']
    assert (value['preferred_start_hour'], value['preferred_end_hour']) == (16, 22)
    assert TodaySettingsIn().order == TODAY_CARDS


def test_user_reordered_cards_are_preserved():
    custom_order = ['reflection', *[key for key in TODAY_CARDS if key != 'reflection']]
    preference = SimpleNamespace(dashboard_config={'today': {'order': custom_order}})
    assert today_preferences(preference)['order'] == custom_order
