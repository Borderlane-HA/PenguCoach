# PenguCoach UI & Personalization — 0.1.0-alpha.7

Alpha.7 extends the bright health-first UI with user-selectable appearance profiles and simpler integration management.

## Themes

Each user can choose one of five themes under **Settings → Appearance**:

- Mint Light — the default bright health theme
- Midnight Health — dark mode
- Ocean — cool blue/aqua accents
- Forest — natural green accents
- Lavender — soft violet accents

The theme is stored in `user_preferences.theme` and applied per account. Existing `system` values from early alphas are normalized to Mint Light.

## Personal imagery

Users can upload:

- a profile picture shown in the sidebar and top-right user corner
- a custom PenguCoach app icon shown in the sidebar brand mark

PNG, JPEG and WebP are accepted up to 3 MB. Assets are stored below `/var/lib/pengucoach/user-assets/<user-id>/` and are therefore included in the normal PenguCoach data backup.

## Dashboard illustration

The Today dashboard includes a lightweight local SVG wellness/training illustration (`apps/web/public/dashboard-wellness.svg`). It has no external network dependency and remains available in offline/self-hosted deployments.

## Garmin UX

The normal everyday action is now a single **Synchronize** button. Historical backfill is intentionally moved into a separate expandable **History & initial setup** section to make clear that it is not part of routine synchronization.

## AI Studio

AI Studio now supports editing and deleting stored models. Provider model discovery is available for saved providers. Anthropic uses the current Models API so model identifiers, display names, input context size and maximum output tokens can be imported instead of maintained manually.
