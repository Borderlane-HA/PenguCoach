# SparkyFitness connection

PenguCoach supports SparkyFitness as an optional **read-only** health and training source alongside the direct Garmin connection.

## Supported baseline

The integration targets the SparkyFitness v1.7.x API surface and was developed against the v1.7.2 Swagger contract. SparkyFitness is under active development, so PenguCoach probes endpoint capabilities when the connection is created or tested instead of assuming every API key has every read permission.

## Connection

Open **Connections & settings → SparkyFitness** and provide:

- the normal SparkyFitness frontend URL, e.g. `https://fitness.example.com`;
- a SparkyFitness API key.

PenguCoach normalizes the URL to the `/api` base automatically. A Swagger URL such as `/api/api-docs/swagger/` is also normalized back to the API base.

The API key is encrypted with `PENGUCOACH_ENCRYPTION_KEY` before it is stored. It is never returned by the PenguCoach API.

## Read-only scope

PenguCoach currently uses GET requests only. It never writes, edits, or deletes data in SparkyFitness.

Capability checks cover:

- exercise/workout history;
- sleep;
- daily check-in/body measurements;
- custom metrics such as HRV or resting heart rate where exposed;
- dashboard daily metrics.

## Data precedence

Direct Garmin data remains authoritative for Garmin-specific metrics such as training readiness, Body Battery, Garmin training load/status, and Garmin workout/calendar operations.

SparkyFitness fills missing general health data such as steps, sleep, body measurements, HRV/resting heart rate where available. Workout sessions are also materialized into the normal activity diary when they contain enough session-level information. Before materialization, PenguCoach enriches compact history rows from SparkyFitness `GET /exercise-entries/{id}` and prefers those relational headline values for distance, duration, calories and other available activity stats. Provider activity details are only used as a fallback when core values are still absent. Existing Garmin canonical values are not overwritten.

Because SparkyFitness can itself contain Garmin-synced data, PenguCoach performs conservative duplicate matching by sport family, start time, duration and distance. A likely match is kept as one activity with `Garmin + SparkyFitness` provenance; otherwise the Sparky session receives its own local activity row. AI context uses the same provenance to avoid double-counting.

## Sync

The SparkyFitness settings page offers 7/14/30/90/180/366 day windows, 2/5/10 year windows and **All data**, plus independent toggles for:

- training & activities;
- sleep;
- daily health, HRV and body data.

Long health/sleep ranges are read in one-year chunks to avoid oversized API responses. Sleep prefers `/sleep/details` and falls back to `/sleep`. The settings page shows the oldest/newest locally stored dates per major domain.

Imported raw records and materialized activity rows remain in PenguCoach after disconnecting the SparkyFitness account.


## Body and smart-scale data

PenguCoach reads body/check-in values when SparkyFitness exposes them, including weight, height, BMI, body-fat percentage, body-water percentage, muscle mass and bone mass. These connected-source values remain read-only and keep per-metric provenance so Garmin values are not silently overwritten.

Users without a smart scale can enter the same body/profile values manually on the Health page. Manual values are stored locally in PenguCoach and remain the current fallback for each metric until a newer Garmin or SparkyFitness measurement for that metric becomes available. They are included in Coach/training context with `manual` provenance.
