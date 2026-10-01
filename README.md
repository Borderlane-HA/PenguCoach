# PenguCost 🐧💶

**Know your recurring finances.** PenguCost is a self-hosted, local-first dashboard for recurring expenses, income, subscriptions, contracts, insurance, energy, utilities and other regular cash flows.

The goal is deliberately narrower than a classic budgeting app: **make recurring costs understandable, comparable and actionable** — without turning personal finance into accounting work.

## Highlights

- **Income & expense management** — recurring income and expenses with monthly, quarterly, half-yearly, yearly or custom cycles
- **Normalized cost view** — every item is converted to monthly and yearly equivalents
- **Contract lifecycle** — contract start, minimum term, exact/under-year contract end, cancellation deadline, notice period and configurable renewal period
- **Actionable reminders** — notification bell with configurable lead time, done/snooze/cancel actions and automatic-renewal warnings
- **Accounts & categories** — administrator-managed global templates; members can hide entries only for their own view
- **Interactive cash-flow analysis** — all current user-owned entries are selected by default; toggle individual income/expense items and totals/charts update immediately
- **Historical price phases** — price changes are effective from a chosen date and never rewrite past months
- **Income vs. expense chart** — normalized monthly income, expenses and delta make recurring deficits/surpluses immediately visible
- **Multi-user privacy** — local Admin/Member accounts with strict per-user cost, contract, dashboard, reminder and AI-data isolation
- **JSON export/import** — personal backups for each user plus a complete administrator export/restore of the whole instance
- **German & English** — per-user language preference with an in-app switch
- **Template cloning** — use any existing entry as an unsaved template; nothing is created until the new entry is explicitly saved
- **Themes** — System, Light, Midnight, Nordic, Graphite and Emerald with flash-free theme loading
- **Local visual assets** — modern PenguCost SVG favicon and UI assets ship with the app; no external CDN is required
- **PenguCost AI Agent** — persistent per-user chat history, editable Brain memory, background analysis jobs and admin-managed profiles for Ollama, OpenAI, Grok/xAI, Gemini, IONOS AI Model Hub, Claude and custom endpoints
- **Local-first & offline capable** — no CDN, no telemetry, no cloud dependency for the core app
- **Docker & Proxmox** — Docker Compose plus a Proxmox VE 8/9 LXC installer
- **Backup-friendly** — all persistent state lives in one Docker volume

## What PenguCost is for

Examples:

| Entry | Billing | Stored amount | Monthly equivalent | Yearly equivalent |
|---|---:|---:|---:|---:|
| ChatGPT Plus | monthly | €22.90 | €22.90 | €274.80 |
| Car insurance | yearly | €840.00 | €70.00 | €840.00 |
| Electricity service | quarterly | €180.00 | €60.00 | €720.00 |

This makes unlike billing cycles directly comparable while retaining the real payment cycle.

## Screens / Information Architecture

### Overview
- Monthly recurring expenses
- Monthly recurring income
- Monthly delta (surplus/deficit)
- Yearly equivalents
- Number of current contracts
- Income-vs-expense 12-month comparison
- Separate expense and income breakdowns by category
- Interactive selector that instantly changes all calculations and charts
- Upcoming cancellation and contract-end timeline
- Year picker with current-year default, automatically available history and deterministic future projections from known contract/price data

### Income & Expenses
Each item is explicitly marked as **Expense** or **Income** and can contain:
- Name and provider
- Amount and currency
- Billing interval / custom month interval
- Category (administrators can create a missing global category directly from the entry form)
- Account / payment route
- Contract start
- Minimum term in months (optional helper)
- Exact contract end, including under-year dates
- Next due date
- Cancellation deadline
- Notice period in days
- Automatic renewal and renewal period in months
- Cancellation acknowledgement date when a contract has actually been cancelled
- Effective-dated price history (old prices remain immutable for past reporting)
- Essential/non-essential marker
- Tags and **Notes (for AI analysis)** — describe the purpose/benefits/constraints so the model has useful context
- Active / paused / cancelled / ended status

### Price history and contract terms
When a recurring cost changes, edit the item, enter the new amount and choose **New price valid from**. PenguCost creates a new price phase instead of overwriting the previous one. Historical charts therefore continue to use the amount that was valid at that time. Future price changes can also be scheduled in advance.

Contracts are date-based rather than calendar-year based. A contract may start or end on any date. If a start date and minimum term are supplied without an explicit contract end, PenguCost calculates the end date automatically. An explicit contract end always wins.


### Reminder center
The bell in the top bar shows the number of contracts that currently need attention. The reminder lead time is configured **per user** in **Settings → Cancellation reminders**.

Each reminder can be handled directly:
- **Done** hides only the current reminder cycle. A later renewal/cancellation cycle creates a new reminder.
- **Remind later** snoozes the current event for 1, 3, 7, 14 or 30 days, but never beyond the last cancellation day.
- **Contract cancelled** requires confirmation, disables automatic renewal, freezes the current effective contract end and records the cancellation action date. The cost remains active until the actual contract end.

This state is stored in SQLite and therefore survives restarts and upgrades.

### Export & import
Every user can export a portable JSON file containing their own expenses/contracts, historical price phases, hidden global accounts/categories, reminder state, theme, language, **AI chat history and Brain memory**. Import replaces only that user's private PenguCost data; global catalogs and other users are untouched.

Administrators additionally have a **complete instance export/import**. It contains users (password hashes), all user-owned expenses, global catalogs, settings, AI profiles, AI conversation history and per-user Brain memory. AI API keys are exported in a restorable form so a full export must be treated like a sensitive backup. A full import replaces the PenguCost database and is intended for restore/migration.

### Languages
PenguCost ships with German and English UI language packs. The selected language is stored per user under **Settings → Language** and follows the user across browsers after login.

### PenguCost AI Agent
Administrators create one or more AI profiles in Settings and decide which profiles are enabled for users. Provider presets are available for **Ollama, OpenAI, Grok/xAI, Google Gemini, IONOS AI Model Hub, Claude/Anthropic and custom OpenAI-compatible endpoints**.

Members can only choose an enabled profile. They cannot see or edit endpoints, API keys or provider configuration. The AI Agent is strictly scoped to the signed-in user and provides:

- persistent per-user chat conversations and history
- a personal editable **Brain** that carries useful context across conversations
- background analysis jobs: navigation away from the page does not discard a running request; returning shows the running state or stored result
- two guided starts: **simple recurring-cost check** or a concrete **monthly savings target**
- a compact data picker with search, income/expense filters and collapsible category groups instead of an ever-growing chip list
- follow-up chat after the initial analysis without losing the selected financial context
- explicit use of **Notes (for AI analysis)** as purpose/benefit/constraint context

All selected entry IDs are revalidated server-side against the authenticated owner before financial data is sent to the model. Chat history and Brain memory are included in the user's JSON export/import. The system prompt tells the model **not to invent market prices or offers** and not to expose chain-of-thought. Claude uses the native Anthropic Messages API; the other presets use OpenAI-compatible chat completions. External AI is optional; Ollama can keep AI traffic local.

## Docker installation

```bash
git clone https://github.com/Borderlane-HA/PenguCost.git
cd PenguCost
docker compose up -d --build
```

Open:

```text
http://SERVER-IP:8080
```

On first start, PenguCost asks you to create the first administrator.

## Proxmox VE installation

PenguCost includes a guided Proxmox installer inspired by the PenguLab/PenguCoach setup flow.

Supported:
- Proxmox VE 8.x → Debian 12 LXC
- Proxmox VE 9.x → Debian 13 LXC
- unprivileged LXC with nesting/keyctl for Docker
- Quick Setup with sensible defaults
- Advanced Setup for VMID, hostname, CPU, RAM, swap, disk, storage, bridge, DHCP/static IPv4, VLAN, web port and source channel
- Main branch, latest stable release/tag or exact tag
- automatic cleanup offer if installation fails after LXC creation
- built-in status, backup, restore and update helpers

Run directly on the **Proxmox host as root**:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCost/main/scripts/proxmox-install.sh)
```

### Quick Setup

Quick Setup currently uses:

```text
VMID       next free Proxmox ID
Hostname   pengucost
CPU        2 cores
RAM        2048 MB
Swap       512 MB
Disk       8 GB
Bridge     vmbr0
Network    DHCP
Web port   8080
Source     main
```

Before anything is created, the installer displays the complete configuration and asks for confirmation.

### Advanced Setup

Advanced Setup lets you choose:

- container ID and hostname
- CPU, RAM, swap and disk size
- rootfs storage and template storage
- network bridge
- DHCP or static IPv4/CIDR + gateway
- optional VLAN tag
- PenguCost web port
- `main`, latest stable release/tag or an exact Git tag

The installer first downloads/checks the selected PenguCost source and prepares the Debian template. **The LXC is only created after those preflight steps succeed.** This avoids leaving a half-created container because a GitHub release asset or source ref is missing.

### What is installed where?

The installer itself runs on the Proxmox host, but Docker and PenguCost are installed **inside the new unprivileged LXC**. It does not install Docker on the Proxmox host.

Inside the LXC:

```text
/opt/pengucost-src     checked-out/extracted PenguCost source
/opt/pengucost         runtime compose file + installed version
/var/backups/pengucost automatic/manual backups
```

### Management commands

From the Proxmox host, for example with LXC `103`:

```bash
pct exec 103 -- /usr/local/sbin/pengucost-status
pct exec 103 -- /usr/local/sbin/pengucost-backup
pct exec 103 -- /usr/local/sbin/pengucost-update main
pct exec 103 -- /usr/local/sbin/pengucost-update stable
```

Restore a backup:

```bash
pct exec 103 -- /usr/local/sbin/pengucost-restore /var/backups/pengucost/<backup-file>.tar.gz
```

Updates create a data backup before downloading/building the new source.

### Offline behavior

The initial installation requires Internet access for the Debian template/packages and the Docker image build dependencies. The selected PenguCost source is downloaded **before LXC creation**.

**After installation the PenguCost core application does not require Internet access.**

Network access is only needed for:
1. deliberately requested PenguCost updates, or
2. an optional externally hosted AI endpoint.

If installation fails after the LXC has been created, the installer offers to remove the incomplete LXC automatically. This can also be controlled for scripted installs using `AUTO_CLEANUP=yes` or `AUTO_CLEANUP=no`.

## Build an offline bundle locally

The release workflow can still create a self-contained PenguCost Docker image bundle for manual/offline Docker deployment:

```bash
./scripts/build-offline-bundle.sh 0.3.0
```

This creates:

```text
dist/pengucost-offline-amd64.tar.gz
```

The guided Proxmox installer no longer depends on this release asset. It installs directly from the selected Git source and therefore cannot fail just because a GitHub release bundle has not been published yet.

## Updating a Proxmox installation

Inside the LXC the installer creates:

```bash
pengucost-update latest
```

From the Proxmox host:

```bash
pct exec <VMID> -- /usr/local/sbin/pengucost-update latest
```

Or update to a specific release tag:

```bash
pct exec <VMID> -- /usr/local/sbin/pengucost-update v0.3.0
```

The persistent `/data` Docker volume is not replaced by an update.

## Backup & restore

```bash
./scripts/backup.sh
./scripts/restore.sh pengucost-backup-YYYYMMDD-HHMMSS.tar.gz
```

For a Proxmox deployment, a normal Proxmox LXC backup additionally protects the whole container.

## AI profile configuration

As administrator open **Settings → AI providers & models**. Add as many profiles as required and choose a provider preset, profile name, base URL, model and API key. Each profile can be enabled or disabled for normal users independently.

Normal users only see the profile name, provider and model in the **AI Agent**. Base URLs and API keys remain admin-only. API keys are encrypted before they are stored in the local database. PenguCost itself does not ship a cloud account or relay service.

## Architecture

```text
Browser
  │
  ▼
React + Vite UI
  │  same origin /api
  ▼
FastAPI
  ├── Auth / local users
  ├── Expense & contract API
  ├── Dashboard calculations
  ├── Optional AI client
  └── SQLite /data/pengucost.db
```

The production Docker image contains both the compiled React frontend and the FastAPI backend, so no external web assets are fetched at runtime.

## Repository layout

```text
PenguCost/
├── backend/
│   ├── app/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
├── scripts/
│   ├── proxmox-install.sh
│   ├── install-docker.sh
│   ├── install-offline.sh
│   ├── backup.sh
│   └── restore.sh
├── docs/
├── .github/workflows/
├── docker-compose.yml
└── README.md
```

## Security choices in the MVP

- Argon2 password hashing
- HTTP-only session cookie
- Local session signing secret generated on first launch
- Local encryption key generated on first launch for stored AI API keys
- Unprivileged Proxmox LXC
- Docker container drops Linux capabilities and enables `no-new-privileges`
- No external frontend assets or telemetry

For Internet-facing installations, place PenguCost behind a trusted HTTPS reverse proxy and an appropriate access policy. The default design assumes a private LAN/VPN deployment.

## Planned next steps

- Home Assistant / SMTP delivery for reminder-center events and upcoming annual payments
- SMTP / Home Assistant webhook notifications
- CSV import/export
- Contract document attachments
- Historical year-over-year comparison and price-change deltas
- Optional household sharing of selected individual costs between users
- OIDC as an optional alternative to local users
- Savings goals with progress tracking
- Optional price/provider research as a separate explicit online feature
- PWA support

## License

PenguCost ships with a source-available personal/non-commercial license in `LICENSE`. Commercial resale, paid hosting and white-label distribution require separate permission.


### Added in 0.1.2
- Configurable category colors used throughout the overview.
- Reminder bell for cancellation deadlines and automatic renewals.
- Configurable reminder lead time in Settings.



### Added in 0.1.7
- Strict per-user isolation for expenses, contracts, dashboards, reminders and AI payloads.
- Admin-managed global account/category templates with per-user hide/restore behavior.
- Multiple admin-managed AI profiles and provider dropdowns for Ollama, OpenAI, Grok/xAI, Gemini, IONOS, Claude and Custom.
- Members can use enabled AI profiles but cannot manage or inspect credentials/endpoints.
- Dashboard now selects all active own costs by default and automatically includes newly added costs.
- Dashboard year selector: current year by default, available historical years based on stored data, plus forecast targets for +1, +2 and +5 years.
- Historical/forecast views recalculate monthly averages, annual totals, categories, contract dates and cash-flow charts for the selected year.

### Fixed in 0.1.6

- Added explicit Vite/CSS TypeScript declarations so production builds accept the global `styles.css` side-effect import.
- The Proxmox install path is now verified with the real frontend production build (`tsc -b && vite build`).

### Added in 0.1.5
- Clear, unambiguous `PENGUCOST` banner in the guided Proxmox installer.
- Fixed Debian 13 Docker installation where `docker.io` could be installed without the separate Docker CLI when recommendations were disabled.
- Installer now verifies both the Docker CLI and Docker Compose before copying/building PenguCost.

### Added in 0.1.4
- Guided Proxmox VE installer with Quick and Advanced setup modes
- Preflight source download before LXC creation
- Main / stable / exact-tag install channels
- DHCP/static IPv4, VLAN and port configuration in the installer
- Automatic cleanup prompt for incomplete LXC installations
- `pengucost-status`, `pengucost-backup`, `pengucost-restore` and source-based `pengucost-update` helpers
- Docker remains isolated inside the unprivileged LXC; nothing is installed on the Proxmox host itself

### Added in 0.1.3
- Persistent reminder actions: Done, Remind later and Contract cancelled.
- Snooze presets with protection against snoozing past the cancellation deadline.
- Cancellation acknowledgement keeps costs active until the real contract end while disabling auto-renewal.
- Completed/expired contract periods no longer count toward current dashboard totals.
