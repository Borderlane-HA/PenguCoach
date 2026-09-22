# PenguCoach 0.1.0-alpha.15

This maintenance release fixes the alpha.14 CI failures reported by GitHub Actions.

## Required files

The Garmin workout calendar feature introduced in alpha.14 requires:

- `db/migrations/versions/0004_garmin_workout_export.py`
- `pengucoach/garmin/gateway/workouts.py`
- `apps/api/routers/garmin_workouts.py`
- `worker/tasks/garmin_workouts.py`

The full alpha.15 archive contains all of them. If updating through the GitHub web UI, upload the complete repository tree (including `db/migrations/versions/0004_garmin_workout_export.py`) before creating the release tag.

## CI fixes

- Frontend: `TrainingPlanCalendar` now accepts the shared `Lang` type used by `bi()`.
- Backend: the alpha.14 Garmin migration is included and remains covered by the regression test.
- Dashboard: the running backend version is shown below the logout action.
