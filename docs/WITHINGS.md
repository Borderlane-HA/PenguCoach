# Withings connection

PenguCoach `0.1.0-alpha.36` adds a read-only Withings connector for the official Withings Public API. It is designed for direct health/body measurements while Garmin and SparkyFitness remain the primary workout sources.

## What is imported

The first connector version imports:

- body/scale measurements: weight, height, body-fat percentage, fat-free mass (raw), muscle mass, bone mass and hydration/body-water when available
- daily activity: steps, distance and calorie totals
- sleep summaries
- raw measure groups such as blood pressure, pulse, SpO2 and other Withings measurement types are retained as source records so dedicated cards can be added later without losing the original data

Withings workouts are intentionally **not** materialized into the PenguCoach activity journal in this first version. This avoids duplicate workouts when the same recording already arrives through Garmin or Apple Health/SparkyFitness.

## Create the Withings OAuth application

1. Create/open an application in the Withings developer portal.
2. In PenguCoach open **Connections & Settings → Withings**.
3. Copy the **Redirect URI** shown by PenguCoach into the Withings application exactly.
4. Enter the Withings **Client ID** and **Client Secret** in PenguCoach.
5. Choose the desired history/sync settings and select **Connect with Withings**.
6. Approve the Withings authorization page. PenguCoach requests the read scopes required for user information, metrics and activity data.

The client secret, access token and refresh token are encrypted at rest. OAuth state is short-lived and validated on callback. Refresh-token rotation is handled automatically; when Withings returns a new refresh token, PenguCoach stores the new token instead of continuing to use the old one.

## Manual history and automatic sync

Manual sync uses the history range selected on the Withings settings page, including **All data**.

Automatic sync is configurable from **15 minutes to 24 hours**. To keep the recurring request small:

- body/measurements use Withings' incremental `lastupdate` cursor after the first successful sync
- daily activity and sleep refresh **today + yesterday**, which also catches values finalized after midnight

No inbound webhook or public PenguCoach URL is required for the initial connector.

## Source precedence

PenguCoach keeps provenance per metric instead of silently treating all sources as equal. For body/profile values:

1. the **newer measurement date** always wins
2. if multiple sources have a value on the same date, the priority is **Withings → Garmin → SparkyFitness → Manual**

This prevents a direct Withings scale measurement from being replaced by the same value after it has travelled indirectly through Apple Health/SparkyFitness. Garmin sync likewise preserves a same-day field already owned by Withings.

Daily/sleep records retain per-field source markers so connected sources can coexist on the same day.

## Delete local data / disconnect

**Delete all Withings data** removes Withings-imported data and provenance from PenguCoach only. It does not delete anything from the Withings account and keeps the connection available for a clean re-sync. If another connected source contains the same measurements, a later Garmin/SparkyFitness sync can populate those values again.

**Disconnect** removes the stored Withings credentials/connection. Imported local health records are kept unless they are deleted separately.

## Read-only scope

The connector does not write weight, blood pressure, workouts or other measurements back to Withings. It is a health-data ingestion source only.
