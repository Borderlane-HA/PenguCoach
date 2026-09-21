# Architecture

PenguCoach follows a local-first facts-before-AI architecture:

```text
Garmin/FIT -> raw source -> normalized facts -> deterministic analytics -> context -> AI interpretation -> user decision
```

Garmin is strict read-only. AI providers never receive Garmin credentials or tokens. Cloud AI data is filtered by explicit user/system privacy policy in later phases.
