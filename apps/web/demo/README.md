# Demo data

Recorded API answers for the public demo (GitHub Pages, alpha.88). Everything here is
made up: the account "Pia", her health values, activities, plans, races and tours.
GPS tracks are synthetic loops placed in the Franconian Switzerland.

- `data/index.json` – maps an API path (with sorted query) to the bundle that holds it
  (`core.json` or `activities-N.json`, ten activities each – few files keep a GitHub web
  upload small).
  `recorded` is the day of the recording; the demo moves all dates by whole weeks so
  it always looks current.
- `data/activities.json` – activity ids that get a pre-rendered detail page.
- Entries starting with a method (`POST /tours/plan`) answer that request.

`npm run build:demo` copies this folder to `public/demo-data` for the build only.
