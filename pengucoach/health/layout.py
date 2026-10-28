"""Personal layout of the Health page (alpha.83): sections, readings and default period."""

HEALTH_SECTIONS = ['overview', 'trends', 'development', 'body', 'coverage']
HEALTH_METRICS = ['hrv', 'sleep', 'resting_hr', 'steps', 'floors', 'body_battery_high', 'stress', 'hydration']
HEALTH_PERIODS = ['7', '30', '90', '180', '365', 'all']
DEFAULT_HEALTH = {
    'order': list(HEALTH_SECTIONS),
    # Coverage is about the data, not about health: off unless someone wants it.
    'hidden': ['coverage'],
    'metrics': ['hrv', 'sleep', 'resting_hr', 'steps', 'body_battery_high', 'stress'],
    'period': '30',
}


def health_preferences(pref):
    config = pref.dashboard_config if pref and isinstance(pref.dashboard_config, dict) else {}
    raw = config.get('health')
    if not isinstance(raw, dict):
        return {k: list(v) if isinstance(v, list) else v for k, v in DEFAULT_HEALTH.items()}

    def keys(name, allowed):
        values = raw.get(name)
        values = values if isinstance(values, list) else []
        return list(dict.fromkeys(k for k in values if isinstance(k, str) and k in allowed))

    order = keys('order', HEALTH_SECTIONS)
    order += [k for k in HEALTH_SECTIONS if k not in order]
    metrics = keys('metrics', HEALTH_METRICS) or list(DEFAULT_HEALTH['metrics'])
    hidden = keys('hidden', HEALTH_SECTIONS) if isinstance(raw.get('hidden'), list) else list(DEFAULT_HEALTH['hidden'])
    period = raw.get('period') if raw.get('period') in HEALTH_PERIODS else DEFAULT_HEALTH['period']
    return {'order': order, 'hidden': hidden, 'metrics': metrics, 'period': period}
