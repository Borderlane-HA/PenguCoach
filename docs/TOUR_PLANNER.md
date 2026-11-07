# Tour planner — Alpha.87

*Touren* (sidebar; on phones via **Aktivitäten → Tour planen**) plans tours per sport
and exports them as GPX. No account, no API key.

## How a tour is found

- **Routing:** [BRouter](https://github.com/abrensch/brouter) (open source). Default is
  the public server `https://brouter.de/brouter`; administrators can enter their own
  BRouter (e.g. `http://192.168.1.50:17777`) under *Routing-Server* on the page and test
  it. Only the API server talks to BRouter – the browser never does, and other users
  cannot change the address.
- **Loop (Rundkurs):** PenguCoach places four waypoints on a circle that passes through
  the start, asks BRouter for the route through them and rescales the circle until the
  length is within ±8 % of the wish (at most four attempts per variant). Three variants
  point in different directions (or around the chosen direction: ±45°). “Other
  suggestions” rotates the directions.
- **A → B:** start and destination (pins can be dragged); BRouter's alternatives 0–3
  give the variants.
- Variants that are nearly the same route are dropped. The best fit comes first: close
  to the wished length, little riding twice.

## Sports and profiles

Only profiles that ship with every BRouter installation are used, so a self-hosted
server behaves like brouter.de. Wishes set profile variables (`profile:<name>=…`);
older servers ignore unknown ones.

| Sport | Profile | Notes |
|---|---|---|
| Road bike | `fastbike` (`fastbike-verylowtraffic` with *low traffic*) | warns about unpaved parts |
| Gravel | `gravel` | `prefer_unpaved_paths` |
| MTB | `mtb` | |
| Bike tour | `trekking` | *low traffic*: `avoid_unsafe`, `consider_traffic` |
| Running | `hiking-mountain` | `iswet=1` (keeps to firm paths), SAC ≤ T1, no steps |
| Trail running | `hiking-mountain` | SAC ≤ T2, `path_preference=20` (away from roads), forest |
| Hiking | `hiking-mountain` | SAC ≤ T3, quiet paths |

Wishes: **low traffic**, **less climbing**, **forest & water**.

## What a variant shows

- Length, climbing (BRouter's filtered ascent), descent, highest and lowest point.
- **Surface** from the OSM tags of every segment: paved, unpaved, *probably* paved /
  unpaved (no surface tag, guessed from the way type) and unknown – weighted by length.
- Share ridden **twice** (out and back).
- **Estimated duration:** your median speed of the last 180 days for that kind of
  activity (three or more needed), otherwise a standard pace; plus a climbing
  allowance (halved for personal speeds, which already include your usual hills).
  Hiking uses DIN 33466 (4 km/h, 300 m/h up, 500 m/h down).
- Elevation profile; moving over it moves a marker on the map. **3D** shows the tour on
  terrain with the line coloured by elevation and the flyover.
- Warnings: length clearly off, out-and-back, unpaved parts for road bikes, a lot of
  road for trail sports, ferries.

## Export

**GPX herunterladen** writes a GPX 1.1 track with elevation. It imports into Garmin
Connect (*Training & Planning → Courses → Import*, then *Send to device*), Garmin Edge
(copy to `Garmin/NewFiles`), Komoot (import in *Plan*), Strava, Wahoo, Hammerhead,
OsmAnd, Locus and most watches. Direct upload is not built in: Komoot has no open API
for it and Garmin's course upload is not officially available.

Saved tours keep line, elevation and summary (table `planned_tours`, migration
`0020_tour_planner`); they can be shown again, exported and deleted. The routing server
is stored in `app_settings`.

## Limits

- Needs internet (brouter.de) or a reachable own BRouter; errors are explained in the
  page (point off the network, area not covered, server busy, timeout).
- A loop can only be as good as the path network: in sparse areas the length may differ
  more, which is flagged.
- Requests per installation are limited to two at a time so the public server is not
  flooded; a loop search makes about 3–12 calls.
