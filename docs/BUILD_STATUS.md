# Build status — 0.1.0-alpha.5

PenguCoach is an alpha development project. This repository contains an installable Proxmox/Garmin training-analysis foundation and now includes a modernized AI Studio and reload-safe background AI generation.

## Implemented

- Multi-user local authentication with Argon2id password hashing
- Mandatory Development & Health Notice after every new login
- German and English UI foundation
- PostgreSQL + Alembic migrations
- Redis + Celery worker/scheduler
- Garmin login and MFA flow with encrypted persisted session tokens
- Explicit allowlist-based Garmin read-only gateway
- Per-user automatic Garmin sync settings
- Incremental sync, history import, sync history and rate-limit handling
- Broad Garmin health ingestion (best-effort by account/device availability)
- Original FIT download, immutable archive, Parquet time series and deterministic activity metrics
- Rich Activity Detail v2 with overlay/stacked charts, splits, laps, elevation, power, cadence and sensor coverage
- Ollama, OpenAI, Anthropic and OpenAI-compatible provider administration
- Modern AI Studio with task-specific routing, DE/EN prompts, context windows and response-token budgets
- Ollama `num_ctx` and `num_predict` mapping
- Background Coach Chat, Activity Analysis and Training Plan jobs with reload-safe polling
- Persisted activity analyses and training plans with token/stop metadata and truncation detection
- AI-assisted training-plan builder with 7/28-day Garmin/FIT context
- Cloud-health-AI opt-in; local-only mode
- Native Proxmox LXC installer with Debian 13 nesting and UTF-8 database initialization
- `pengucoach-update`, `pengucoach-backup`, `pengucoach-status`, `pengucoach-db-utf8`
- Docker Compose development/alternative deployment

## Intentionally still alpha / next iterations

- Full Garmin field-by-field normalization for every model/account combination
- Map/route visualization and richer sport-specific comparisons
- Long-term personal baseline/recovery analytics suite
- Full adaptive training-plan lifecycle and plan-vs-actual tracking
- More sophisticated context retrieval/ranking before very large AI prompts
- OIDC/passkeys/coach sharing
- End-to-end live Garmin regression tests (require a real account and must never run in public CI)

## Validation performed for this source package

- Python bytecode compilation (`compileall` / `py_compile`)
- Shell syntax validation (`bash -n`)
- JSON and TOML parsing
- TypeScript/TSX parser validation with TypeScript 5.8
- targeted Python tests: 9 passed
- package wheel build with local build dependencies (`pip wheel --no-build-isolation`)

A full dependency installation and production Next.js build could not be completed in the artifact environment because npm package download timed out. The production updater performs `npm install` and `npm run build` on the PenguCoach LXC.

## Safety

PenguCoach is for development, fitness, training and wellness analysis. It is not a medical device and does not provide medical diagnosis or treatment. Users must consult appropriately qualified medical, sports, nutrition or other professionals where relevant.
