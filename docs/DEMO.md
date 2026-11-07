# Live demo — Alpha.88

**https://borderlane-ha.github.io/PenguCoach/**

The demo is the real PenguCoach interface, built as static pages and published with
GitHub Pages. There is no server behind it: every API call is answered in the browser
from recorded, made-up data (`apps/web/demo/data`). The demo account "Pia" runs,
rides and hikes in the Franconian Switzerland; her health values, plans, races and
tours are invented.

## What works

- Every page: Today, Health (all periods and the recap), Activities with charts, the
  2D/3D route map and flyover, Training, Calendar, AI Coach (an example conversation),
  Tours (example suggestions, elevation profile, 3D, GPX download), Help and settings.
- Themes and language can be switched; the choice is kept for the browser tab.
- Dates move along with the calendar (in whole weeks), so the demo always looks current.

## What does not

Saving, syncing with Garmin or SparkyFitness, new AI answers, uploading files and
calculating new tours need a real installation. The demo then says so instead of
pretending it worked. Activities beyond the first page of the journal have no detail
page.

## How it is built and published

1. `.github/workflows/demo-pages.yml` runs on every push to `main` that touches
   `apps/web` (and can be started by hand under *Actions*).
2. `npm run build:demo` (`apps/web/scripts/build-demo.mjs`) builds with
   `NEXT_PUBLIC_DEMO=1` and the base path `/<repository name>` as a static export into
   `apps/web/out`, with the demo data copied into it.
3. The workflow uploads `out/` and deploys it to GitHub Pages.

One-time setup in the repository: **Settings → Pages → Source: GitHub Actions**.

Normal installations are not affected: without `NEXT_PUBLIC_DEMO` none of this is
active and no demo data is shipped with the app.

## Updating the demo data

The data was recorded from a demo database by opening every page and saving the API
answers. Names are replaced, GPS tracks are moved, long activity series are thinned
and example tours are generated from demo rides. A test (`tests/demo.test.cjs`)
checks that the data is complete and contains no personal values.
