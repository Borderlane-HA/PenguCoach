# Host steps

Numbered, idempotent shell scripts that the PenguCoach maintenance agent runs as
root after an update (after build and database migration, before services start).

* File name: `NNN-short-name.<scope>.sh` with scope `native`, `docker` or `all`.
* Steps run once per installation, in file-name order; the agent records applied
  steps in its private state (`host-steps.json`).
* Scripts are executed from the agent's root-owned release checkout, never from
  the application directory. Read files via `$PENGUCOACH_SOURCE`.
* A failing step aborts the update and restores code, database and data. Host
  changes made by a step are not undone, so every step must be safe to repeat and
  compatible with the previous release.
* If an older agent installed the release, the new agent runs pending steps once at
  startup.

Environment: `PENGUCOACH_DEPLOYMENT`, `PENGUCOACH_PROJECT`, `PENGUCOACH_SOURCE`,
`PENGUCOACH_DATA`, `PENGUCOACH_ENV_FILE`, `PENGUCOACH_MANAGED_ENV`,
`PENGUCOACH_SERVICE_USER` and, for Docker, `PENGUCOACH_COMPOSE`.
