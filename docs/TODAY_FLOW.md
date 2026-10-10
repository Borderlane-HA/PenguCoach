# Today flow — Alpha.53

Today uses the server-side user timezone and saved records. Start, Preparation and Reflection can be selected manually; Automatic restores the recorded-data-based stage. Pending workouts stay pending when matching is ambiguous. A recorded completed activity can open Reflection; absence of an import does not establish a rest day. Upcoming sessions come from the five most recently updated saved schedules.

## Readiness and loading

Three enlarged lamps use a pause symbol, dash and checkmark in addition to color. The score ring and compact confidence bars retain the existing deterministic readiness model. Explanations remain collapsed. Loading, failed requests and insufficient evidence stay neutral.

`GET /coach/readiness` queries a bounded 28-day recovery window, today’s check-in, 14 days of activity summary columns and three days of ordinary activity feedback. It does not load FIT files, plan comparisons, body history, weather or AI. `GET /coach/briefing` loads plans and route choices separately. Weather has its own independent request. The UI retries errors, guards against late responses, preserves unsaved check-in edits and refreshes after feedback/check-in changes, on focus and every two visible minutes. Actual latency still depends on the local database and deployment.

## Preparation

The first pending workout today, or the next scheduled workout, shows saved duration, colored steps and available HR/power zones. Repeats expand for a bounded preview of 120 sections; the full workout stays available in Training. Strength exercises show stored sets, repetitions and optional weight. Missing structure is stated explicitly. Short variants retain the existing Preview → Confirm workflow and revision/export protections.

The route selector uses GPS-covered parsed recordings among the newest 50 recordings, at most 20 choices, of the matching sport. Opening a route expands its briefing and preselects the chosen plan session. Climbs and fast passages describe the historical recording; planned-step placement remains approximate. No new route, future speed or panorama availability is invented. Map and street-view settings and consent remain unchanged.

## Body check-in and reflection

Front/back views and accessible area buttons select legs, back, shoulders, arms and core. Selecting a region alone does not save a severity. Each region has levels 1–5; save with the normal daily check-in. The highest reported severity, including the overall selector, contributes once to the existing soreness factor. Regional “none” alone does not establish lack of soreness everywhere. Choosing overall “none” clears regional values.

Reflection lists only owned activities with positive known duration whose recorded end is already in the past today. Ordinary feeling/comment feedback is saved on the chosen activity. Existing exertion, discomfort, independent training experiences and route notes are preserved. Multiple activities can be selected separately. The tomorrow preview uses the user’s server-side local calendar date and saved pending sessions; an empty calendar is described as unscheduled.

## Personal layout and weather

“My Today view” changes card order by dragging or up/down buttons, hides optional cards, pins one to four available metrics and selects training hours. Changes are reviewed as a draft and saved per user in existing preferences. Readiness and the daily check-in stay available above the cards. Restore defaults changes the draft until saved.

Hourly weather windows require the existing enabled weather setting and configured location. No browser geolocation or new API key is requested. `GET /weather/windows` compares up to three non-overlapping windows today that fit the available minutes and preferred hours. Unix timestamps are converted through the user timezone for daylight-saving transitions. Rain probability and gust readings refer to the preceding forecast hour, so coverage uses end-boundary readings. Partial hours conservatively use the covered whole hour; no minute-level precision is claimed.

All required hourly values must exist and be valid; gaps are not filled. Windows expose rain, strong wind, frost, heat, thunderstorm or snow/ice hints when present. These are forecast comparisons, not guarantees of suitable conditions. No plan is changed automatically. Disabled or missing weather configuration makes no provider request. Public forecast results alone are cached for ten minutes, with concurrent requests to the same location combined. Check-ins and readiness are not cached. Provider errors show an unavailable state with retry.

Reference: [Open-Meteo forecast API](https://open-meteo.com/en/docs).

## Upgrade

No new migration, dependency or API key. Use the full archive for a clean installation or apply the Alpha.52 → Alpha.53 update at the repository root. Rebuild the application containers as with earlier source updates. Existing user settings, provider credentials and stored activities remain compatible.
