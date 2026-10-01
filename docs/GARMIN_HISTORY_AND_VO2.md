# Garmin History Import and VO₂ max

## Historical import

The history selector supports fixed periods from 30 days through 10 years plus **All available data** (`historical_days = 0`).

Activities are catalogued first. Daily wellness/recovery data is then backfilled separately, so a slow wellness import cannot leave gaps in the activity list.

Two import modes are available:

- **Optimized (recommended):** the latest 90 days use full detail. Older days request a smaller core set of daily summary, sleep, HRV, stress, Body Battery, max metrics/VO₂ and body data.
- **Full:** every enabled Garmin domain is requested for each historical day.

Completed days are marked in the local database and are skipped on the next run. This makes pause, cancellation, updates and restarts resume-safe.

### Pause, cancel and stuck requests

**Pause** is cooperative and takes effect at the next safe checkpoint. **Stop now** hard-revokes the exact Celery history task and clears the stale per-account Redis lock, while preserving already imported data.

Each individual Garmin domain call also has a finite request timeout. If Garmin fails to return a domain request within the timeout, PenguCoach stops the history run as resume-safe instead of leaving the job frozen indefinitely. Restarting the import skips completed days.

## VO₂ max

Garmin activity summaries can contain `vO2MaxValue`. PenguCoach normalizes that official Garmin value on each activity and classifies the series by sport, including Running and Cycling/Biking where Garmin exposes the value.

Missing values remain `NULL`; PenguCoach does not estimate VO₂ max. Historical charts use the imported Garmin values together with the selected Health time range.
