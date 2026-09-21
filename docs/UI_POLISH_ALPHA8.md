# PenguCoach UI polish — 0.1.0-alpha.8

Alpha.8 is a focused usability polish release on top of the alpha.7 health design.

## Branding

- A built-in PenguCoach SVG app icon is now the default brand mark instead of the plain `P` placeholder.
- The same mark is registered as the browser favicon.
- Per-user custom app icon uploads remain supported and override the sidebar mark after login.

## Coach and training planning

The Coach and Training Planning pages now use a single balanced header frame. The active-model panel is aligned to the same visual frame as the content below, stretches to the heading height, and no longer floats loosely in the top-right corner.

## Garmin synchronization

The manual Synchronize action now follows the real Celery job rather than only the HTTP enqueue request.

- The button remains disabled while the worker is running.
- The progress notice exists only while the job is active.
- The task id is stored in browser local storage so a page reload can resume status polling.
- When the job finishes, Garmin status is refreshed automatically, including the last/next sync timestamps.
- The success notice disappears automatically.

The automatic-sync controls are split into two clear panels: Schedule and Activity data. This also fixes the previous toggle text/grid overlap.

## AI Studio wording and actions

The former `routes set` KPI is now shown as `fixed models`. It counts how many of the three AI tasks have an explicitly selected primary model. Tasks without a fixed model continue to use the first eligible active model automatically.

Provider and model management actions no longer stretch across the row. Delete actions are compact, readable and explicitly labelled.

## Deployment updates

The updater continues to treat `/opt/pengucoach` as a deployment checkout. After creating a backup it aligns the source with `origin/<channel>` without an overwrite confirmation or local-source-change abort. Runtime data under `/var/lib/pengucoach` and configuration under `/etc/pengucoach` remain outside the Git checkout.
