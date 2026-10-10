# Training & Personal Progress — Alpha.50

## Goal review

Open an activity linked to a saved training-plan session. **Plan meets workout**
shows recorded below/in/above-target time and a compact step overview. Expand the
remaining steps when needed. Step buttons jump to the corresponding chart position.
The next-workout Coach link includes the visible review as explicit prompt evidence.
It does not launch an AI request by itself or edit the training plan.

Confirmed assignments take precedence. Otherwise the existing duration-aware,
one-to-one matching is used across the five most recently updated saved plans.
Ambiguous plans require a choice. An unlinked activity points back to Training.

- Full FIT/GPX/TCX parquet recordings are read for the assessment, independently
  of the chart's sample reduction. Recorded elapsed time is required.
- Nested repeat groups expand in plan order, with a 1,000-step safety bound.
- Timed boundaries use elapsed recording time; distance steps use monotonic
  recorded distance. An unresolved distance boundary or one inside a gap over 30 seconds stops further alignment.
- Only matching sport-specific or default imported Garmin zones are used. The
  current zone snapshot date is shown; this is not a reconstruction of old zones.
- Readings are held until the next sample and weighted by real seconds. Gaps
  over 30 seconds and explicit track-segment changes are not counted as observed.
  Zero watts are valid; missing HR/power is not zero.
- An assessed step requires at least 70% sensor coverage. An overall percentage
  requires at least 70% coverage of resolved target-step time. Any unassessed step
  keeps the overall result partial. 70% in-range marks a target as met; otherwise
  above/below or a mixed result is shown. These are transparent product rules,
  not physiological thresholds.
- Alignment initially assumes the first recording sample is the plan start.
  **Matching & calculation** can shift that start by 0–7,200 seconds. It is not
  automatic lap detection; elapsed-time pauses can shift planned-step alignment.

## Route comparison and replay

Under the analysis range, **Start comparison** checks the whole route or the
selected section, including a climb. The range uses the chart's actual time,
distance or explicitly labelled point axis. Results clear when the range changes.

The candidate search reads up to 100 recent user-owned parsed recordings from
365 days, filters to the same sport family (and comparable total distance for
whole routes), then checks up to 20 candidates. It is a bounded recent comparison,
not an exhaustive all-time search or exact map matching.

A match requires at least 12 GPS points, 80% GPS coverage, one explicit track
segment, endpoints within 100m, recorded distance within 12%, ordered progress,
and 95% of bidirectional shape samples within 80m. Reversed routes and differently
shaped routes are rejected. Selected sections locate ordered endpoints inside
each candidate. Repeated loops or complex intersections can cause conservative
false negatives. Distance without GPS never proves a route match.

Time is recorded elapsed time, including pauses. Means use recorded time with
70% channel coverage; unavailable columns disappear. Time delta means current
recording minus comparison. A lower-HR highlight needs at least 3 bpm difference
and mean speed within 5%. Weather, stops and daily condition still differ; the
highlight is an observation, not proof of a fitness gain.

Replay follows recorded time at 1/10/30/60/120×, with pause, restart, touch seeking,
step jumps and a jump to the steepest available grade point. Replay without real
time is disabled. The route and readings synchronize; street-level views retain
per-opening consent and settle at the paused position. Grade remains an estimate.

## Personal progress

Today shows 7/28/90 days of readiness and recorded training. Day selection works
with a keyboard/touch slider. History is recomputed from currently stored values
dated on or before each day, with historical baselines and feedback windows. It
is not a log of what the app knew at that time: later imports or edits can update
the past. Missing scores leave gaps. No recorded training is labelled as such,
without inferring a rest day or inventing a zero-minute measurement.

Personal patterns use a 90-day window. Sleep under 6h is compared with 7–9h:

- Mean reported check-in energy needs at least three days per cohort and an
  observed difference of at least 0.5 energy-scale points.
- The fraction of days with hard workout feedback needs at least three days
  per cohort and a difference of at least 20 percentage points. Multiple
  workouts count as one day; a day is hard if any recorded feedback is hard.

Both panels expose dates and sample sizes. These are exploratory associations;
training difficulty and other confounders are not controlled. They are not
automatically stored as permanent Coach memories or claimed to be causal.

Milestones recognize at least three recorded training days in each of the last
two complete ISO weeks, or a new longest endurance session in the 90-day window
recorded in the last seven days. The latter requires at least three earlier
same-sport workouts, a 20-minute session and 10% longer duration. It is not an
all-time record, an intensity target or a request to keep increasing duration.

## API and update

- `GET /api/v1/activities/{id}/goal-review`: optional owned matched `plan_id`,
  `session_id`, and `offset_s`.
- `GET /api/v1/activities/{id}/route-comparison`: `start`/`end` percentages and
  `axis=time|distance|points`.
- `GET /api/v1/coach/progress?days=7..90`.

All reads use the authenticated user scope, including fit files, plans, health,
check-ins and feedback. Cross-user activities return 404. No schema migration,
provider key, external telemetry request or AI call is required for these features.
The existing map/panorama integrations keep their separate user settings.
