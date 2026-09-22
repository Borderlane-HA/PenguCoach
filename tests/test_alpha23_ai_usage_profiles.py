from pathlib import Path

from pengucoach.llm.usage import calculate_cost_eur, quality_budget, quality_instruction


def test_token_cost_formula_and_unpriced_models():
    usage = {"input_tokens": 1_000_000, "output_tokens": 2_000_000}
    pricing = {"input_eur_per_million": 0.10, "output_eur_per_million": 0.15}
    assert calculate_cost_eur(usage, pricing) == 0.40
    assert calculate_cost_eur(usage, {"input_eur_per_million": None, "output_eur_per_million": None}) is None


def test_quality_profiles_keep_standard_and_scale_other_profiles():
    standard = 8_000
    assert quality_budget("training_plan", standard, "standard") == standard
    assert quality_budget("training_plan", standard, "very_low") < standard
    assert quality_budget("training_plan", standard, "low") < standard
    assert quality_budget("training_plan", standard, "high") > standard
    instruction = quality_instruction("very_low", "de", "training_plan")
    assert "vollständigen strukturierten Plan" in instruction
    assert "alle" in instruction.lower()


def test_ai_studio_exposes_pricing_usage_budget_and_default_quality_profiles():
    backend = Path("apps/api/routers/admin_ai.py").read_text()
    web = Path("apps/web/app/admin/ai/page.tsx").read_text()
    settings = Path("apps/api/routers/settings.py").read_text()
    assert "input_cost_per_million_eur" in backend
    assert 'router.get("/usage")' in backend
    assert "avg_tokens_per_request" in backend
    assert "monthly_budget_eur" in settings
    assert "Standard-Antwortprofil" in web
    assert "AI USAGE & COST" in web


def test_cost_and_quality_are_snapshotted_on_ai_runs_and_coach_is_counted():
    service = Path("pengucoach/llm/service.py").read_text()
    worker = Path("worker/tasks/ai.py").read_text()
    coach = Path("apps/api/routers/coach.py").read_text()
    assert '"pricing": pricing' in service
    assert '"cost_eur": cost_eur' in service
    assert '"elapsed_seconds": elapsed_seconds' in service
    assert '"generation_calls": generation_calls' in worker
    assert "db.add(AiRun(" in worker
    assert "db.add(AiRun(" in coach


def test_all_three_ai_surfaces_offer_quality_profile_and_cost_feedback():
    coach = Path("apps/web/app/coach/page.tsx").read_text()
    training = Path("apps/web/app/training/page.tsx").read_text()
    activity = Path("apps/web/app/activities/[id]/page.tsx").read_text()
    for source in (coach, training, activity):
        assert "AiQualityControl" in source
        assert "quality_profile" in source
    assert "cost_eur" in coach
    assert "cost_eur" in training
    assert "cost_eur" in activity


def test_activity_catalogue_repair_is_separate_from_wellness_backfill():
    api = Path("apps/api/routers/garmin.py").read_text()
    worker = Path("worker/tasks/garmin_sync.py").read_text()
    web = Path("apps/web/app/settings/garmin/page.tsx").read_text()
    assert '@router.post("/import/activities")' in api
    assert "activity_catalog_import" in worker
    assert 'sync_type="activity_catalog"' in worker
    assert "_activity_catalog_only" in worker
    assert "Nur Aktivitäten vollständig abgleichen" in web
    assert "activity_count" in web


def test_release_docs_stay_in_root_changelog_only():
    docs = Path("docs")
    names = {p.name for p in docs.iterdir() if p.is_file()}
    assert not any(name.startswith("CHANGED_FILES_") for name in names)
    assert not any(name.startswith("RELEASE_ALPHA") for name in names)
