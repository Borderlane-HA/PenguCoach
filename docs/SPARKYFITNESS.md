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

SparkyFitness fills missing general health data such as steps, sleep, body measurements, HRV/resting heart rate where available, and adds workout sessions as a secondary AI context source. Existing Garmin canonical values are not overwritten.

Because SparkyFitness can itself contain Garmin-synced data, AI context marks SparkyFitness as a secondary source and explicitly warns against double-counting sessions that appear to be the same workout.

## Sync

The SparkyFitness settings page offers a configurable 7–366 day sync window and independent toggles for:

- training & activities;
- sleep;
- daily health, HRV and body data.

Imported raw records remain in PenguCoach after disconnecting the SparkyFitness account.
