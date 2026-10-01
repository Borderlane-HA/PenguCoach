# Activity Detail v2

PenguCoach 0.1.0-alpha.3 prepares the deterministic analytics layer before deeper AI coaching.

## Goals

The activity page is intended to be useful without an LLM. Garmin metadata and the original FIT file remain the source of truth; PenguCoach derives display and training metrics locally.

## Interactive chart

Available FIT channels are detected dynamically. Depending on the device/activity, the chart can show:

- heart rate
- speed
- elevation
- power
- cadence
- grade
- temperature

Users can switch between an overlay view and synchronized stacked panels. Overlay lines use independent visual scales because the units differ; the shared pointer readout always shows the original units. The displayed activity range can be narrowed without changing the underlying data.

## Deterministic statistics

The API derives min/average/max values where meaningful, pace, normalized power (when power exists), elevation gain/loss, elevation range and a smoothed grade profile. Missing channels stay missing; PenguCoach does not invent power, heart-rate or cadence values.

Elevation and grade use light smoothing to suppress point-to-point GPS/barometric noise. The UI therefore labels the steepest grade as a training-view estimate from the smoothed series rather than a survey-grade measurement.

## Splits

Distance-based splits are generated from FIT records:

- running/cycling/other distance sports: 1 km
- swimming: 100 m

Each split can include elapsed time, pace, speed, average/max HR, average/max power, cadence, ascent/descent and average grade.

## FIT sport structures

Re-analysis now retains additional FIT message groups in the deterministic metric details:

- `lap` messages for device laps/intervals/auto-laps
- `set` messages for strength workouts when the device stores repetitions/weight/category
- `length` messages for pool swimming when the device stores lane-level data

Older activities parsed before alpha.3 need one FIT re-analysis if these lap/set/length tables are desired. The Parquet record series and existing activity metadata continue to work without a database migration.

## AI preparation

The new normalized statistics and split structures are deliberately deterministic. A future AI context layer should consume these prepared values rather than asking an LLM to calculate them from raw FIT samples.
