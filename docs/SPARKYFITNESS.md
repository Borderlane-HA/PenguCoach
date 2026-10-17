# SparkyFitness integration

## GPS, sensor series and laps (alpha.64, SparkyFitness 1.8.0)

SparkyFitness stores GPS/sensor samples, laps and HR-zone times separately from `ExerciseSession_raw_data`. A raw HealthKit summary with only start/end/duration/distance/calories does not contain that recording. PenguCoach now reads the same separate endpoints as Sparky's editor:

- `GET /api/generic-health/workout-gps/{exerciseEntryId}` → `{data: {points: [...]}}` or `{data: null}`.
- `GET /api/generic-health/workout-laps/{exerciseEntryId}` → `{data: [...]}`.
- `GET /api/generic-health/workout-hr-zones/{exerciseEntryId}` → `{data: [...]}`.

Verified source contracts: [SparkyFitness v1.8.0 frontend service](https://github.com/CodeWithCJ/SparkyFitness/blob/v1.8.0/SparkyFitnessFrontend/src/api/Health/genericHealthService.ts), [server routes](https://github.com/CodeWithCJ/SparkyFitness/blob/v1.8.0/SparkyFitnessServer/routes/genericHealthRoutes.ts), [GPS schema](https://github.com/CodeWithCJ/SparkyFitness/blob/v1.8.0/shared/src/schemas/database/ExerciseEntryGpsPoints.zod.ts) and [HR-zone schema](https://github.com/CodeWithCJ/SparkyFitness/blob/v1.8.0/shared/src/schemas/database/ExerciseEntryHrZones.zod.ts).

The API key also needs check-in/health read access for these endpoints (the upstream router uses `checkin_read`). A denied/unsupported optional endpoint does not fail the whole sync; denied access is shown in the activity detail. Previously imported telemetry is preserved on a failed fetch. Empty successful responses clear removed upstream data. Optional endpoints are skipped for the remainder of a sync if unavailable or denied.

After updating API, web and workers together, select the desired history range (or **All data**), save and run **Sync now**. Existing IDs, feedback and plan assignments remain intact. Manual sync refreshes telemetry throughout that range; automatic sync stays restricted to today/yesterday. No deletion or new migration is required. A large first historical import makes additional read requests, reflected in sync progress.

Available timestamped points feed the existing OpenStreetMap/chart view, measured HR minimum, altitude/speed/power/cadence channels, per-activity efforts, route briefing and plan execution review. Recorded laps and HR-zone times remain separate from locally computed distance splits. Invalid timestamps/coordinates/values remain missing; gaps are not connected as one track. FIT recordings retain priority for merged activities. Summary-only entries never become fabricated curves or routes. There is a 100,000-point per-workout import bound; absent provider samples and unsupported optional endpoints remain empty. No live Sparky credentials or paid AI calls were used during development.

# SparkyFitness connection

## Recording time and additional readings (alpha.63)

Sparky may return a day in `entry_date`, a separate local clock in `entry_time` and an IANA `record_timezone`. PenguCoach combines these into a UTC recording instant and displays it in the browser's local timezone. If no recording zone is supplied, it uses the PenguCoach user's configured timezone. Original provider timestamps (`raw_data.startTime`, including JSON-string/wrapped raw payloads) take precedence. The recorded date determines the summer/winter offset.

A bare day or relational UTC-midnight placeholder is not treated as a proven recording time. Such activities show **Uhrzeit unbekannt / Time unknown**. Native Garmin midnight timestamps and explicit original-provider midnight recordings remain valid. Invalid timezone names, malformed local clocks, DST gaps and repeated local hours without an explicit offset remain date-only. Only recordings with a known time qualify for the automatic ±4-hour plan match; manual assignment and conservative untimed same-day matching remain available. The AI receives the same precision instead of an invented clock time.

On the next activity sync, old standalone Sparky rows without the new parser marker are repaired from their saved payloads. Their IDs, feedback and plan assignments remain. Garmin recording timestamps are never rewritten from Sparky. If older saved payloads lack the true clock or additional readings, choose **Alle Daten / All data**, save the connection settings and run **Jetzt synchronisieren / Sync now** to fetch available historical details. Deleting activities is unnecessary. The automatic incremental sync still fetches only today and yesterday; the local historical timestamp repair is independent of that fetch window.

Minimum HR accepts supported direct aliases, named heart-rate statistics and nested/JSON-string raw data, including numeric strings. Boolean, empty, non-finite and impossible minimum-HR values are not measurements. Additional supported stride, ground-contact, vertical-ratio/oscillation, swimming and temperature readings are shown in a collapsed section only when available. Oscillation supplied in millimetres is explicitly converted to centimetres. Garmin remains the first source for merged readings. The parser does not infer a minimum from an average, arbitrary unrelated minimum fields or incomplete chart samples.

Missing training load, aerobic effect, HR, movement time and coverage remain unknown rather than becoming zero. Real reported zeros remain visible. A session's duration is not silently duplicated as movement time. Additional fields must actually be returned by the permitted Sparky API; a value visible in Sparky's own charts is not necessarily exposed in the summary endpoint. No FIT time series or interval adherence is fabricated from averages.

There is no new migration or dependency. Rebuild/restart API, web and workers together, then synchronize Sparky. Automated validation uses recorded-shape fixtures, real temporary databases, simulated endpoints and browser checks; it does not access the user's live Sparky installation.

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

SparkyFitness can be the only source or be combined with Garmin. It refreshes general health data such as steps, sleep, body measurements and HRV/resting heart rate where available. Corrections from the same source are applied. Dated observations are compared per metric; undated overlapping daily totals use a stable Garmin tie-break and are never added together. Body snapshots select the newest dated measurement per metric across all sources. Workout sessions are also materialized into the normal activity diary when they contain enough session-level information. HealthKit `Active Calories`/Move-ring entries are explicitly treated as daily health metrics: they may fill the day's active-calorie value when Garmin has not already supplied it, but they are never materialized as workouts.

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

## Water intake

Daily health sync also reads `/measurements/water-intake-range/{startDate}/{endDate}` in bounded range chunks. The documented `entry_date` and `water_ml` fields are normalized to milliliters. On 404/405, older servers use `/measurements/water-intake/{date}` for up to the last 28 days of the requested range. Automatic sync still covers only today and yesterday. The stored sync summary reports the actual range/mode or an unavailable/permission reason. No water goal is inferred if the provider did not supply one.

API shapes were checked against the upstream [measurement routes](https://github.com/CodeWithCJ/SparkyFitness/blob/main/SparkyFitnessServer/routes/measurementRoutes.ts) and [measurement service](https://github.com/CodeWithCJ/SparkyFitness/blob/main/SparkyFitnessServer/services/measurementService.ts). Optional endpoints remain capability/error tolerant because deployed SparkyFitness versions differ.
