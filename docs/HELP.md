# In-app help (alpha.82)

The help page (`/help`, sidebar → Help) is built from `apps/web/lib/help.ts`.
Each section has an `id` (used as anchor, e.g. `/help#garmin`), a German and an English title and intro,
question/answer topics and links to the matching settings. Admin-only sections and links carry `admin: true`.

## Keep it current with every release

When a release adds or changes a feature, a setting or a page:

1. Add or update the topic in `apps/web/lib/help.ts` – both languages.
2. Add a link to the place where it is set, if there is one.
3. Run `node --test apps/web/tests/todayLayout.test.cjs`: it checks that every text exists in both languages,
   that section ids are unique and that admin sections stay hidden for users.

Other pages can link to a section directly, for example the Today settings panel links to `/help#today`.
