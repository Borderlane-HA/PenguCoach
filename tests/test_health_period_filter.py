from pathlib import Path


def test_health_vo2_history_accepts_same_period_filter_as_health_range():
    router = Path("apps/api/routers/health.py").read_text()
    assert '@router.get("/vo2-history")' in router
    assert 'all_data: bool = Query(default=False, alias="all")' in router
    assert 'start = None if all_data else date.today() - timedelta(days=days - 1)' in router
    assert 'Activity.started_at >= start_dt' in router


def test_health_page_applies_selected_period_to_every_chart_family():
    page = Path("apps/web/app/health/page.tsx").read_text()
    assert 'api<any>(`/health/range${suffix}`)' in page
    assert 'api<Vo2Data>(`/health/vo2-history${suffix}`)' in page
    assert 'Laufen & Radfahren","Running & cycling")} · {periodLabel}' in page
    assert 'gesamter Verlauf' not in page


def test_cloud_provider_setup_explains_privacy_before_health_data_is_sent():
    page = Path("apps/web/app/admin/ai/page.tsx").read_text()
    assert 'externalProviderSelected' in page
    assert 'Externer KI-Provider' in page
    assert 'Cloud-KI aktivieren' in page
    assert 'Gesundheits- und Trainingsdaten bleiben gesperrt' in page
