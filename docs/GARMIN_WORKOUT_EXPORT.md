# Garmin workout calendar export

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

PenguCoach exports typed Garmin workouts for running, cycling, swimming, walking, hiking and strength. Mobility, yoga, Pilates, HIIT and generic cardio use Garmin's generic workout endpoint with a timed main step when the plan does not provide finer structured steps. Unsupported custom/other sports remain visible in PenguCoach and are marked **Plan only**.

Endurance steps support time or distance, nested repeat blocks and optional heart-rate/power-zone targets. Strength workouts use Garmin's bundled exercise catalogue; PenguCoach resolves common localized/German labels to safe canonical catalogue entries before upload. If an exercise still cannot be resolved, only that session fails and the rest of the export continues.

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

## Edit before export

The calendar is an export staging area. Open a session and choose **Edit before Garmin** to adjust the copy that will be sent to Garmin Connect without rewriting the stored AI plan. PenguCoach supports changing the workout name, total duration, notes, timed/distance steps, zone targets, repeat counts and strength exercise parameters; individual steps or exercises can also be removed. Draft edits are kept in the browser per plan until the user restores the original or clears browser storage. Session identity, sport, week and weekday remain fixed so an edit cannot silently move an already planned workout.
