# PenguCoach 0.1.0-alpha.16

Alpha.16 is an in-place upgrade from alpha.15. It requires **no new Alembic migration**.

## Highlights

- Manage and delete stored training plans, including plans from older versions.
- Delete stored per-activity AI analyses.
- When a plan has PenguCoach-managed Garmin exports, choose whether deletion should also unschedule/delete those Garmin entries. Remote cleanup is a background job and keeps the local plan if any Garmin removal fails, so cleanup can be retried.
- Historical Garmin import now defaults to **Optimized** mode. Activity catalogue import is unchanged; days older than 90 days use core daily/sleep/HRV/stress/Body Battery/max-metrics/body calls while the newest 90 days use full detail. Existing alpha.15 full-day completion markers are reused.
- Long history imports can be paused or cancelled. Already committed days stay in the database and are skipped on the next compatible run.
- Training-plan generation is explicitly told the effective output-token limit and expected session count, and is instructed to complete compact structured JSON inside that limit. Transient HTTP model failures are retried once.
- Sidebar version text is aligned with the other account controls.

## First history import after upgrading

If an alpha.15 import had already completed days, do not delete those records. Start alpha.16 in **Optimized** mode with the desired time window. Full alpha.15 completion markers are recognized and skipped automatically.

If the old worker was stopped while an import was active, let the deployment restart finish before starting the new import. The new UI then provides Pause and Cancel for subsequent jobs.

## Garmin deletion semantics

- **Also delete from Garmin:** unschedule calendar entry first, then delete the PenguCoach-created workout template, then delete the local plan.
- **Delete only in PenguCoach:** local plan/export ledger is deleted and Garmin is intentionally left untouched.
- A failed remote deletion keeps the local plan/export ledger so the cleanup can be retried.
