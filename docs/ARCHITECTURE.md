# PenguCost Architecture

## Design goals

1. Core app must continue to work without Internet access.
2. Deployment should be simple enough for a small home server or Proxmox LXC.
3. Recurring finances must remain understandable without bookkeeping knowledge.
4. Financial and AI data are isolated per authenticated user.
5. AI is optional and remains outside the core CRUD/reporting path.
6. Releases must remain easy to deploy through Docker or the guided Proxmox installer.

## Runtime

The frontend is compiled during the Docker build and copied into the backend image. FastAPI serves both `/api/*` and the SPA. SQLite stores all persistent state under `/data`.

## Persistence

`/data` contains:
- `pengucost.db`
- `.session_secret`
- `.fernet_key`

All three must be included in backups. Losing the Fernet key means already stored AI API keys can no longer be decrypted, but financial data remains readable.

## Multi-user ownership

Income/expense rows carry `created_by`. Normal financial queries always filter on the authenticated user, including dashboard, reminders, exports and AI context generation. Administrator privileges manage users, global account/category templates and AI profiles but do not implicitly bypass financial ownership in the normal UI/API.

Accounts and categories are shared administrator-managed templates. A member can hide a template for their own view without deleting it globally.

## Effective-dated prices

Each financial entry has one or more price phases in `expense_prices`. A phase starts on `valid_from` and remains valid until the next phase begins. Editing a price creates or updates a phase instead of rewriting prior periods. This keeps historical reporting stable and also allows future price changes to be scheduled.

## Contract terms

Contracts store exact dates and therefore do not assume calendar-year boundaries. `minimum_term_months` can calculate an end date when one is not entered explicitly. Auto-renewing contracts store `renewal_period_months`; newly enabled automatic renewal defaults to 12 months in the UI until the user chooses another value.

## Recurring normalization and year projection

`monthly_equivalent = price_effective_on_date / interval_months`

`yearly_equivalent = monthly_equivalent * 12`

Supported presets use 1, 3, 6 and 12 months. A custom interval stores an arbitrary positive month count.

The dashboard year model is deterministic rather than predictive market forecasting:
- the real current year is the default after login;
- historical years appear only when the current user has relevant stored periods;
- future choices include current year +1, +2 and +5;
- every projected month uses the price phase valid in that month;
- contract starts/ends are respected;
- paused/ended entries are excluded from current/future projections;
- active auto-renewing contracts are extended by their configured renewal period;
- contracts without automatic renewal disappear after their known end.

The UI deliberately displays only year numbers in the picker. Explanatory text below the picker distinguishes current, historical and future projections.

## AI Agent data flow

PenguCost AI uses persistent per-user conversations instead of a one-shot result box.

For each turn:
1. The UI creates/opens a conversation and sends a message plus selected financial entry IDs.
2. The backend revalidates every selected ID against the authenticated owner.
3. A user message and a `running` conversation state are committed to SQLite before the HTTP response returns.
4. A background task opens its own database session, builds a reduced structured finance payload, loads only that user's Brain/history and calls the selected enabled AI profile.
5. The assistant response is stored as an `ai_messages` row and the conversation returns to `idle`; failures are stored as `error` with a message.
6. The UI can be left while the task runs. When the user returns, the stored conversation state/result is loaded and a running conversation is polled until completion.

The Brain (`ai_brains`) is one per user. It can be edited manually and is also compactly updated after successful assistant turns. Conversations, messages and Brain memory are part of personal JSON export/import and privileged full-instance backup/restore.

AI profile credentials remain administrator-managed. Claude uses the native Anthropic Messages API; other provider presets use OpenAI-compatible chat completions.

## Reminder state

Reminder actions are stored separately from financial entries using an event key built from reminder kind, cancellation deadline and effective contract end. This lets a user dismiss the current reminder without permanently muting the contract: a later renewal cycle creates a new event key and can notify again.

Marking a contract as cancelled disables automatic renewal and freezes the currently effective contract end. The expense remains active until that date so current cost calculations are not reduced prematurely.
