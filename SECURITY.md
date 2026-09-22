# Security Policy

PenguCoach processes health, activity, location and authentication data. Security-sensitive reports should not be filed with real Garmin tokens, passwords, FIT files, GPS traces, medical information or LLM API keys attached.

## Security design

- Garmin data synchronization is allow-list/read-only. The optional workout/calendar exporter is a separate, default-off narrow gateway limited to explicit workout upload/schedule/cleanup actions and is never exposed generically to AI code.
- Garmin passwords are not stored.
- Garmin tokens and LLM API keys are encrypted at rest.
- Browser authentication uses HttpOnly cookies.
- The safety notice is required after every new application login.
- Cloud AI processing of user health/training context is disabled until the user opts in.
- Local-only AI mode must not silently fall back to cloud providers.
- Normal logs should contain identifiers/status codes, not health payloads or secrets.

## Development status

PenguCoach is under active development. It is not a medical device and should not be used as the sole basis for medical, nutrition or training decisions.
