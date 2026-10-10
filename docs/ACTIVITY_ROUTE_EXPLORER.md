# Activity Route Explorer — Alpha.48

Activities with recorded coordinates now show an OpenStreetMap route synchronized
with the workout chart. FIT coordinates are normalized to degrees by the existing
reader; manually imported GPX/TCX data uses the same time-series endpoint.
Summary-only activities without a recorded route do not invent a map or samples.

## Using the explorer

- Move the mouse over the chart to select the corresponding recorded sample.
- Click to lock a selection; **Unlock selection** resumes mouse following.
- The position slider works on phones and with the keyboard. Focus a chart and
  use Left/Right, Home/End or Enter to select or lock/unlock a point.
- A route click selects a nearby recorded point. Start and finish are marked.
- Choose a recorded metric under **Route color** to color the track from low to
  high values. Missing measurements use gray dashes.
- Choose time or distance, overlay or stacked charts, and an analysis range.
  Axis positions use actual elapsed time/distance rather than equally spaced
  samples. Incomplete or non-monotonic axes explicitly fall back to point order.
- Only available measurement channels appear. The readout shows only values
  actually present at the selected sample. Zero watts is valid; null is missing.
- Calculated grade is a smoothed approximation from elevation and distance.
- GPS gaps, gaps over two minutes and separate GPX track segments break the route.
  A missing GPS sample hides the marker instead of moving it to a fabricated point.

The activity endpoint currently returns at most 5,000 sampled records. Displayed
positions are those samples, not an invented reconstruction of every second.
Existing imported GPX files without timestamps may need re-importing to benefit
from the corrected distance derivation; stored original data is not modified.

## Personal settings

Every signed-in user can open **Settings → Maps & street view**:

1. Enable/disable the OpenStreetMap route map. No OSM key is required.
2. Select the preferred panorama provider.
3. Save a personal Google API key and/or Apple Maps web token.
4. Leave an input blank to keep its existing credential; use the delete button
   to remove one. Re-enter a credential to replace it.

Credentials are encrypted with the existing `PENGUCOACH_ENCRYPTION_KEY` and stored
under the owner's user preferences. Retain that installation key across updates
and backups. The settings API returns configured flags, never decrypted keys.
There is no new database migration or installation-wide panorama key.

### Google Street View

Create a Google Cloud project, enable **Maps Embed API** and create an API key.
Restrict that browser key to your PenguCoach website origin/referrers and Maps
Embed API. Follow Google's account/billing prerequisites. Embed usage is currently
provided without usage charges; that does not apply to other Google Maps APIs.

- Setup: https://developers.google.com/maps/documentation/embed/get-api-key
- Pricing: https://developers.google.com/maps/documentation/embed/usage-and-billing

The viewer requests the nearest outdoor panorama within 50 metres and sets its
initial heading from the local recorded route. Google displays its own unavailable
or credential-error message inside the cross-origin iframe; PenguCoach cannot
reliably read that message or claim independent coverage verification. The OSM
map is unmounted while Google Street View is active. The chart remains usable.
This also avoids displaying Google imagery alongside a non-Google map across
deployments with different applicable Google Maps terms.

### Apple Look Around

Create an Apple Maps web token in your Apple Developer account, authorizing the
PenguCoach website. Enter the web token, never a private `.p8` signing key. Replace
expired tokens in settings. Developer-account requirements, quotas and terms apply.

- Token: https://developer.apple.com/documentation/mapkitjs/creating-a-maps-token
- Look Around: https://developer.apple.com/documentation/mapkitjs/lookaround

The documented MapKit JS core loader with `look-around,services` loads only after
consent, inside an isolated same-origin iframe. The viewer handles load, coverage,
browser and service errors. Each iframe owns its token/SDK lifetime; tokens are
not shared between user accounts or persisted in browser storage.

## Consent and imagery

Opening the panorama controls does not contact Google or Apple. **Confirm and
load** authorizes that viewer session and releases only the current user's
credential to their browser through an authenticated no-store response. Closing
unmounts the viewer and discards the in-memory credential. A subsequent opening
requires another confirmation; cancellation also ignores late access responses.

**Follow chart** updates the panorama after the selection has stayed still for
650 ms. Turn it off to inspect the current panorama and use **Load this point**
when needed. A consented provider receives selected coordinates and normal
connection data such as IP address, but no heart-rate/power/other sensor values.
OSM tile requests separately reveal the viewed map area and normal connection
data; disable the route map in personal settings to prevent these requests.

Panoramas are provider recordings, not footage from the workout date. Coverage
can be absent and the panorama location may differ from the workout coordinate.
The OSM tile service has best-effort availability and a usage policy; this release
uses normal browser caching and visible attribution, without bulk/offline fetching:
https://operations.osmfoundation.org/policies/tiles/.

## Validation

Automated tests cover encrypted storage, account isolation, consent, key replacement
and deletion, unavailable encryption, no-store responses, actual authenticated HTTP
routes and sparse/segmented GPX input. Browser verification covers diagram/map
synchronization, settings, provider consent/cancellation, mobile layouts and
provider lifecycle using mocked services. Live Google/Apple credentials are not
included and live panorama delivery must be checked with the user's configured
account, allowed origin, browser and local imagery coverage.
