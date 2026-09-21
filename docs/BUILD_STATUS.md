# Build status — 0.1.0-alpha.1

PenguCoach is an alpha development project. This repository contains the first installable foundation for real Proxmox/Garmin testing; it is not yet the finished product described in the long-term roadmap.

## Implemented

- Multi-user local authentication with Argon2id password hashing
- Mandatory Development & Health Notice after every new login
- German and English UI foundation
- PostgreSQL + Alembic migrations
- Redis + Celery worker/scheduler
- Garmin login and MFA flow with encrypted persisted session tokens
- Explicit allowlist-based Garmin read-only gateway
- Per-user automatic Garmin sync settings
- Incremental sync, history import, sync history, jitter/locking and rate-limit cooldown handling
- Broad Garmin health ingestion (best-effort by account/device availability)
- Activities list/detail foundation
- Original FIT download and immutable archive
- FIT parsing, Parquet time-series storage and first deterministic metrics
- Personal Today/Health views foundation
- Ollama, OpenAI, Anthropic and OpenAI-compatible provider administration foundation
- Cloud-health-AI opt-in; local-only mode
- Native Proxmox LXC installer
- `pengucoach-update`, `pengucoach-backup`, `pengucoach-status`
- Docker Compose development/alternative deployment

## Intentionally still alpha / next iterations

- Full Garmin field-by-field normalization for every model/account combination
- Rich charting, map and FIT comparison UI
- Full personal baseline/recovery analytics suite
- Deep LangGraph multi-agent workflow
- Complete training-plan engine and plan adaptation workflow
- OIDC/passkeys/coach sharing
- End-to-end live Garmin regression tests (require a real account and must never run in public CI)

## Validation performed for this source package

- Python bytecode compilation (`compileall`)
- Shell syntax validation (`bash -n`)
- JSON and TOML parsing
- TypeScript/TSX transpilation syntax checks
- SQLAlchemy metadata import/table registration
- secret/temporary-file cleanup checks

A full dependency installation and production Next.js build require network package access and are intentionally exercised by GitHub Actions and the first real Proxmox installation after the repository is pushed.

## Safety

PenguCoach is for development, fitness, training and wellness analysis. It is not a medical device and does not provide medical diagnosis or treatment. Users must consult appropriately qualified medical, sports, nutrition or other professionals where relevant.
