from types import SimpleNamespace

from apps.api.routers.settings import TodaySettingsIn
from pengucoach.coach.today import TODAY_METRICS, today_preferences


def test_all_available_readings_can_be_selected_and_survive_normalization():
    payload = TodaySettingsIn(pinned_metrics=list(reversed(TODAY_METRICS)))
    result = today_preferences(SimpleNamespace(dashboard_config={'today': payload.model_dump()}))
    assert result['pinned_metrics'] == list(reversed(TODAY_METRICS))
    assert len(result['pinned_metrics']) == len(TODAY_METRICS) == 12
    assert {'vo2max', 'body_fat', 'training_readiness', 'floors'} <= set(result['pinned_metrics'])


def test_existing_favorite_selection_and_hidden_cards_are_preserved():
    result = today_preferences(SimpleNamespace(dashboard_config={'today': {
        'pinned_metrics': ['hrv', 'weight'], 'hidden': ['weather', 'reflection'],
    }}))
    assert result['pinned_metrics'] == ['hrv', 'weight']
    assert result['hidden'] == ['weather', 'reflection']


def test_new_account_defaults_agree_with_settings_contract():
    assert today_preferences(None)['pinned_metrics'] == TodaySettingsIn().pinned_metrics
    assert len(today_preferences(None)['pinned_metrics']) == 6
