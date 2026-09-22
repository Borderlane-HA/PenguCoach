# Changelog

## 0.1.0-alpha.17 - 2026-09-22

### Added
- selectable training-plan context windows of 3, 7, 14, 21 or 28 days, defaulting to 7 days
- per-plan context-category selection for Training/FIT analytics, Garmin zones, sleep/HRV, recovery/stress signals and optional steps/hydration
- live approximate output-token progress for streamed Ollama Coach, activity-analysis and training-plan jobs; final Ollama token counts remain authoritative
- cancellation controls for Coach requests, per-activity AI analyses and training-plan generation, with cooperative worker cancellation and no persisted AI result after cancellation
- Coach cancellation restores the submitted text so it can be edited and resent

### Changed
- Ollama `/api/chat` generation now uses streaming instead of waiting for one complete response; the local read timeout is a between-chunk/first-token safeguard rather than a five-minute total generation ceiling
- training-plan context contains only the selected time window instead of always combining hidden 7-day and 28-day context
- training-plan activity context now includes available PenguCoach FIT analytics alongside Garmin activity facts
- plan metadata stores the selected context window and context categories for later review
- historical release/change-list documents were removed from `docs/`; release history is maintained in this root changelog, while current feature documentation keeps stable filenames

### Fixed
- fixes long local Ollama plans failing after roughly ten minutes when the former 300-second non-streaming HTTP wait timed out and the automatic retry hit the same timeout again
- failed AI background jobs now expose an exception type/details instead of collapsing empty timeout messages to a generic `AI job failed` where possible

## 0.1.0-alpha.16 - 2026-09-22

### Added
- training-plan management for current and legacy plans, including local deletion even when a plan predates the structured Garmin-calendar format
- a three-way delete flow for Garmin-exported plans: remove from Garmin + PenguCoach, remove only from PenguCoach, or cancel
- Garmin cleanup jobs that unschedule PenguCoach-created calendar entries before deleting their Garmin workout templates; failed cleanup keeps the local ledger so it can be retried
- deletion of persisted per-activity AI analyses from Activity Detail
- pause and cancel controls for long Garmin historical imports; completed data is preserved and restart remains resume-safe
- an optimized historical-import mode (default) that keeps full detail for the latest 90 days and uses a smaller core endpoint set for older days

### Changed
- historical imports created by alpha.15 remain reusable: existing `history_day_complete` markers are recognized and skipped by the optimized importer
- old-day optimized imports retain daily summary, sleep, HRV, stress, Body Battery, max metrics/VO2 and body data while avoiding several expensive detail endpoints
- the training-plan LLM receives its exact effective hard output-token budget, estimated session count and a per-session compactness target before generation
- structured-plan instructions now prioritize completing every requested week/session and closing valid JSON before spending tokens on prose or repeated defaults
- transient HTTP interruptions during training-plan generation are retried once automatically
- the sidebar application version is left-aligned with the account/logout controls
- training-plan history can display/manage up to 30 stored plans; activity-analysis history can display/manage up to 20 stored analyses

### Fixed
- prevents compact historical imports from clearing richer full-detail fields when those endpoints were intentionally omitted
- makes pause/cancel checks survive temporary Redis-control read failures without aborting the Garmin import

## 0.1.0-alpha.15 - 2026-09-22

### Fixed
- fixes the Next.js production-build type error in `TrainingPlanCalendar.tsx` by using the shared `Lang` union type instead of a generic string
- keeps the required `0004_garmin_workout_export.py` Alembic migration in the full release and documents it as a required upload for upgrades from alpha.13
- updates stale application-version fallbacks so API/version reporting remains consistent with the checked-out release

### Added
- shows the authoritative running PenguCoach version in the dashboard sidebar directly below Sign out / Abmelden
- exposes `app_version` from `/auth/me`, sourced from the backend's resolved release version instead of duplicating a frontend-only constant

## 0.1.0-alpha.14 - 2026-09-21

Training calendar / Garmin workout export release:

- stores newly generated AI training plans as a validated structured plan document in addition to deterministic human-readable Markdown
- adds a week-by-week calendar view with expandable session details, start-date mapping, required/optional selection and supported/unsupported export states
- adds explicit **Training & Calendar** Garmin settings; workout export is disabled by default while normal Garmin health/activity/FIT synchronization remains read-only
- adds a separate narrow `GarminWorkoutGateway` instead of relaxing the existing read-only gateway
- exports supported running, cycling, swimming, walking, hiking and strength sessions as individual typed Garmin workouts and schedules them on the selected dates
- supports Garmin heart-rate and power-zone targets in structured endurance workout steps and repeat blocks
- uses the Garmin exercise catalogue for structured strength sessions
- adds a per-user export ledger that prevents duplicate exports of the same plan session on the same date and records safe per-session errors
- cleans up an uploaded workout template if calendar scheduling fails, avoiding known orphan templates from partial exports
- runs multi-session Garmin exports in the background with reload-safe job polling and progress
- preserves older prose-only training plans; they remain readable but clearly show that calendar export requires a newly generated structured plan
- adds a final browser confirmation before any selected workouts are written to Garmin
- adds regression coverage for structured-plan validation/rendering/date mapping and for the default-off/narrow-write design

## 0.1.0-alpha.13 - 2026-09-21

### Added
- Garmin heart-rate and power-zone synchronization using the read-only Garmin gateway.
- Versioned local storage for Garmin zone profiles and a `/garmin/zones` status endpoint.
- Garmin training-zone status cards in AI Coach and Training Planning.
- Sport-aware Garmin zone context for Coach Chat, activity analysis and training-plan generation.
- Local FIT time-in-zone calculation using Garmin-provided heart-rate/power boundaries.

### Changed
- Deep activity-analysis prompts now use Garmin zones and PenguCoach/FIT time-in-zone when available.
- Training-plan prompts can prescribe intensities using the user's configured Garmin zones instead of estimated zones.
- Garmin zone refresh runs with normal synchronization and at the start of historical imports without blocking the main sync if the optional zone endpoint is temporarily unavailable.

### Fixed
- iOS/iPadOS number validation for AI maximum-response fields. Values such as 2,500, 3,500 and 8,000 tokens are now accepted because response-token inputs use unit steps instead of an incompatible 100/250 step offset from the 128-token minimum.

## 0.1.0-alpha.12 - 2026-09-21

Large Garmin history / resumable import release:

- replaces day-by-day activity discovery with true offset pagination over Garmin's activity catalogue, continuing until Garmin returns no further page instead of trusting a possibly capped activity count
- imports the complete activity catalogue **before** the slower daily wellness backfill, so hundreds or thousands of activities appear without waiting for years of sleep/HRV/stress requests
- supports date-bounded history imports and **All available data** with a 25-year safety horizon while deriving the wellness start from the oldest activity actually discovered
- batch-upserts each Garmin activity page with one database lookup, eliminating the historical N+1 query pattern
- persists per-day historical completion markers for older wellness days, making interrupted/rate-limited imports safe to restart without re-requesting every completed day
- automatically retries Garmin rate limits with bounded exponential backoff and records a resume-safe rate-limited result if Garmin continues throttling
- uses one per-account Garmin lock so the normal scheduler cannot compete with a long historical import
- exposes live Celery history progress in the Garmin page: activity pages/count, wellness day progress, skipped completed days and FIT queue progress; progress survives a browser reload
- queues even very large historical FIT backlogs directly in Redis while FIT workers consume them at a controlled 30/min rate; per-account/per-activity locks, Garmin rate-limit retries and an already-parsed check prevent bursts and duplicate work
- raises Coach/Activity/Training request ceilings to match AI Studio's configurable 65,536 output / 1,048,576 context settings
- protects the current activity during AI context compression and automatically reduces only the effective output budget when a too-small context window would otherwise squeeze the activity data out
- adds a clear Cloud-AI privacy banner in AI Studio with an explicit enable action, and a useful Privacy link instead of an empty model selector when cloud models are configured but not permitted
- warns directly while configuring any external/Cloud AI provider that health and training data remains blocked until explicit privacy consent is enabled, with one-click enable and Privacy actions
- makes the Health period selector authoritative for every chart family: VO₂ max running/cycling now follows the same 7/30/90 day, 1 year, 5 year or All data window as HRV, resting HR, sleep and stress; coverage counts follow the same range

## 0.1.0-alpha.11 - 2026-09-21

Manual activity import / non-Garmin activity release:

- adds a prominent **Training importieren / Import activity** action to the Activities page
- imports FIT, GPX, TCX and ZIP files containing FIT data without requiring a Garmin account
- stores uploaded activity files locally, creates Parquet time series and runs the existing deterministic activity analytics
- automatically detects activity name/sport where possible, with optional name and sport overrides in the upload dialog
- rejects duplicate imports using the canonical activity-file SHA-256 and limits uploads to 50 MB
- labels manual activities explicitly in the activity history and adapts source/AI wording so imported files are not presented as Garmin data
- makes manually imported activities available to Coach, activity AI analysis and training-plan context together with Garmin activities
- restores the sign-out button in the desktop sidebar and responsive top bar while preserving the newer default app icon/theme/avatar behavior
- adds parser tests for GPX and TCX imports

## 0.1.0-alpha.10

- Fixed fresh Proxmox LXC installs: an empty database is now bootstrapped from the current reviewed schema and Alembic is stamped at head instead of replaying historical migrations against dynamic metadata.
- Fresh-install recovery also works when an interrupted attempt left only a stale `alembic_version` table.
- Added post-bootstrap schema verification for core tables and `activities.vo2max`.
- Made the historical `0002_ai_runs` migration idempotent and added a clear baseline error to `0003_activity_vo2max`.
- Switched early installer locale handling to Debian's built-in `C.UTF-8`, removing the noisy locale bootstrap warnings on minimal Debian 13 containers.
- Added regression tests for the fresh database bootstrap path.

## 0.1.0-alpha.9 - 2026-09-21

Full-history Garmin / sport-specific VO2 release:

- adds **Alle verfügbaren Daten / All available data** to Garmin history import instead of stopping at the previous 5-year UI choice
- discovers the account-specific history start efficiently from Garmin's activity count + oldest activity page, then backfills daily/training/activity domains from that date
- reuses one authenticated Garmin client during long history imports to reduce repeated SSO work and rate-limit pressure
- keeps a conservative 25-year safety horizon, which still covers Garmin Connect's practical lifetime, and extends the long-history worker lock to 72 hours
- adds a 10-year explicit history option alongside the automatic all-data scope
- normalizes Garmin activity `vO2MaxValue` into an indexed activity field and backfills existing activities from their retained raw Garmin summary during migration
- adds separate latest **VO2 max Running** and **VO2 max Cycling** values on the Today dashboard without changing the metric-card grid
- adds a new full-width Health **VO2 max history** chart with distinct Running and Cycling series over all imported activity history
- adds 5-year and **All data** range choices to the general Health trends page
- exposes activity VO2 max to the activity API and AI training context as an official Garmin summary metric
- adds `GET /health/vo2-history` for sport-specific long-term VO2 series

## 0.1.0-alpha.8 - 2026-09-21

UI polish / live Garmin sync / branding release:

- adds a built-in PenguCoach SVG app icon as the default sidebar/login/setup brand mark instead of the plain `P` placeholder
- registers the PenguCoach icon as the browser favicon
- keeps per-user custom app-icon uploads as an override of the default sidebar branding
- turns the Coach and Training Planning top area into one balanced full-width header frame and aligns the active-model panel with the heading/content geometry
- makes manual Garmin synchronization follow the real Celery task until completion instead of only showing that enqueueing succeeded
- keeps the Garmin Sync button disabled while the worker is actually running and resumes polling after a page reload through a stored task id
- automatically refreshes Garmin last/next-sync timestamps when the job finishes and removes the running notice once complete
- replaces the cramped Garmin automation grid with separate **Schedule** and **Activity data** panels and fixes the toggle text/layout overlap
- renames the confusing AI Studio `routes set` KPI to **fixed models**, with an explanatory tooltip for automatic model selection
- fixes provider action layout so Discover/Add/Delete controls stay compact and readable; destructive actions are explicitly labelled instead of using an unclear stretched `×`
- keeps model Edit/Delete actions compact
- re-verifies that the deployment updater performs backup + deterministic `origin/<channel>` alignment without an overwrite confirmation or local-source-change abort
- adds `docs/UI_POLISH_ALPHA8.md`

## 0.1.0-alpha.7 - 2026-09-21

Personalization / Garmin simplicity / AI-provider management release:

- adds per-user appearance themes: **Mint Light**, **Midnight Health**, **Ocean**, **Forest** and **Lavender**
- adds local PNG/JPEG/WebP upload for a user profile picture and a custom PenguCoach sidebar app icon
- stores uploaded appearance assets under `/var/lib/pengucoach/user-assets/<user-id>/`, so existing backups include them automatically
- adds a local dashboard wellness/training SVG illustration with no external dependency
- simplifies Garmin settings around one everyday **Synchronize** action; historical backfill is moved into a clearly separated expandable initial-setup/history section
- keeps historical import available without presenting it as a second routine synchronization action
- adds AI model **edit**, enable/disable and **delete** controls in AI Studio
- adds deletion of complete AI providers and discovery of models from already-saved providers
- updates Anthropic/Claude integration to use the current `GET /v1/models` API and imports model display name, maximum input context and maximum output tokens when available
- keeps Anthropic Messages API on the documented `anthropic-version: 2023-06-01` header and intentionally omits `temperature` for Claude requests to remain compatible with newer Claude models that reject non-default sampling parameters
- increases configurable task ceilings to 65,536 output tokens and 1,048,576 context tokens while keeping recommended presets
- raises recommended defaults for deep Activity Analysis and Training Planning to 16K context / 8K output; Coach Chat remains 8K / 2.5K
- persists provider-reported maximum output tokens on discovered models and clamps generated output to the provider capability when known
- changes `pengucoach-update` to treat `/opt/pengucoach` as a deployment checkout: after backup it automatically replaces local source changes with `origin/<channel>` instead of aborting
- preserves ignored runtime dependencies such as `.venv` and `node_modules` while removing untracked source/build leftovers
- adds `docs/UI_PERSONALIZATION_ALPHA7.md`

## 0.1.0-alpha.6 - 2026-09-21

Bright Health UI / readability release:

- adds four explicit Activity AI context scopes: **Nur dieses Training**, **Dieser Tag**, **3 Tage** and **7 Tage** (with English equivalents)
- **Dieser Tag** includes available Garmin wellness/recovery values for the activity date, including hydration, sleep, HRV, resting HR, stress, Body Battery, Training Readiness and steps when present
- fixes 3-/7-day recovery windows to be true inclusive calendar-day windows instead of loading one extra date
- deep-analysis prompts now adapt to the selected context scope and no longer demand unavailable 3-/7-day sections
- introduces a cohesive light health-and-training design system with mint/teal accents, softer borders, restrained shadows and improved typography
- replaces the dense desktop top navigation with a persistent grouped sidebar and compact contextual header
- adds a responsive five-destination mobile navigation dock for Today, Health, Activities, Training and AI Coach
- redesigns the login experience into a clearer local-first health/product introduction and focused sign-in surface
- rebuilds the Today dashboard with a calmer health hero, readiness/Body Battery focus panel, semantic metric cards, recent activity list and larger 14-day trend surface
- rebuilds the Health page with a clearer period selector, consistent health metric cards, larger trend cards and explicit data-coverage summary
- modernizes the Activities history with search, FIT-analysis counters, sport-aware badges, clearer distance/duration/HR hierarchy and responsive list rows
- refreshes Activity Detail v2, Coach, AI Studio, forms, tables, chips and status elements without changing the underlying Garmin/FIT/AI data contracts
- deliberately keeps the interface light even when the operating system requests dark mode to preserve the new bright health visual language
- adds `docs/UI_REFRESH_ALPHA6.md` documenting the visual system and responsive behavior

## 0.1.0-alpha.5 - 2026-09-21

Modern AI Studio / long-running local-model release:

- redesigns the AI administration into a focused **AI Studio** with task tabs for Coach Chat, Activity Analysis and Training Planning
- adds separate German and English default prompts; the active UI language is sent with every AI job and selects the matching prompt automatically
- adds a configurable **context window** per task (default 8192 tokens) and passes it to Ollama as `num_ctx`
- separates context-window size from maximum response tokens (`num_predict` for Ollama)
- raises sensible local-first defaults to 2500 response tokens for Coach Chat, 3500 for Activity Analysis and 4500 for Training Plans
- visualizes input/output token budgets and offers 4K/8K/16K/32K context presets in AI Studio
- records provider stop reasons and detects responses that hit the output-token ceiling
- shows a clear **response truncated** warning instead of silently presenting incomplete analyses
- moves Coach Chat, Activity Analysis and Training Plan generation to Celery **background jobs** using the already-consumed maintenance queue for seamless alpha.4 upgrades
- AI jobs survive page reloads; the UI stores active task IDs and resumes polling automatically
- avoids browser/proxy 504s for slow local models because long generation no longer depends on one open browser request
- increases the default LLM HTTP timeout to 300 seconds and updates existing alpha.4 environments from the old 120-second default
- adds 300-second Nginx API proxy timeouts for compatibility with synchronous API clients
- Coach context can be Auto, none, 7 days or 28 days; Auto skips Garmin/FIT context for unrelated questions such as general IT topics
- activity AI UI is simplified into a compact modern control panel with model, lookback, context window and response budget
- activity analysis history remains selectable and now shows model, context, token usage and stop reason
- training planning uses the same background-job and context-window controls
- improves AI markdown rendering including `####` and deeper headings
- new installs use a 300-second AI timeout; local providers also enforce a minimum 300-second client timeout so alpha.4 installations work immediately after update

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
