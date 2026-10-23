# Garmin connection methods: login or Personal API key

PenguCoach can connect to Garmin in two ways. You choose under **Settings → Garmin → Connect Garmin**.

| | Garmin login (e-mail & password) | Personal API key (official) |
|---|---|---|
| Activities & original FIT files | ✓ | ✓ |
| Daily values, sleep, HRV, stress, Body Battery, SpO₂, hydration | ✓ | ✓ |
| Weight & body data, heart-rate zones | ✓ | ✓ |
| Training status, training readiness, VO₂max trend, power zones, respiration, floors | ✓ | – (not offered by the API) |
| Send workouts to Garmin / remove them there | ✓ (opt-in) | with an additional login used only for export |
| What is stored | Garmin's sign-in tokens (encrypted); never the password | the API key and a short-lived access token (both encrypted) |
| Typical issue | Garmin may ask for a new sign-in or MFA | the key expires after its lifetime and must be replaced |

Both methods fill the same tables. Switching keeps all local data.

## Using both: API key for data, login only for workout export

With the Personal API key connected, *Settings → Garmin → Training & calendar* offers **Add Garmin login**. That login (e-mail, password, MFA if Garmin asks) is stored like the normal login – encrypted tokens, never the password – but it is used **only** when you send or remove workouts. Sync, history import and FIT downloads keep using the API key. If Garmin later rejects the export login, only export is affected; the page and the training plan ask for a new sign-in. When you switch from the login to an API key, the form offers to keep the existing login for export.

Without the extra login, features the API key cannot deliver are shown greyed out with a short hint: Readiness on Today, power zones, and the workout export switch.

## Create a Personal API key

1. Open [Garmin Connect → Personal API](https://connect.garmin.com/app/settings/personalApiToken) and sign in.
2. Create a new personal API key. If the page is not available for your account, use the Garmin login for now.
3. Pick the lifetime (Garmin offers 30 days to one year). One year is the most convenient.
4. Copy the complete key right away – Garmin may show it only once.
5. In PenguCoach choose **Personal API key**, paste the key, enter the same expiry date and click **Connect with API key**. PenguCoach exchanges the key with Garmin immediately; a wrong, revoked or expired key is rejected at once and nothing changes.

Treat the key like a password for your health data.

## Renewal

The Garmin page shows the key and its expiry. From 14 days before the expiry date it turns orange; **Renew key** replaces the key in place – sync settings, history and data stay as they are. If Garmin stops accepting the key earlier (revoked), the connection changes to *re-authentication required* and the page asks for a new key.

## Technical notes

- Flow from Garmin's reference client [`garmin/connect-personal-api-python`](https://github.com/garmin/connect-personal-api-python) (Apache-2.0): `POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token` with `Authorization: ApiKey <key>` returns a JWT; data requests use `Authorization: Bearer <jwt>`. The token is cached (encrypted in `garmin_connections.token_ciphertext`) and exchanged again when less than one hour remains or after a `401`.
- `pengucoach/garmin/personal_api.py` offers the same method names as the read-only password gateway, so sync, history import, FIT download and zones use one code path. Domains without a Personal API endpoint are recorded as `unsupported` in the sync run, not as errors.
- Activity lists are read in pages of 50 (larger pages are answered with HTTP 400/500). Daily values are requested per day, well within the documented range limits.
- HTTP 401/403 → re-authentication required, HTTP 429 → the existing cool-down. Response bodies are never logged or stored.
- Garmin decides how far back the API delivers data. Empty older days in a history import are therefore not an error.
- Field names of a few newer endpoints (for example `usersummary-service/v2/dailysummaries`) differ from the login API; PenguCoach reads both spellings and keeps the raw payload. If a value is missing with the API key but present with the login, please report the endpoint.
- Database: migration `0016_garmin_personal_api` adds `auth_mode` (`password` by default, so existing connections are unchanged), `api_key_ciphertext`, `api_key_hint` and `api_key_expires_on`.
