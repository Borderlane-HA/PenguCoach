# PenguCoach alpha.9 · Garmin full history and VO₂ max

## Garmin history

The history selector now supports **All available data** (`historical_days = 0`).

Garmin does not expose one universal "first wellness date" for every domain. PenguCoach therefore determines a safe account-specific starting boundary from the **oldest Garmin activity** using the activity count and oldest activity page. From that date forward the normal read-only daily sync pipeline imports health, recovery, training and activity data.

This avoids probing many years of empty dates blindly. Very long backfills are deliberately paced and can take a substantial amount of time.

## VO₂ max

Garmin activity summaries can contain `vO2MaxValue`. PenguCoach now normalizes that official Garmin value on each activity and classifies the series by sport:

- Running
- Cycling / biking

Existing rows are backfilled from the already retained raw Garmin activity summary during the alpha.9 database migration. Missing values remain `NULL`; PenguCoach does not estimate VO₂ max.

The Health page renders Running and Cycling together over the complete imported history. The Today page shows both latest values in one compact VO₂ max card.
