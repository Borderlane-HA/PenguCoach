# Plan Evolution — Alpha.47

## Where to find it

Open a saved plan under **Training → Training calendar → Your plan in real life**.
Save any calendar draft first. Today links directly to the relevant plan, offers
**Plan my next 7 days**, and exposes a short variant for today's next session.
The time from the saved daily check-in preselects the short-variant budget.

## Planned versus actual

- Same local day + same sport family + duration within 25% can match automatically
  only when there is exactly one same-day candidate and no competing session.
- Activities up to three days before/after the planned day are ranked suggestions.
  Shifted dates and uncertain durations always require explicit confirmation.
- A recorded activity can have only one persistent assignment across all plans.
- Confirmed matches and confirmed **Not completed** markers are editable/resettable
  and user-scoped. Missing imports remain **Matching pending**, regardless of the
  last successful sync. Only an explicit past-session confirmation marks it missed.
- Compare planned/actual dates and minutes, available average HR/power, planned
  target zones and recorded FIT laps. Averages/laps are not proof that prescribed
  intervals or zone durations were fulfilled; no such measurement is invented.
- Both Coach context and the plan UI use the same matching service. Completed
  sessions are removed from the next-session list on Today.

## Short variants

Choose a preset or a custom shorter duration, then review the full before/after
steps. Confirm to save; dismiss to keep the calendar.

Timed endurance sessions preserve warmup, cooldown and recovery. Whole interval
repetitions are removed before continuous work is shortened. Remaining time can
be filled with easy untargeted work; interval intensity never increases. Strength
reduces sets while retaining movements, reps and rests. Strength duration remains
an estimate, not a stopwatch guarantee.

If essential steps cannot fit, PenguCoach declines the short variant. Distance
steps require a timed draft, and inconsistent step totals require correction in
the existing workout editor. Workouts without structured steps support only a
clearly labelled duration change without inferred intensity targets.

## Next seven days

The default window begins today in the user's timezone. A start up to seven days
in the future can be selected. Specify 0–480 minutes for each date; zero means
unavailable. Saved training weekdays still apply. Today defaults to the saved
check-in time where available, and other dates default to profile session time.

This deterministic review adapts the **existing saved plan**, without an extra
model call or new workouts. It keeps the original plan IDs, respects plan bounds,
availability, other saved plans, protected Garmin exports, completed sessions,
hard-session spacing, today's readiness/recent feedback and available Open-Meteo
forecast dates. It prefers a date with enough time when practical; otherwise it
can use a reviewed short variant. Unfavorable outdoor weather can propose an
indoor version. Weather outages do not block the review.

Recovery is evaluated only for today. Future recovery is not predicted. Missing
past sessions are not automatically inserted into the week. Impossible constraints
remain explicit unresolved suggestions requiring manual review. Protected workouts
can therefore still conflict with a newly entered zero-minute budget.

Before/after dates, steps, volume and reasons are visible. Apply saves all reviewed
changes and Decision Log entries together in one transaction. Dismiss saves nothing.
A calendar revision and a review fingerprint prevent stale or changed proposals
from being applied. Original AI source plans remain available; overrides are saved
in the existing schedule. Already exported Garmin sessions are locked; changes do
not edit Garmin automatically.

## Data freshness

Today and the comparison show the last successful Garmin/SparkyFitness sync,
connection state and a freshness indication. This timestamp does not prove that
all past days or all health measurements were imported. Missing workouts stay open.

## Upgrade

Alpha.47 adds migration **0014_plan_evolution** for persistent one-to-one activity
assignments. The normal Proxmox updater runs migrations. For Docker installations:

```bash
docker compose build
docker compose run --rm api alembic -c alembic.ini upgrade head
docker compose up -d
```

Use your existing .env and database/data volumes. Back up before updating.

The GitHub web update contains only files changed/added since Alpha.46.1, with
repository-relative paths; it is not a full replacement repository. Upload all
included top-level directories, including apps, pengucoach, db and tests.

## Release validation

- Full Python suite: 196 tests passed; targeted evolution/companion/intelligence
  checks passed after the final scheduling refinements.
- Ruff and Python compilation passed; Next.js 15.5.26 production build passed
  with TypeScript validation.
- Browser interaction checks with mock API data covered week preview/apply and
  Today short-variant preview at 1440 px light/dark and 390 px Nordic Night,
  with no horizontal overflow or page JavaScript exceptions.
- Existing-schema migration upgrade, idempotent upgrade and downgrade were
  exercised in SQLite. The PostgreSQL migration chain remains part of repository
  CI; this session did not run a live Garmin export or a live PostgreSQL server.
