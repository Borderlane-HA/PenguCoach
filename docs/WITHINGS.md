# Retired Withings connector

The direct Withings connector was removed at the user's request. No OAuth routes, token refreshes, sync tasks or navigation entry are active. Migration `0010_retire_withings` removes its connection/credential table. Existing imported measurements remain available with their original provenance, displayed as “Withings · Archiv”.

Historical migration `0009_withings_connection` remains in the Alembic chain so existing installations can upgrade. Inert old module/page filenames are deliberately shipped for updates through GitHub's web uploader; they contain no active connector. Reverting the migration cannot recover removed credentials.
