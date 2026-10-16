# Training workspace (Alpha.59)

Training opens with **My week**, **My goal** and **Progress**. The existing navigation does not gain extra top-level entries.

## My week

The week is a seven-column calendar on desktop and an accessible day list on mobile. Each workout shows its name, duration and recorded matching state. Completed requires a matched activity; missing imports remain pending. Multiple workouts on the same day remain separately selectable. A workout opens a native dialog containing its structured steps, notes and links to the activity and full plan.

The page uses the selected saved plan. Plan management and technical plan details stay collapsed. Existing plan generation, job restoration, editing, activity assignment and Garmin export remain available. A generated plan without a saved calendar appears as a preview; activating it explicitly reviews its start date and scheduling conflicts before saving.

## Week adjustments and What if

The guided assistant offers availability changes for the next seven days, keeping a day free, and shorter versions of upcoming workouts. It shows a before/after preview and explanations before the user applies it. Availability changes may override the profile's usual training days for this proposal; the stored profile is preserved. The existing backend rules preserve completed and exported workouts, bound the plan dates, avoid increasing total training time and require review again if the plan or relevant comparison facts changed.

Unresolved sessions remain unchanged and explicitly marked for manual review. Keeping a day free is a redistribution request, not an automatic deletion of a workout. If no suitable slot or short variant exists, the assistant explains this instead of silently removing sessions.

## Goal journey

One measurable goal is stored per user in the existing coach profile JSON, without a database migration. A goal includes a title, sport, measurement, target, start and optional end date. Three measurement types are available:

- **Distance in one session:** the maximum recorded distance of a matching activity in the goal period.
- **Duration of one session:** the maximum recorded duration. This does not establish uninterrupted movement.
- **Number of sessions:** matching activities of at least five recorded minutes since the start date.

Future activities, other users, unmatched sports, non-finite values and missing measurements do not advance progress. Goals use the user's local calendar dates. Milestones are quarter-target thresholds (rounded up to whole sessions and deduplicated for count goals). Each reached milestone links to an actual activity. Missing measurements remain unknown. The UI does not claim a predicted fitness level or race outcome.

Goal edits use a three-step native dialog and a revision guard. Removing a goal preserves activities and the other coach profile fields. The general profile editor preserves the separately managed goal even if an older client does not send it.

## Progress

The Progress tab uses the existing recorded training/readiness history, personal patterns and bounded milestones. It loads only when opened. Readiness patterns remain associations, not causal findings.

## Accessibility and themes

The tabs support arrow keys, Home and End. Dialogs provide native focus containment, Escape and focus return; busy writes prevent accidental dismissal. Controls have explicit labels and use the current theme's foreground, panel and accent variables. The calendar does not depend on drag-and-drop; every workout has a keyboard-accessible control.
