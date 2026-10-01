# Changelog

## 0.3.0

- Replaced the one-shot AI analysis screen with the persistent **PenguCost AI Agent**: per-user conversations, follow-up chat, history and editable Brain memory.
- AI requests now run as persisted background jobs; leaving the AI page no longer loses the running state or completed result.
- Added guided AI start modes for a general recurring-finance check or a concrete monthly savings target.
- Strengthened the AI Agent prompt with exact selected-income/expense/delta context, protected essential entries, realistic savings contribution/cumulative-gap logic and structured JSON finance context.
- Reworked the AI data selector into a searchable modal with expense/income filters and collapsible category groups for large datasets.
- Extended personal JSON export/import and administrator full backup/restore with AI conversations, messages and Brain memory.
- Added a modern local SVG PenguCost favicon.
- Simplified the dashboard year menu to year numbers only while keeping the real current year as the default after login.
- Hardened deterministic history/forecast projection to continue from the latest effective renewal cycle, use known price phases and contract dates, and default newly enabled automatic renewal to a 12-month period until changed explicitly.
- Administrators can create a missing global category directly while creating/editing an entry.
- Changed cloning into **Use as template**: opening a clone creates only an unsaved draft, clears identity/contract-specific fields and does not imply a relationship to the source entry. Closing the modal with X or Cancel never creates data.
- Hardened AI ownership checks so selected IDs are always revalidated against the authenticated user before model calls.

## 0.2.1

- Added an explicit dashboard year selector while keeping the current year as the default view.
- Historical years appear automatically only when the signed-in user has relevant contract/price data for those years.
- Added forecast targets for +1, +2 and +5 years.
- Forecast calculations use known price phases, contract terms and automatic renewal periods instead of copying today's total unchanged.
- Historical/forecast views calculate year totals and average monthly expense, income and delta for the selected year.
- Category breakdowns and the interactive item selector now follow the selected dashboard year.
- Upcoming dates switch from the current 60-day window to contract/cancellation dates inside the selected historical or forecast year.
- The selected year is shown prominently in the dashboard and in the cash-flow chart subtitle.


## 0.2.0

- Added recurring **income** alongside expenses using a backwards-compatible `entry_type` field. Existing entries migrate automatically as expenses.
- Fixed overview selection so cancelled-but-still-running contracts remain in current totals until their effective contract end; only paused/ended entries are excluded.
- Reworked the overview into expense, income and monthly-delta metrics.
- Added an income-vs-expense 12-month chart with an explicit delta line.
- Added separate category breakdowns for expenses and income.
- Added expense/income grouping to the interactive dashboard selector.
- Added type filtering and a type column to the Income & Expenses list.
- Annual/quarterly entries are normalized into monthly equivalents in the recurring cash-flow chart, so yearly subscriptions remain visible every month.
- AI analysis now receives only the current user's selected entries, including explicit income/expense types, separate totals and delta.
- Reworked the AI system prompt for concrete, structured, decision-ready Markdown output without invented market prices.
- Added richer AI result rendering with headings and bullet lists.
- Removed the explanatory user-permission text below the AI analysis button.


## 0.1.9

- Added per-user German/English language packs with a user-level language switch.
- Added application version display below the signed-in user in the sidebar.
- Added personal JSON export/import for expenses, price history, hidden accounts/categories, reminders, theme, language and saved AI-analysis prompt.
- Added administrator full JSON export/import for all users, expenses, catalogs, settings and AI profiles; AI keys are exported in restorable form and the file must be treated as sensitive.
- Added expense cloning from the Costs & Contracts table.
- Removed example placeholders from the new-expense form.
- Renamed notes to “Notes (for AI analysis)” / “Notizen (für KI-Analyse)” and explicitly instructs the AI to use this context when evaluating a cost.
- Fixed dashboard selection so every active expense belonging to the current user is selected after a full refresh.
- AI Analysis now has its own per-analysis cost selector, defaults to all active expenses for the current user and remains strictly user-isolated server-side.
- Added persistent per-user AI prompt storage so it is included in user exports.
- Updated Proxmox management examples to use absolute helper paths under `/usr/local/sbin`.

## 0.1.8

### Fixed
- Fixed Proxmox/LXC backups failing with `Permission denied` when the application image runs as the unprivileged `pengucost` user.
- Backup and restore utility containers now run as root only for filesystem/archive operations; the PenguCost application remains unprivileged.
- Proxmox helper scripts invoke repository scripts through `bash`, so updates no longer depend on Git archive executable bits.
- Installer output now uses absolute `/usr/local/sbin/pengucost-*` helper paths for reliable `pct exec` usage.

## 0.1.7

- Enforced strict per-user ownership for expenses, dashboards, reminders and AI payloads. Administrators no longer see other users' cost data.
- Global accounts and categories are managed by administrators and shared as templates with all users. Non-admin deletion now hides a template only for that user, with a restore option.
- Added admin-managed AI profiles with provider presets for Ollama, OpenAI, Grok/xAI, Google Gemini, IONOS AI Model Hub, Claude/Anthropic and custom OpenAI-compatible endpoints.
- Non-admin users can only select enabled AI profiles for analyses and cannot view or modify base URLs, API keys or model configuration.
- Added native Anthropic Messages API support for Claude profiles while retaining OpenAI-compatible chat-completions for the other providers.
- Made cancellation reminder lead time user-specific.
- Fixed dashboard selection so all active expenses are selected initially and newly created expenses are automatically added without re-selecting previously excluded items.
- Added safe migration of orphaned legacy expenses to the first administrator and migration of the former single AI configuration into a profile.

## 0.1.6

### Fixed
- Added `frontend/src/vite-env.d.ts` with Vite/CSS declarations so `tsc -b` can resolve the global stylesheet side-effect import during Docker builds.
- Updated project version references and installer tag example to 0.1.6.

## 0.1.5

### Fixed
- Replaced the ambiguous ASCII art with a clearly readable `PENGUCOST` installer banner.
- Fixed Proxmox VE 9 / Debian 13 installs where `docker.io` was installed with `--no-install-recommends`, leaving the separately packaged Docker CLI unavailable and causing `docker: command not found` during the image build.
- Docker installation now keeps package recommendations enabled for cross-version Debian compatibility and explicitly verifies the Docker CLI before continuing.
- Added a Docker Compose availability check before the PenguCost source is copied/built.

## 0.1.4

### Changed
- Reworked the Proxmox VE installer to use the guided PenguLab/PenguCoach-style setup flow.
- Added Quick Setup and Advanced Setup before any LXC is created.
- Advanced mode now configures VMID, hostname, CPU, RAM, swap, disk, rootfs/template storage, bridge, DHCP/static IPv4, VLAN, web port and source channel.
- PenguCost source is downloaded and validated before LXC creation, preventing the previous release-bundle 404 from leaving a half-installed container.
- Proxmox deployment now builds the selected source inside the LXC and therefore no longer depends on a GitHub release asset being present.
- Failed installations now offer automatic cleanup of the incomplete LXC.
- Added in-LXC helpers: `pengucost-status`, `pengucost-backup`, `pengucost-restore` and `pengucost-update`.
- Source-based updates create a backup before building/restarting PenguCost.
- Normal runtime remains offline-capable after installation; Internet is only required for installation, updates and optional external AI endpoints.

## 0.1.3
- Added persistent reminder actions: Done, Remind later, and Contract cancelled.
- Added snooze presets for 1/3/7/14/30 days with deadline capping.
- Added two-step confirmation before marking a contract as cancelled.
- Contract cancellation now freezes the current effective term, disables auto-renewal, records the cancellation date, and keeps costs active until term end.
- Added per-reminder event keys so completed reminders can return correctly for later renewal cycles.
- Current dashboard/AI totals now exclude effectively expired non-renewing contracts.
- Added automatic in-place migration from 0.1.2 for cancellation acknowledgement and reminder state storage.

## 0.1.2
- Added configurable colors for all cost categories.
- Category colors are now used in the dashboard donut chart and category badges.
- Added configurable cancellation reminder lead time in Settings.
- Added notification bell with reminder count and a contract reminder center.
- Added separate reminder states for cancellation deadlines, imminent automatic renewals, and already renewed contracts.
- Improved cancellation notice input with common presets plus a custom-day option.
- Added automatic in-place migration from 0.1.1 for the new category color field.

## 0.1.1

- Added effective-dated price history; changing a subscription price no longer rewrites historical periods
- Added support for scheduled future price changes
- Added minimum contract term in months and automatic contract-end calculation
- Added configurable auto-renewal periods in months
- Added effective upcoming contract/cancellation dates for renewed contracts
- Updated annual payment forecast to use the price valid on each payment date
- Added in-place SQLite migration from 0.1.0 and automatic seeding of existing prices into history

## 0.1.0

Initial PenguCost foundation:
- Recurring expense and contract management
- Monthly/yearly normalization
- Contract and cancellation dates
- Account and category assignment
- Interactive dashboard filtering
- Annual payment forecast
- Multi-user local authentication
- Six themes
- Optional OpenAI-compatible AI analysis
- Docker deployment
- Proxmox VE 8/9 installer
- Offline release bundle workflow
- Backup and restore scripts
