# Build status — 0.1.0-alpha.16

PenguCoach is an alpha development project. Alpha.16 adds stored-plan/AI-analysis deletion, optional cleanup of PenguCoach-created Garmin calendar workouts, a token-budget-aware structured plan generator, and an optimized/resumable historical Garmin importer with pause/cancel controls. No database migration is required from alpha.15.

## Implemented baseline

- Multi-user local authentication and mandatory Development & Health Notice
- German and English UI foundation
- PostgreSQL + Alembic, Redis + Celery worker/scheduler
- Garmin login/MFA, encrypted persisted session tokens, read-only sync gateway and explicit opt-in workout/calendar export gateway
- Historical/incremental Garmin health and activity synchronization
- Original FIT archive, Parquet time series and deterministic activity analytics
- Activity Detail v2 with overlay/stacked charts, splits, laps, elevation, power, cadence and sensor coverage
- Ollama, OpenAI, Anthropic and OpenAI-compatible provider administration
- AI Studio with per-task routing, DE/EN prompts, context windows and response-token budgets
- Background Coach Chat, Activity Analysis and Training Plan jobs with reload-safe polling
- Persisted AI runs with token/stop metadata and truncation detection
- Native Proxmox LXC installer/updater/backup/status/database repair helpers

## Alpha.8 visual & operations layer

- bright health-first design system with five per-user themes and high-contrast typography
- persistent grouped desktop navigation sidebar
- compact sticky context header
- responsive mobile bottom navigation dock
- redesigned login, Today, Health and Activities experiences plus a local dashboard wellness illustration
- modernized forms, tables, cards, status chips, Activity Detail v2, Coach and AI Studio surfaces
- profile-picture and custom app-icon uploads stored under the persistent data directory
- simplified Garmin sync/backfill separation plus live Celery-job status, reload-safe polling and automatic timestamp refresh
- model edit/delete and saved-provider discovery, including current Anthropic model discovery, clearer fixed-model wording and compact destructive actions
- updater replaces local deployment-source changes after backup without an overwrite confirmation or local-source-change abort
- built-in default app icon + favicon and improved responsive behavior without removing analytical table detail

## Intentionally still alpha / next iterations

- Full Garmin field-by-field normalization for every device/account combination and more range/batch endpoints for very old history
- Long-term 7/28/90/365-day training-load and recovery insight layer
- Route/map visualization and richer sport-specific comparisons
- Adaptive training-plan lifecycle and plan-vs-actual tracking
- More sophisticated context retrieval/ranking for very large AI prompts
- OIDC/passkeys/coach sharing
- End-to-end live Garmin regression tests (require a real account and must never run in public CI)

## Validation performed for this source package

- Python bytecode compilation: passed
- Python regression suite with local import-only service stubs: **38 passed**
- Changed frontend sources type-checked with local TypeScript declarations: passed
- All 25 TypeScript/TSX sources transpiled without syntax errors
- Full `next build` cannot be reproduced in the artifact environment because npm dependency installation is unavailable; GitHub Actions remains the authoritative production-build check

## Safety

PenguCoach is for development, fitness, training and wellness analysis. It is not a medical device and does not provide medical diagnosis or treatment. Users should involve appropriately qualified medical, sports, nutrition or other professionals where relevant.
