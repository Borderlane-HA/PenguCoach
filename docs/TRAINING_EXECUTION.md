# Training execution review and token continuation

Available from v0.1.0-alpha.61. Existing structured PenguCoach plans, including plans edited manually, can be reviewed retrospectively. This release does not connect to an external human-coaching service.

## Using the review

Open **Training → a workout in My week**. The session dialog contains two focused views:

- **Plan vs. Ist / Planned vs actual:** planned/recorded duration, work-step adherence, recording coverage and available FTP. Interval details and matching controls stay collapsed until needed.
- **Coach-Auswertung / Coach review:** select an eligible model and start the AI review. It receives the planned workout, recorded evidence, alignment, relevant activity context and your feedback. A separate next-session proposal can be reviewed and explicitly applied.

Use the activity's feedback form to record *too easy*, *about right* or *too hard*, optional RPE (1–10), discomfort and notes. Recorded target adherence and personal feedback describe different things; neither is silently substituted for the other.

## Matching

A session may have an optional local `start_time` (`HH:mm`). When present, eligible sport recordings within **±4 hours** can match automatically, including across midnight. Multiple matching recordings, competing plan sessions or an activity explicitly assigned elsewhere prevent a silent automatic match. The four-hour match does not require a successful duration, so shortened workouts can still be evaluated.

Without a start time, the existing conservative same-local-day/sport/similar-duration rule remains. Start times in a daylight-saving gap or an ambiguous repeated clock hour are rejected; use manual assignment for those dates. The local clock time is matching metadata and does not reschedule a Garmin event.

**Zuordnung & geplante Uhrzeit / Matching & planned start time** lets you search suitable recordings within ±7 local days, assign one or clear a manual confirmation. Server-side ownership, sport, date-window, unique-assignment and schedule-revision checks still apply. Missing imports remain pending and are not automatically marked as missed workouts.

## What the local calculation can assess

The calculation reads the complete available FIT/Parquet timeline, expands repeat groups and compares each planned interval with its aligned recorded time span. An optional offset states where the planned workout begins in the recording. Time is weighted by actual sample spacing; gaps over 30 seconds, track breaks and missing sensor channels are unknown. Step classification requires at least 70% relevant sensor coverage. Distance-based boundaries require suitable recorded monotonic distance.

Absolute watt targets use `power_watts` with a positive `watts` value and a configurable tolerance (default ±5%). Existing heart-rate and power-zone targets continue to work. Zone targets use the current synchronized, sport-specific Garmin zone profile; its source/date is retained. A current FTP is context, not a reconstructed historical FTP. Absolute watt prescriptions remain fixed when synchronized FTP changes.

Average activity power alone cannot verify individual intervals. If FIT data or suitable sensors are missing, duration can still be compared while intensity stays unassessed. Recorded intervals can also be misaligned when the actual workout deviates from its planned order; inspect the timeline and adjust the offset before interpreting the result.

## Proposed adjustments

Proposals are deterministic, conservative rules supported by measured evidence and confirmed feedback. AI interpretation is kept separate from the actual calendar write.

- **Reduction:** at least 70% overall relevant coverage, assessable work steps, less than 50% work time in target, and explicit *too hard* feedback. Timed work steps shorten to 75%; absolute watt targets reduce by 2%. For example, **4 × 60 s at 250 W → 4 × 45 s at 245 W**.
- **Progression:** two distinct, comparable recorded successes within 28 days, at least 90% work adherence, approximately 90–115% planned duration, explicit *too easy* feedback and no recorded discomfort. The source session must have low/moderate recorded exertion when supplied, and current readiness must be green. Absolute power targets rise by 2%; other timed work targets instead extend by 5%. Both axes are not raised together.
- Only a comparable future session in the same plan within 28 days is proposed. Sport, expanded step/target structure, zone, approximate work duration and power level must fit. Completed, unresolved matching candidates and already exported workouts are excluded. Strength/distance prescriptions without suitable timed work may have no automatic proposal.
- Warmup, recovery, cooldown and repetition count are preserved. FTP is never changed by this action. Discomfort blocks an automatic proposal.
- Preview first, then apply explicitly. Applying rechecks revisions and an evidence fingerprint; stale proposals fail without changing the plan. Each completed source session can justify one applied adjustment, preventing repeated clicks from progressively reducing/increasing a workout. Changes are logged in the existing Decision Log.

A failed or easy single workout is not proof of a changed physiological threshold. Weather, stops, recording alignment and sensor gaps can explain deviations. The rules propose one practical next-session change; they do not implement a full physiological performance model.

## Context for future AI plans

Local execution reviews are stored in `training_reviews`, refreshed hourly without AI calls, and refreshed before relevant background coach/plan generation. The next request includes only the user's still-current, matched reviews inside its selected time window when training context is enabled. Changed activity data, target prescriptions, feedback, files or zone profiles invalidate old cached evidence and old AI review links. No historical private context is sent to another user.

New AI plans can use the supplied measured FTP/zones, target adherence, completion and personal feedback to propose suitable future work. A four-week plan can be selected using the existing plan-length controls. The AI does not retrain its model weights or silently rewrite an existing calendar. Previously exported Garmin workouts require the existing explicit workflow rather than an automatic remote update.

Deleting a plan removes its derived session-analysis reports; deleting source activities or users cascades the local review rows. The existing plan/conversation deletion workflows also remove their continuation snapshots.

## Continuing after an output limit

A recoverable limit preserves the existing text and offers **Mit +8.000 Token fortsetzen / Continue with +8,000 tokens**. Clicking starts a new, billable/provider-counted generation; it does not modify a request that has already finished.

- Visible text: request up to 8,000 additional output tokens, keep the old answer and append the continuation. Only exact repeated suffix/prefix overlap is removed; no earlier text is summarized away.
- No visible answer: retry with the prior effective budget plus 8,000, bounded by the model/context limits. Hidden reasoning is not treated as an answer. A model can still exhaust its new budget before answering.
- Format/network failure: retry the pending section with the same budget. Successful plan sections are saved before the next call begins. Usage of an interrupted request can be unknown; it is not displayed as zero.
- Training plans: preserve valid completed sections and regenerate the pending invalid/incomplete section with the larger budget. Continue the remaining sections through the same schema validator. Drafts have no valid structured calendar/export representation until completion.
- Model output and context limits remain authoritative. The context window may expand within the selected model's limit to carry the previous output. If a higher retry budget cannot fit, stop before issuing the model request. An older chat message cannot be continued after the conversation has moved on.
- Ownership, model availability and current local/cloud policy are rechecked on every click. Repeated clicks reuse an active job; revisions protect saved output. Reloads restore the continuation job, and cancel/failure preserves the previous answer. Token usage and costs accumulate on the saved run.

Snapshots are stored privately with the original run only while needed. Completion removes the saved prompt/data snapshot. Public run and message payloads do not expose private continuation state.

## Update and validation

Migration **0015_training_reviews** adds the local review cache with owner/plan/activity foreign keys and indices. Standard Docker API startup (`alembic upgrade head`) and the Proxmox updater already apply it. Update and restart web, API and workers together. No new runtime dependency is needed.

Automated tests use real temporary databases and recorded-sample files plus simulated AI responses. They cover matching around midnight/DST, ownership, manual assignments, sensor gaps, watt targets, proposals, stale data and export protection; continuation covers partial/empty output, repeated clicks, cloud policy, cancellation, usage and segmented-plan recovery. Browser QA covers the focused dialog and continuation workflow across the available themes. No live Garmin upload or paid model request is part of these tests.
