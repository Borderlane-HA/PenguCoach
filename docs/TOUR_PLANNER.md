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

## Dead ends (alpha.89)

A waypoint next to the road is snapped by BRouter to the nearest usable way – often a
track or a footpath – and the route goes there and back on the same way. For every via
point PenguCoach follows the route backwards and forwards from the point closest to it
while both sides lie on top of each other (≤ 15 m); where they part is the junction.
Spurs of 60 m or more are cut by moving the waypoint to the junction and routing again
(one extra call per loop attempt). The editor marks remaining spurs and cuts them on
request (`POST /tours/route` with `clean_spurs`).

## Edit mode (alpha.89)

Every variant carries its waypoints. The editor sends them to `POST /tours/route`,
which routes each pair of neighbouring waypoints separately and caches the pieces
(600 per installation), so moving one point only routes the two pieces next to it. The
answer contains the merged line, where each piece starts (`segments`), the stats and the
dead ends. Saved tours have no waypoints; the editor samples eight along the line.

## Known ways (alpha.89)

The user's GPS tracks of the same kind of sport from the last 365 days (FIT time series
and SparkyFitness tracks, cached for ten minutes) are turned into ~90 m grid cells.
*Known ways* moves each loop waypoint to the nearest own track point within 45 % of the
loop radius; *Discover new* moves waypoints out of known cells. Every variant gets
`known_share` – the share of its length in known cells – and ranking prefers more
(known) or less (new) of it.

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
