# PenguCoach

**Self-hosted AI Training & Health Coach** · **Selbst gehosteter KI-Trainings- und Gesundheitscoach**

> **Development project / Entwicklungsprojekt.** PenguCoach analyses fitness, training and wellness data. It is not a medical device and does not replace qualified medical, sports, physiotherapy or nutrition advice. Every new login requires confirmation of the Development & Health Notice.

PenguCoach is designed as a local-first, multi-user platform that reads Garmin Connect data, archives original FIT files, calculates deterministic activity metrics and can use local or cloud LLMs for contextual training analysis.

## Current alpha scope

`v0.1.0-alpha.2` is the hardened first end-to-end deployment baseline:

- German and English web UI
- first-run administrator setup
- multi-user local authentication
- mandatory safety/development gate after every login
- Garmin Connect login with MFA
- encrypted Garmin token persistence; Garmin password is never stored
- allow-list based **strict read-only** Garmin gateway
- configurable automatic sync with jitter, lock, 429 cooldown and reconnect state
- daily Garmin data ingestion for health, sleep, HRV, stress, Body Battery, hydration, respiration, SpO₂, intensity, training readiness/status, max metrics, body data and activities where the account/device exposes them
- immutable original FIT download
- FIT parsing and Parquet time-series storage
- deterministic FIT analytics: HR/pace/power/cadence drift, aerobic decoupling, pace consistency and data coverage
- activity list and detail view with FIT time series
- health overview and historical charts
- Ollama, OpenAI, Anthropic and OpenAI-compatible provider management
- cloud-health AI disabled per user by default; local Ollama can be used without cloud permission
- basic evidence-constrained Coach chat using local Garmin/FIT facts
- PostgreSQL + Redis/Celery
- Alembic schema baseline
- native Proxmox LXC installer with Debian 13 `nesting=1`, UTF-8 locale/database setup and explicit Nginx reload
- `pengucoach-update`, `pengucoach-backup`, `pengucoach-status`, `pengucoach-db-utf8`
- Docker Compose for development/alternative deployments

Training-plan generation, advanced baselines, correlation explorer and the full LangGraph multi-agent workflow remain planned work; the UI intentionally marks unfinished areas instead of pretending they are complete.

## Proxmox installation

Requirements:

- Proxmox VE host with internet access
- root shell on the Proxmox host
- a Debian 13 LXC template available through `pveam`
- DHCP on the selected bridge, unless you adapt the installer

Run on the **Proxmox host**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh)"
```

The installer asks for CT ID, CPU, RAM, disk, bridge and storage. Defaults are 4 vCPU, 4 GB RAM and 32 GB disk. It creates an unprivileged Debian 13 LXC, clones this repository and installs PostgreSQL, Redis, FastAPI, Celery, Next.js and Nginx natively inside the container.

After installation open:

```text
http://<LXC-IP>/
```

There is no default administrator password. The first browser session creates the administrator through `/setup`.

Detailed instructions: [`install/proxmox/README.md`](install/proxmox/README.md)

## Update

Inside the PenguCoach LXC:

```bash
pengucoach-update
```

Or directly from the Proxmox host:

```bash
pct exec <CTID> -- pengucoach-update
```

The updater creates a backup, fetches the configured Git branch, updates Python dependencies, applies Alembic migrations, rebuilds Next.js, restarts services and performs a health check.

Status:

```bash
pct exec <CTID> -- pengucoach-status
```

Manual backup:

```bash
pct exec <CTID> -- pengucoach-backup
```

Early alpha installations that still use a PostgreSQL `SQL_ASCII` database can be migrated safely with:

```bash
pct exec <CTID> -- pengucoach-db-utf8
```

## Docker development quick start

Copy the environment template and generate secrets:

```bash
cp .env.example .env
python3 - <<'PY'
import secrets
from cryptography.fernet import Fernet
print("PENGUCOACH_JWT_SECRET=" + secrets.token_urlsafe(48))
print("PENGUCOACH_ENCRYPTION_KEY=" + Fernet.generate_key().decode())
PY
```

Place the two values in `.env`, then:

```bash
docker compose up --build
```

Web: `http://localhost:3000`  
API docs: `http://localhost:8000/docs`

## Activity Detail v2

Since `0.1.0-alpha.3`, parsed FIT activities include a richer deterministic detail view before AI interpretation: interactive overlay/stacked charts, min/average/max sensor values, elevation and grade, kilometre/100 m splits, channel coverage, and sport-specific FIT lap/set/length tables when the recording device provides them. See [`docs/ACTIVITY_DETAIL_V2.md`](docs/ACTIVITY_DETAIL_V2.md).

## Data flow

```text
Garmin Connect (read only)
        ↓
Raw source records + normalized PostgreSQL data
        ↓
Original FIT → Parquet → deterministic analytics
        ↓
Context builder
        ↓
Ollama / OpenAI / Anthropic (subject to user privacy settings)
        ↓
PenguCoach interpretation
```

AI is deliberately near the end of the pipeline. Numbers that can be calculated deterministically are calculated by PenguCoach before an LLM sees the context.

## Garmin read-only policy

PenguCoach does **not** expose generic access to the Garmin client. `GarminReadOnlyGateway` contains an explicit allow-list of getters/download operations. Methods that upload, edit, delete, schedule, add hydration, add weight, or otherwise mutate Garmin data are unavailable to the application and the AI layer.

The integration uses the unofficial `python-garminconnect` project. Garmin can change its private web services at any time, so the gateway is intentionally isolated and replaceable.

## Repository layout

```text
apps/web/                 Next.js UI
apps/api/                 FastAPI API and routers
pengucoach/               Domain/application code
pengucoach/garmin/        Auth, read-only gateway and sync
pengucoach/fit/           FIT storage/parser/analytics
pengucoach/llm/           Provider adapters and routing
worker/                   Celery workers/scheduler
db/migrations/            Alembic schema migrations
install/proxmox/          LXC install/update/backup tools
docs/                     Architecture and operations docs
tests/                    Unit/integration tests
```

## Security and privacy defaults

- Garmin password is used for authentication only and is not persisted.
- Garmin token bundles and LLM API keys are encrypted at rest.
- Secrets are never returned by the API after storage.
- Cloud AI access to a user's health/training context is **off by default**.
- Local-only mode prevents silent cloud fallback.
- Exact Garmin mutation operations are not exposed.
- Health/FIT files remain local unless the user explicitly allows eligible cloud AI processing.

See [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).

Garmin and Garmin Connect are trademarks of Garmin Ltd. or its subsidiaries. PenguCoach is an independent development project and is not affiliated with or endorsed by Garmin.
