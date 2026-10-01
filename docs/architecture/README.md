# Architecture

PenguCoach follows a local-first facts-before-AI architecture:

```text
Garmin/FIT -> raw source -> normalized facts -> deterministic analytics -> context -> AI interpretation -> user decision
```

Garmin data synchronization is strict read-only. Alpha.14 adds a separate default-off workout/calendar write gateway that is invoked only after an explicit user export request and is not exposed to the AI layer. AI providers never receive Garmin credentials or tokens. Cloud AI data is filtered by explicit user/system privacy policy in later phases.
