from pathlib import Path
import json
import re
import tomllib


def test_alpha451_version_is_pep440_and_displays_as_maintenance_release():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    package = json.loads(Path("apps/web/package.json").read_text())
    assert project["project"]["version"] == "0.1.0-alpha.46"
    assert package["version"] == "0.1.0-alpha.46"
    config = Path("pengucoach/common/config.py").read_text()
    assert 'app_version: str = "0.1.0-alpha.46"' in config
    assert 'return f"{match.group(1)}-alpha.{match.group(2)}.{match.group(3)}"' in config


def test_activity_page_decouples_first_page_from_summary_stats_and_has_loading_feedback():
    api = Path("apps/api/routers/activities.py").read_text()
    ui = Path("apps/web/app/activities/page.tsx").read_text()
    css = Path("apps/web/app/globals.css").read_text()
    assert '@router.get("/stats")' in api
    assert 'include_stats: bool = Query(default=True)' in api
    assert 'include_stats:"false"' in ui
    assert 'api<Stats>("/activities/stats")' in ui
    assert 'Aktivitäten werden geladen…' in ui
    assert 'Aktivitäten werden aktualisiert…' in ui
    assert 'ActivityListSkeleton' in ui
    assert 'import {bi,useI18n,type Lang} from "../../lib/i18n";' in ui
    assert 'function ActivityListSkeleton({lang}:{lang:Lang})' in ui
    assert 'function ActivityListSkeleton({lang}:{lang:string})' not in ui
    assert 'controller.abort()' in ui
    assert '.activity-skeleton-row' in css
    assert '@media(max-width:480px)' in css


def test_activity_stats_are_one_aggregate_query_without_full_json_text_casts():
    api = Path("apps/api/routers/activities.py").read_text()
    block = api[api.index("async def _activity_stats"):api.index("def _activity_sources")]
    assert 'func.count(Activity.id).filter' in block
    assert 'Activity.raw.has_key("sparkyfitness")' in api
    assert 'Activity.raw["source"].astext == "manual_upload"' in api
    assert '_STATS_TTL_SECONDS = 30.0' in api
    assert 'cast(Activity.raw' not in api


def test_activity_performance_indexes_exist_in_models_and_migration():
    models = Path("pengucoach/db/models.py").read_text()
    migration = Path("db/migrations/versions/0013_activity_performance.py").read_text()
    for name in (
        "ix_activities_user_started_at",
        "ix_activities_user_fit_status",
        "ix_activities_user_manual_source",
        "ix_activities_user_sparky_source",
    ):
        assert name in models
        assert name in migration
    assert 'down_revision = "0012_training_intelligence"' in migration
    assert "raw ? 'sparkyfitness'" in migration
    assert "raw ->> 'source'" in migration


def test_activity_search_no_longer_scans_entire_raw_json_payload():
    api = Path("apps/api/routers/activities.py").read_text()
    search_block = api[api.index("term = (q or \"\").strip()"):api.index("paginated = page is not None")]
    assert 'Activity.name.ilike(pattern)' in search_block
    assert 'Activity.sport_type.ilike(pattern)' in search_block
    assert 'Activity.subsport_type.ilike(pattern)' in search_block
    assert 'Activity.raw["filename"].astext.ilike(pattern)' in search_block
    assert 'cast(' not in search_block
