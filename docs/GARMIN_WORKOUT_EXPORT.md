# Garmin workout calendar export · alpha.14

PenguCoach `0.1.0-alpha.14` can turn a newly generated AI training plan into a reviewable weekly calendar and explicitly export selected supported sessions to Garmin Connect.

## Flow

1. Generate a new plan on **Training**.
2. Open **Kalender & Garmin / Calendar & Garmin** below the readable plan.
3. Choose the Monday that represents week 1. PenguCoach maps every plan week/day to a concrete date.
4. Review each session and expand its structured steps.
5. Select required sessions, all exportable sessions, or an individual subset.
6. In **Garmin settings → Training & Calendar**, enable **Export training plan to Garmin**. This opt-in is off by default.
7. Click **Export to Garmin** and confirm the selected count.
8. The Garmin worker uploads each selected structured workout and schedules it for the mapped date.

Successful session/date combinations are written to `garmin_workout_exports`; a repeated export skips those combinations instead of creating duplicates.

## Supported export types

The initial exporter supports typed Garmin workouts for:

- running
- cycling
- swimming
- walking
- hiking
- strength

Other PenguCoach plan sports such as mobility, yoga, Pilates, HIIT, generic cardio and custom/other remain visible in the plan but are marked **Plan only** until a reliable Garmin workout representation is added.

Endurance steps support time or distance, nested repeat blocks and optional heart-rate/power-zone targets. Strength workouts use Garmin's bundled exercise catalogue. If an AI-generated exercise name cannot be resolved to that catalogue, only that session fails and the rest of the export continues.

## Safety boundary

The existing `GarminReadOnlyGateway` is unchanged for synchronization. Health, sleep, HRV, activities, FIT downloads, body data, zones and training-status ingestion continue through the read-only allow-list.

The new `GarminWorkoutGateway` is a separate façade and deliberately exposes only:

- upload one structured plan session
- schedule an uploaded workout on a date
- delete an uploaded template when scheduling that template failed

It has no generic attribute passthrough and is created only inside the explicit export worker after the per-user `workout_export_enabled` flag is checked. The AI model never receives the Garmin client, token or write gateway.

## Structured plan format

Training-plan generation now asks the selected LLM for a compact JSON plan enclosed in PenguCoach markers. PenguCoach validates that JSON with Pydantic and then renders the readable Markdown itself. The validated structure is stored in `ai_runs.metadata_json.structured_plan` and is the source for calendar/export operations.

If a local model ignores the structured-output contract, PenguCoach keeps its original prose instead of failing the whole job. Such a plan is readable but cannot be exported; generating a new plan with a model that follows the contract enables the calendar.

## Database migration

Alembic revision `0004_garmin_workout_export`:

- adds `garmin_sync_settings.workout_export_enabled` with server default `false`
- creates `garmin_workout_exports`
- adds a uniqueness constraint across user, plan run, session id and scheduled date

No Garmin write operation is enabled by the migration itself.

## Compatibility note

The project remains pinned to `garminconnect==0.3.16`. The exporter is built against that release's typed workout upload and workout scheduling API. `python-garminconnect` uses unofficial Garmin web services, so a future Garmin service change can still require an exporter update.
