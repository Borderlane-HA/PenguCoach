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

SparkyFitness fills missing general health data such as steps, sleep, body measurements, HRV/resting heart rate where available. Workout sessions are also materialized into the normal activity diary when they contain enough session-level information. HealthKit `Active Calories`/Move-ring entries are explicitly treated as daily health metrics: they may fill the day's active-calorie value when Garmin has not already supplied it, but they are never materialized as workouts.

Before materialization, PenguCoach enriches compact history rows from SparkyFitness `GET /exercise-entries/{id}` and prefers those relational headline values for distance, duration and calories. If useful workout details such as heart rate or elevation are still missing, PenguCoach also asks the provider-detail endpoint. SparkyFitness v3 `telemetry` and JSON/JSON-string `raw_data` are understood, including HealthKit `startTime`, duration objects and `totalEnergyBurned`. Existing Garmin canonical values are not overwritten.

Recorded timestamps have precedence over SparkyFitness audit/import timestamps. `startTime`, `entry_timestamp`, `logged_at`, `measured_at` and the explicit entry date are considered before `created_at`, so historical HealthKit data keeps the date/time on which it was actually recorded.

Because SparkyFitness can itself contain Garmin-synced data, PenguCoach performs conservative duplicate matching by sport family, start time, duration and distance. A likely match is kept as one activity with `Garmin + SparkyFitness` provenance; otherwise the Sparky session receives its own local activity row. AI context uses the same provenance to avoid double-counting.

## Sync

The SparkyFitness settings page offers 7/14/30/90/180/366 day windows, 2/5/10 year windows and **All data**, plus independent toggles for:

- training & activities;
- sleep;
- daily health, HRV and body data.

Long health/sleep ranges are read in one-year chunks to avoid oversized API responses. Sleep prefers `/sleep/details` and falls back to `/sleep`. The settings page shows the oldest/newest locally stored dates per major domain.

Imported raw records and materialized activity rows remain in PenguCoach after disconnecting the SparkyFitness account. The connection page also offers **Delete all SparkyFitness data**. This deletes only PenguCoach's local SparkyFitness imports/provenance, preserves Garmin/manual values where provenance is known, never writes to the remote SparkyFitness instance, and keeps the connection configured so a clean re-sync can be started immediately.

### Workout telemetry note

SparkyFitness v1.7.x can store wearable workout telemetry (heart rate, GPS, cadence, power and elevation), but these values are optional upstream. PenguCoach can only import fields that SparkyFitness actually exposes for the workout. If the SparkyFitness exercise detail itself contains no HR/elevation telemetry, PenguCoach deliberately leaves the values empty instead of estimating them.


## Body and smart-scale data

PenguCoach reads body/check-in values when SparkyFitness exposes them, including weight, height, BMI, body-fat percentage, body-water percentage, muscle mass and bone mass. These connected-source values remain read-only and keep per-metric provenance so Garmin values are not silently overwritten.

Users without a smart scale can enter the same body/profile values manually on the Health page. Manual values are stored locally in PenguCoach and remain the current fallback for each metric until a newer Garmin or SparkyFitness measurement for that metric becomes available. They are included in Coach/training context with `manual` provenance.


## Automatic incremental sync (alpha.33)

The connection can run a Garmin-style small automatic sync every 15 minutes to 24 hours. Automatic runs deliberately request only today and yesterday so late Apple Health / HealthKit writes (for example heart-rate telemetry arriving after the workout row) are picked up without re-reading the configured history range. The manual **Sync now** action continues to honour `sync_days`, including multi-year/all-data backfills.

Workout provider telemetry is normalized from SparkyFitness' relational/provider payloads. In addition to average/max heart rate and ascent, PenguCoach reads `avg_speed_mps`, `max_speed_mps`, `elevation_gain_meters`, `elevation_loss_meters`, `min_elevation_meters`, `max_elevation_meters`, cadence and power where SparkyFitness exposes them.
