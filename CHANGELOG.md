# Changelog

## 0.1.0-alpha.4 - 2026-09-21

AI analysis and training-planning release:

- adds an **AI Analysis** action directly on every activity detail page
- shows the effective default model/provider and lets the user choose another eligible configured model per request
- adds 0/3/7-day lookback selection for activity analysis; the 7-day context also includes a deterministic 3-day summary
- ships a predefined deep-training-analysis prompt and keeps it editable per request
- adds centrally configurable task prompts for Coach Chat, Activity Analysis and Training Planning
- adds per-task **maximum response token** limits and a bounded input-context budget to control cloud cost
- maps token limits to OpenAI/OpenAI-compatible `max_tokens`, Anthropic `max_tokens` and Ollama `num_predict`
- reports provider token usage when the backend returns it
- introduces persisted `ai_runs` so activity analyses and generated training plans survive page reloads
- adds an AI training-plan builder for muscle gain, cardio/endurance, hybrid, cycling, 5K/10K, half marathon, marathon, strength, general fitness, mobility and custom goals
- training-plan generation accepts experience, weeks, days/week, typical session duration, equipment, constraints and a custom prompt
- training-plan context includes deterministic 7- and 28-day Garmin/FIT load summaries plus available recovery data
- activity AI context clearly separates official Garmin totals from PenguCoach-calculated FIT analytics
- activity detail now prefers Garmin summary values for ascent/descent, elevation range, HR, speed, power and cadence when Garmin provides them; local FIT calculations remain analytical fallbacks
- exposes Garmin elevation gain/loss and minimum HR in the curated activity-extra layer when available
- adds model/provider names to the AI admin model list and task-specific primary/fallback routing
- fixes helper bootstrap/update reliability by invoking the backup helper via absolute path
- installs `/usr/bin` helper symlinks so `pct exec <CTID> -- pengucoach-update|status|backup` works without depending on `/usr/local/bin` being in LXC attach PATH
- adds a repository `.gitignore` for Python/Next.js build artifacts

## 0.1.0-alpha.3 - 2026-09-21

Activity Detail v2 / analytics preparation release:

- adds an interactive multi-series FIT explorer with overlay and synchronized stacked modes
- heart rate, speed, elevation, power, cadence, grade and temperature can be toggled independently
- shared pointer/crosshair readout shows exact values at the selected point
- selectable analysis range for whole activity, first half, second half or custom range
- adds richer deterministic activity statistics: min/avg/max HR, avg/max speed, pace, power, normalized power, cadence, elevation gain/loss, min/max elevation and smoothed grade
- adds kilometre splits for running/cycling and 100 m splits for swimming
- split rows include time, pace, speed, HR, power, cadence, ascent/descent and grade when available
- captures FIT lap, strength-set and swim-length messages on re-analysis and renders sport-specific tables
- adds channel data-coverage indicators so missing sensors are visible instead of silently becoming zero
- exposes only a curated numeric subset of Garmin activity extras to the web UI instead of the full raw payload
- updater now synchronizes `PENGUCOACH_APP_VERSION` automatically from `pyproject.toml` and restores the previous version on rollback
- fresh installs derive the runtime version from `pyproject.toml` rather than a hard-coded installer value
- adds deterministic tests for activity detail statistics, splits and normalized series

## 0.1.0-alpha.2 - 2026-09-21

Hardening release based on the first real Proxmox/Garmin installation:

- fixed Python package discovery/build metadata for setuptools
- fixed Garmin ORIGINAL FIT download enum for `garminconnect==0.3.16`
- removed the conflicting `apps/web/lib/i18n.ts`; the React provider now resolves from `i18n.tsx`
- fixed the Admin Users page effect/refresh flow for the production Next.js build
- explicitly registers Garmin, FIT and scheduler Celery tasks
- uses SQLAlchemy `NullPool` to avoid asyncpg connections being reused across Celery `asyncio.run()` event loops
- creates Debian 13 LXC containers with `nesting=1`, fixing Redis/systemd user-namespace startup failures
- configures `en_US.UTF-8` before PostgreSQL installation and creates the PenguCoach database explicitly as UTF-8
- adds `pengucoach-db-utf8` to safely migrate early SQL_ASCII installations while retaining both a dump and the old database
- explicitly reloads Nginx after writing the site configuration before `/healthz` validation
- installs helper commands early during setup and refreshes them on updates
- `pengucoach-status` now reports the active database encoding

## 0.1.0-alpha.1 - 2026-09-21

Initial public architecture build:

- multi-user auth and mandatory login safety gate
- German/English UI
- Garmin MFA and encrypted token persistence
- strict read-only Garmin gateway
- scheduled Garmin health/activity synchronization
- original FIT archive, Parquet time series and first deterministic metrics
- Health, Activities, Garmin settings, Coach and Admin AI screens
- Ollama/OpenAI/Anthropic/OpenAI-compatible provider layer
- cloud AI health-data opt-in
- PostgreSQL/Redis/Celery/Alembic
- Proxmox LXC installer, updater, backup and status commands
