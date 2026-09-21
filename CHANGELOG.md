# Changelog

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
