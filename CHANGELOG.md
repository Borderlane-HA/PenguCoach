# Changelog

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
