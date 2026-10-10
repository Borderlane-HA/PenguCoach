# Local training companion — Alpha.51

All five additions extend existing PenguCoach workflows. No additional API key,
AI request, database table or migration is required. Existing optional map tiles
and panorama providers keep their settings and confirmation flow.

## Available time today

A saved upcoming workout already supports reviewed short variants. Today now
opens that preview directly when available time is shorter, at least five
minutes, and no current recovery warning takes priority. The existing calendar
and rolling-week review remain accessible for recovery or schedule adaptations.
The preview shows the original and proposed duration, complete workout steps,
and the reduction rules. It only saves after `Apply short variant`.

The deterministic shortening preserves warmup/cooldown, interval duration and
recovery, removes entire repetitions, and reduces continuous work where possible.
Strength variants reduce sets while preserving reps and rest; duration remains an
estimate. Distance steps require manual conversion to timed steps. A budget that
cannot accommodate the essential steps produces an explanation rather than an
invented workout. Schedule revisions, completed sessions and Garmin export locks
remain enforced by the existing short-variant API.

## Confirmed training experiences

In an activity's feedback section, users can write and explicitly save one
experience. Applicability is selected: all sessions of this sport, intervals,
continuous endurance or strength. It is stored under `ActivityFeedback.data.experience`.
No preference is inferred or permanently saved automatically.

The Coach profile lists all experiences with edit, pause and delete controls.
Matching uses the sport family and selected type. The existing deterministic
intensive-session classification uses structured zones and workout wording;
this is a coarse matching rule, not a physiological assessment or a claim about
work/commuting circumstances. Up to three recent matching hints are displayed.
Up to 30 enabled experiences enter personal coaching context. Disabling the
personal profile also disables experience hints and AI use. Paused experiences
are excluded. There is a maximum of 50 saved experiences per user.

Ordinary feedback edits preserve experiences and route notes. Deleting ordinary
feedback preserves those independent fields. Deleting an experience preserves
feedback. Clearing the complete Coach profile/memory clears experiences as well,
but preserves activity feedback and route notes. Deleting the activity removes
its feedback, experience and notes through the existing activity lifecycle.

## Recorded best efforts

Activity details provide 1-, 5- and 20-minute power and speed averages on demand.
Running speed is displayed as pace. Activity lists offer a separate sport-specific
comparison across the latest **50 parsed recordings in the past 365 days**. This
is a bounded recorded-data comparison, not an all-time record or fitness score.
The comparison displays the number of recordings checked and unreadable files.

The full stored recording is read, not the chart's downsampled representation.
A left-sample-held, time-weighted integral finds complete windows, including
candidate edges between samples. Actual elapsed time, zero watts and recorded
pauses count. Missing values, invalid/negative readings, recording gaps over
30 seconds and track-segment changes break valid windows. Missing/non-monotonic
timestamps do not create synthetic time. Entire windows must have valid sensor
intervals. Speed varies with terrain and conditions and is not evidence of an
improved fitness state. Each result links to its activity and exact chart start.

## Calendar draft load check

Moving/editing a session triggers a debounced, read-only check of the **current
draft**, including saved other PenguCoach plans and Garmin export dates.
The calendar shows conflicts before saving. It checks intensive days back to
back, saved training weekdays, unusually long sessions, multiple-session volume,
and other plans on the same date. An easy session on a hard day no longer hides
an adjacent intensive day. Intensive days in other saved plans are included.

Up to three nearby alternative dates are offered. They must be free, within
plan bounds, today or later, on an allowed weekday, and must not create adjacent
intensive days. They are suggestions, not an optimization of fitness or recovery.
If none fits, the user can edit manually. Selecting an alternative changes only
the draft. Saving rechecks the exact submitted draft. When warnings remain, a
review dialog offers continued editing or explicit saving with those warnings.
Garmin export locks are hard guards and cannot be bypassed by that dialog.
A failed check does not report a successful check or save an unchecked calendar.

## Route briefing and personal notes

The existing route explorer offers a collapsed briefing for a recorded route.
It uses the same 5,000-point representation as the chart, for synchronized jumps.
Recorded elevation and distance are grouped into roughly 100m bins. Continuous
uphill bins of at least 3% grade, totaling 300m and 15m gain, are shown (up to
8 climbs with the largest gain, then sorted by route order). Invalid coordinates,
missing measurements, distance resets, segment changes and obvious large jumps
interrupt detection. Elevation is noisy: this is an approximate descriptive
briefing, not a route survey or intensity prescription. Only sufficiently covered
recorded average HR, power and speed are displayed for a climb.

Users can attach, edit and delete up to 40 notes of 300 characters to actual GPS
points of that recording. Coordinates are resolved on the server, not accepted
from the browser. Notes are stored under `ActivityFeedback.data.route_notes` and
rendered as text (including map tooltips), never HTML. They remain attached to the
source activity, rather than being silently transferred to vaguely similar routes.

A matching saved workout in the next 30 days can be previewed along the route.
Up to five recent saved schedules are examined; already completed sessions are
excluded using the existing plan/activity matching. Timed steps and repeats map onto
the **same elapsed-time progression as the old recording**. This is explicitly
labelled as orientation: it predicts no future pace and changes no plan. Missing
times, distance steps and missing structured steps have explicit empty states.
Steps after the recorded endpoint cannot be placed. Chart, map and elevation
profile provide the surrounding terrain; selecting a climb, note or plan step
moves the shared cursor. Notes/climb/work markers appear on the map while the
briefing is open.

## APIs and ownership

- `GET /coach/experiences`
- `PUT /coach/experiences/{activity_id}`: text, kind, enabled
- `DELETE /coach/experiences/{activity_id}`
- `GET /activities/{activity_id}/best-efforts`
- `GET /coach/best-efforts?sport=running`
- `POST /coach/plans/{run_id}/schedule-check`: start_date, overrides, revision
- `GET /activities/{activity_id}/route-briefing?plan_id=…&session_id=…`
- `PUT /activities/{activity_id}/route-notes`: text, point_index, optional note id
- `DELETE /activities/{activity_id}/route-notes/{note_id}`

All endpoints require a signed-in, safety-confirmed user. Activity and plan
ownership is checked, all comparison rows are user-scoped, and explicit plan
selection must match the user's upcoming list. Read-only previews write nothing.
Existing databases work without migrations because additions use existing JSON
fields. Notes and experiences remain user-owned and removable through the
activity or Coach profile controls described above.

## Recorded fast passages (Alpha.52)

Route preparation also detects sustained faster sections, using recorded speed,
GPS, distance and elapsed time independently of elevation. A qualifying interval
has valid coordinates, non-decreasing distance (at most 250m between points),
speed between 0 and 200 km/h, matching track segments and a positive time gap no
larger than 30 seconds. Missing or invalid readings interrupt continuity.

The threshold is the greater of the duration-weighted 75th speed percentile and
115% of duration-weighted moving speed. Stops are excluded from this baseline;
no speed is inferred from distance or missing timestamps. At least 60 seconds
of moving readings are needed. Passages must last 30 seconds and span 150m.
Up to eight longest passages are displayed in route order. Segment average
speed is time weighted; optional HR/power use the existing 70% coverage rule.

Cards, speed-profile bands, elevation-profile bands and purple route-map sections
link to the shared chart cursor. The speed view is available without elevation;
without usable speed it is hidden. These are historical descriptions, not future
targets or judgements about a safe place to ride or run fast.
