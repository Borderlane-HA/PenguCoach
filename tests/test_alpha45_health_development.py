from datetime import datetime, timedelta, timezone
from pathlib import Path
import tomllib

import pytest

from pengucoach.db.models import Activity, BodyMeasurement, DailyHealth, User
from pengucoach.health.development import _vo2_from_hrr, estimate_summary, estimate_vo2_history, vo2_display_payload



def test_alpha45_release_version():
    project=tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["version"] == "0.1.0-alpha.45.post1"
    assert project["license"] == "LicenseRef-PolyForm-Noncommercial-1.0.0"

def _user():
    return User(username="alpha45", email="alpha45@example.invalid", password_hash="x", timezone="Europe/Berlin")


def _health(days=14, resting=55):
    today = datetime.now(timezone.utc).date()
    return [DailyHealth(user_id=None, date=today - timedelta(days=i), resting_hr=resting, raw={}) for i in range(days)]


def test_hrr_extrapolation_uses_vo2_reserve_not_raw_vo2max_scaling():
    # 60% HR reserve corresponds to ~60% VO2 reserve, not 60% raw VO2max.
    estimate, fraction = _vo2_from_hrr(27.5, avg_hr=133, max_hr=185, resting_hr=55)
    assert fraction == pytest.approx(0.6)
    assert estimate == pytest.approx(43.5)
    assert estimate != pytest.approx(27.5 / 0.6)


def test_running_vo2_fallback_is_labelled_estimate_and_rejects_hilly_summary():
    user = _user()
    started = datetime.now(timezone.utc) - timedelta(days=1)
    flat = Activity(
        id=None, user_id=None, garmin_activity_id=1, sport_type="running", started_at=started,
        duration_seconds=3600, distance_m=10800, avg_hr=155, max_hr=178, avg_speed=3.0,
        elevation_gain=50, raw={},
    )
    hilly = Activity(
        id=None, user_id=None, garmin_activity_id=2, sport_type="running", started_at=started,
        duration_seconds=3600, distance_m=10000, avg_hr=155, max_hr=178, avg_speed=3.0,
        elevation_gain=450, raw={},
    )
    zones={"heart_rate":{"profiles":[{"sport":"RUNNING","max_hr_bpm":185,"resting_hr_bpm":55}]}}
    rows=estimate_vo2_history([flat,hilly],_health(),[],{},zones,user)["running"]
    assert len(rows) == 1
    assert rows[0]["measurement_kind"] == "estimated"
    assert rows[0]["source"] == "pengucoach_estimate"
    assert rows[0]["method"] == "acsm_running_hrr"
    assert rows[0]["confidence"] in {"low","medium","high"}


def test_cycling_vo2_requires_power_and_body_mass_not_speed_alone():
    user=_user(); started=datetime.now(timezone.utc)-timedelta(days=1)
    speed_only=Activity(id=None,user_id=None,garmin_activity_id=3,sport_type="cycling",started_at=started,duration_seconds=3600,distance_m=30000,avg_hr=150,max_hr=178,avg_speed=8.33,raw={})
    powered=Activity(id=None,user_id=None,garmin_activity_id=4,sport_type="indoor_cycling",started_at=started,duration_seconds=3600,distance_m=30000,avg_hr=150,max_hr=178,avg_speed=8.33,avg_power=220,raw={})
    weight=BodyMeasurement(user_id=None,measured_at=started-timedelta(days=2),weight_kg=75,raw={})
    zones={"heart_rate":{"profiles":[{"sport":"CYCLING","max_hr_bpm":185,"resting_hr_bpm":55},{"sport":"DEFAULT","max_hr_bpm":185,"resting_hr_bpm":55}]}}
    rows=estimate_vo2_history([speed_only,powered],_health(),[weight],{},zones,user)["cycling"]
    assert len(rows)==1
    assert rows[0]["method"]=="acsm_cycle_power_hrr"
    assert rows[0]["inputs"]["avg_power_w"]==220


def test_provider_vo2_always_wins_over_fallback_for_same_sport():
    imported={"running":[{"date":"2026-09-01","value":51.2,"measurement_kind":"imported","source":"sparkyfitness"}],"cycling":[]}
    estimated={"running":[{"date":"2026-09-02","value":53.0,"measurement_kind":"estimated","confidence_score":.8}],"cycling":[]}
    display=vo2_display_payload(imported,estimated)
    assert display["running"] == imported["running"]
    assert display["latest"]["running"] == 51.2
    assert display["latest_meta"]["running"]["measurement_kind"] == "imported"


def test_estimate_summary_uses_recent_median_not_single_outlier():
    points=[
        {"date":"2026-09-01","value":50,"confidence_score":.8},
        {"date":"2026-09-08","value":51,"confidence_score":.8},
        {"date":"2026-09-15","value":70,"confidence_score":.8},
        {"date":"2026-09-20","value":50.5,"confidence_score":.8},
        {"date":"2026-09-25","value":51.5,"confidence_score":.8},
    ]
    summary=estimate_summary(points)
    assert summary and summary["value"] == 51.0
    assert summary["sample_count"] == 5


def test_health_development_ui_is_professional_progressive_and_mobile_aware():
    page=Path("apps/web/app/health/page.tsx").read_text()
    component=Path("apps/web/components/HealthDevelopment.tsx").read_text()
    chart=Path("apps/web/components/ProfessionalLineChart.tsx").read_text()
    css=Path("apps/web/app/globals.css").read_text()
    assert 'value="3m"' in page and 'value="6m"' in page
    assert '<HealthDevelopment' in page
    assert '<details className="card health-secondary-details">' in page
    assert 'TrainingVolumeChart' in component and 'Belastung & Erholung' in component
    assert 'geschätzt' in component and 'keine Spiroergometrie' in component
    assert 'pro-tooltip' in chart and 'onTouchStart' in chart
    assert '@media(max-width:620px)' in css and '.health-development-card' in css


def test_sparky_sync_accepts_future_cardio_fitness_custom_metric_without_overwriting_source_semantics():
    sync=Path("pengucoach/sparkyfitness/sync.py").read_text()
    assert '"cardio fitness"' in sync
    assert '"aerobic capacity"' in sync
    assert 'merge_metric(row, "vo2max_running", value, "sparkyfitness"' in sync


def test_ai_coach_receives_training_development_and_discloses_it():
    service=Path("pengucoach/llm/service.py").read_text()
    companion=Path("pengucoach/coach/companion.py").read_text()
    ui=Path("apps/web/app/coach/page.tsx").read_text()
    assert 'training_development' in service
    assert 'development_summary_for_coach' in companion
    assert 'trainingDevelopment' in ui
    assert 'Entwicklung' in ui
