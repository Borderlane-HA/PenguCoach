# Steps, appearance and faster navigation (Alpha.68)

## Personal step targets

Use the small arrow in the **Steps** card on Today or Health to set a daily target
between 1,000 and 50,000 steps. A target is not activated until it is saved. The
editor's initial 8,000 is an editable starting value, not a prescribed target.
The setting belongs to the signed-in user and works with Garmin or SparkyFitness.

Today shows recorded steps, the target, percentage and remaining steps. Percentages
can exceed 100%; the visual bar ends at 100%. Missing readings have no percentage.

Health keeps the selected period's average as the main reading. Its progress is
the sum of recorded steps divided by the sum of daily targets for those recorded
days. Zero steps count as a recorded day; missing days do not. The card shows
recorded days versus the requested period and days reaching their target. For
**All**, it reports the recorded-day count without inventing a calendar boundary.
Target changes apply from the user's local today. Earlier saved daily targets are
preserved. Days before the first saved target use that first target as an explicit
comparison reference; the editor explains this when such days are present.

**Personal target suggestions** is optional and local; it does not call an LLM.
It evaluates the last 14 completed local days, needs at least 10 recorded days and
waits at least seven days after a target change. Consistently reaching the target
can produce a modest increase; consistently missing it can produce a reduction.
Suggestions never change the target automatically. Selecting a suggestion fills
the editor; **Save step target** is still required. Disabling suggestions keeps
the manually chosen target.

## Custom theme

Open **Settings → Appearance → Custom Theme**. Select light or dark mode and an
accent, page background and card color. The preview uses sample values. Brightness,
text colors, muted labels, controls and chart colors are derived to maintain
contrast; unsuitable combinations are adjusted. Save to activate the theme.

The custom palette is saved per account and retained when selecting another
theme. Theme colors are restored before the first paint, including on reload.
Only appearance settings are cached in browser storage, not the dashboard's health
readings. Avatar and app-icon settings remain independent.

## Navigation and loading

Internal page links use client navigation without replacing the entire document.
The authenticated shell and appearance remain available. Dashboard requests share
an in-memory cache scoped to the user and local date. A quick return shows existing
readings immediately; stale entries refresh in the background. Writes invalidate
cached data. Health period requests have distinct keys, so an older response cannot
replace the newly selected period. Errors preserve known readings and show retry
controls. Sign-out, account changes and local day changes clear/isolate the cache.

Today fetches basic readings without a 180-day VO₂max calculation. That history is
requested only when VO₂max is selected. Its resting-HR trend uses a small dedicated
endpoint. Hidden optional sections avoid their data requests; progress and weather
sections mount near the viewport. Health readings and its more extensive development
charts load independently. Browser timings are not a benchmark of a user's LXC,
database or network.

## Release notification

The installed version links to the repository's releases. A newer published release
adds **Update available** with a direct release link; the collapsed sidebar keeps an
arrow and the mobile navigation menu includes the notice. Versions are compared
numerically, including alpha patch components. Alpha installations include published
prereleases; stable installations ignore prereleases. Drafts and unrecognized tags
are skipped.

The backend checks the fixed public GitHub repository anonymously, caches successful
checks for six hours and uses ETags when supplied. Failures retry later and do not
block dashboard data. The check sends no health data or account credentials. It
does not install updates automatically.

Since Alpha.69, the refresh symbol beside the installed version and **Settings →
About → Check now** can bypass the six-hour cache. The authenticated check shares
a one-minute cooldown across accounts on the API process, including automatic
requests; clicks during that minute reuse the result. Concurrent checks are
serialized, keep ETags and retain known release information if GitHub is unavailable.
The UI then says that the check could not complete instead of claiming the installed
version is current. The last successful check time is shown separately. Automatic
checks are demand-driven while using the app, not an independent server cron job.

For an update to appear, publish a GitHub **Release** with a comparable version tag,
for example `v0.1.0-alpha.69`; updating repository files or creating a draft alone
does not make a newer release available. Alpha users also see published prereleases.

## Daily readiness appearance

Alpha.69 replaces the three large lamps and circular dial with one status symbol,
a score badge and a slim segmented scale. The scale visualizes the numeric score;
the recommendation and status still use the existing readiness rules, including
recovery overrides. Missing, failed and loading assessments have no invented score.
Evidence and the guided daily assistants remain in their existing places.

No database migration or new runtime dependency is needed. Update the API and web
application together; deploy the matching release to workers as usual.


### Changelog in About

Settings → About includes a collapsed Changelog panel sourced from the public
repository's `main/CHANGELOG.md`. It loads only when opened. The newest entry
is expanded, the installed version is marked when present, and older entries
are revealed six at a time. Repository notes can describe changes newer than
the installed app. The original language and wording are retained.

The authenticated `/settings/changelog` endpoint fetches a fixed public URL
anonymously. It shares a six-hour per-process cache, uses ETags, and allows a
manual refresh at most once a minute. The complete fetch is limited to six
seconds and 1 MiB. A failed refresh retains the last successful notes and
timestamp with a visible stale notice; the direct GitHub link remains available.
No AI request, provider key, new dependency or migration is required.
