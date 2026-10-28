# Training Intelligence v1

Alpha.44 adds deterministic training intelligence without turning the Training page into a second dashboard.

## Load & trends

PenguCoach compares the last 7 days with a 28-day weekly baseline. When at least half of the activities in the 28-day window expose Garmin `training_load`, that metric is used. Otherwise the calculation falls back to training minutes and labels that basis explicitly. The result is a planning trend, not a medical readiness score.

## Weather on planned sessions

Near-term outdoor sessions can show Open-Meteo temperature, rain and wind context. Unfavorable conditions may offer an Indoor Alternative. The user reviews the before/after session and must confirm before anything is saved. Forecast outages never block the plan calendar.

## Plan conflicts

V1 can flag deterministic conflicts including:

- sessions outside saved training days;
- sessions substantially longer than the user's typical duration;
- unusually high-volume double-session days;
- hard sessions on consecutive days;
- another session from a different PenguCoach plan already exported to Garmin on the same date.

These are advisory. No schedule is mutated automatically.

## AI Decision Log

Accepted adaptive changes persist a before/after snapshot plus structured reasons. This keeps adaptive coaching explainable and makes later review possible without reconstructing a model prompt.

## Memory suggestions

PenguCoach may propose a memory after repeated explicit evidence, such as repeatedly confirmed weather-based Indoor Alternatives or repeated very-hard workout feedback. Suggestions are never stored automatically. The user can accept or dismiss them.
