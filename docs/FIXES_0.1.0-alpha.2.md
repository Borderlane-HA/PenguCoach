# 0.1.0-alpha.2 fix manifest

This archive consolidates the fixes discovered during the first real Debian 13 / Proxmox / Garmin run.

## Source/build fixes

- `pyproject.toml`: explicit setuptools build system and package discovery; SPDX-style MIT license field.
- `pengucoach/garmin/gateway/read_only.py`: Garmin ORIGINAL download enum is referenced through `Garmin.ActivityDownloadFormat.ORIGINAL`.
- `apps/web/lib/i18n.ts`: removed because it conflicted with the React-aware `i18n.tsx` module.
- `apps/web/app/admin/users/page.tsx`: async refresh is invoked safely from `useEffect`, and creation awaits refresh.

## Worker/database fixes

- `worker/celery_app.py`: explicit task imports for Garmin sync, FIT and scheduler tasks.
- `pengucoach/db/session.py`: SQLAlchemy async engine uses `NullPool`, preventing asyncpg connections from crossing Celery event loops.
- New `install/proxmox/pengucoach-db-utf8.sh`: safe SQL_ASCII -> UTF8 repair utility for early alpha databases.

## Proxmox installer fixes

- LXC creation enables `nesting=1` for Debian 13/systemd/Redis compatibility.
- Locale generation is performed before PostgreSQL installation.
- The application database is explicitly created with UTF-8 encoding.
- Database encoding is validated during installation.
- Nginx is explicitly reloaded after the PenguCoach site is written and before `/healthz` is checked.
- Helper commands are installed early and reinstalled at the end of setup.
- The updater refreshes helper commands on future updates.
- Status output includes the database encoding.

## Validation observed during the real install

After the UTF-8 database repair, a 365-day Garmin history import completed successfully and FIT files were downloaded and analyzed. This file records the fix set; it does not include private Garmin data, credentials, FIT files or database dumps.
