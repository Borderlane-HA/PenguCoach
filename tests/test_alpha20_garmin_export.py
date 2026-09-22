from pathlib import Path


def test_strength_export_resolves_localized_common_exercises():
    gateway = Path("pengucoach/garmin/gateway/workouts.py").read_text()
    for label in (
        '"kniebeugen": ("SQUAT", "SQUAT")',
        '"liegestutz": ("PUSH_UP", "PUSH_UP")',
        '"ausfallschritte": ("LUNGE", "LUNGE")',
        '"planke": ("PLANK", "PLANK")',
        '"side plank": ("PLANK", "SIDE_PLANK")',
        '"kreuzheben": ("DEADLIFT", "DEADLIFT")',
        '"rudern": ("ROW", "ROW")',
        '"beinpressen": ("SQUAT", "LEG_PRESS")',
        '"bankdrucken": ("BENCH_PRESS", "BENCH_PRESS")',
        '"wadenheben": ("CALF_RAISE", "CALF_RAISE")',
    ):
        assert label in gateway
    assert "def _exercise_candidates" in gateway
    assert "GARMIN_EXERCISE_NOT_FOUND" in gateway


def test_mobility_and_wellness_sports_use_generic_garmin_workout_endpoint():
    gateway = Path("pengucoach/garmin/gateway/workouts.py").read_text()
    assert '"mobility": (11, "mobility", BaseWorkout, "upload_workout")' in gateway
    assert '"yoga": (7, "yoga", BaseWorkout, "upload_workout")' in gateway
    assert '"pilates": (8, "pilates", BaseWorkout, "upload_workout")' in gateway
    assert '"hiit": (9, "hiit", BaseWorkout, "upload_workout")' in gateway
    assert '"cardio": (6, "cardio_training", BaseWorkout, "upload_workout")' in gateway
    assert '"stepTypeId": 8' in gateway
    assert 'return self.__client.upload_workout(workout.to_dict())' in gateway


def test_future_plan_prompt_asks_for_canonical_exercises_and_duration_consistency():
    structured = Path("pengucoach/training_plan/structured.py").read_text()
    assert "canonical plain English Garmin exercise names" in structured
    assert "duration_min * 60" in structured


def test_calendar_has_friendly_export_errors_and_new_sport_icons():
    ui = Path("apps/web/components/TrainingPlanCalendar.tsx").read_text()
    assert "garminErrorText" in ui
    assert 'mobility:"🧘"' in ui
    assert 'hiit:"⚡"' in ui
