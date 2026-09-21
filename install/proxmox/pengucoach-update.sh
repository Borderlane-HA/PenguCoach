#!/usr/bin/env bash
set -Eeuo pipefail
APP=/opt/pengucoach
ENV_FILE=/etc/pengucoach/pengucoach.env
CHANNEL_FILE=/etc/pengucoach/channel
BRANCH="$(cat "$CHANNEL_FILE" 2>/dev/null || echo main)"
[[ $EUID -eq 0 ]] || { echo "Run as root inside the PenguCoach LXC." >&2; exit 1; }
cd "$APP"
git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
OLD_SHA="$(git rev-parse HEAD)"
OLD_VERSION="$(sed -n 's/^PENGUCOACH_APP_VERSION=//p' "$ENV_FILE" 2>/dev/null | tail -n1)"
echo "[PenguCoach] Current revision: $OLD_SHA"
BACKUP="$(/usr/local/bin/pengucoach-backup | tail -n1)"
echo "[PenguCoach] Backup: $BACKUP"

git fetch origin --tags --prune
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Local source changes detected in $APP. Update aborted to avoid overwriting them." >&2
  exit 2
fi
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
NEW_SHA="$(git rev-parse HEAD)"
if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then echo "[PenguCoach] Already up to date."; exit 0; fi
NEW_VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"

rollback(){
  echo "[PenguCoach] Update failed. Rolling source back to $OLD_SHA" >&2
  cd "$APP"; git reset --hard "$OLD_SHA" || true
  if [[ -n "${OLD_VERSION:-}" && -f "$ENV_FILE" ]]; then
    if grep -q '^PENGUCOACH_APP_VERSION=' "$ENV_FILE"; then
      sed -i "s/^PENGUCOACH_APP_VERSION=.*/PENGUCOACH_APP_VERSION=${OLD_VERSION}/" "$ENV_FILE" || true
    fi
  fi
  "$APP/.venv/bin/pip" install . >/dev/null 2>&1 || true
  cd "$APP/apps/web"; npm install --no-audit --no-fund >/dev/null 2>&1 || true; NEXT_PUBLIC_API_BASE_URL=/api/v1 npm run build >/dev/null 2>&1 || true
  systemctl restart pengucoach-api pengucoach-worker pengucoach-scheduler pengucoach-web || true
}
trap rollback ERR

echo "[PenguCoach] Updating Python environment"
cd "$APP"; .venv/bin/pip install --upgrade pip wheel >/dev/null; .venv/bin/pip install .
echo "[PenguCoach] Applying database migrations"
set -a
# shellcheck disable=SC1091
. "$ENV_FILE"
set +a
cd "$APP"; .venv/bin/alembic -c alembic.ini upgrade head
echo "[PenguCoach] Rebuilding frontend"
cd "$APP/apps/web"; npm install --no-audit --no-fund; NEXT_PUBLIC_API_BASE_URL=/api/v1 npm run build
chown -R pengucoach:pengucoach "$APP"

# Refresh helper commands on every update so fixes to installer utilities reach /usr/local/bin.
install -m 0755 "$APP/install/proxmox/pengucoach-update.sh" /usr/local/bin/pengucoach-update
install -m 0755 "$APP/install/proxmox/pengucoach-backup.sh" /usr/local/bin/pengucoach-backup
install -m 0755 "$APP/install/proxmox/pengucoach-status.sh" /usr/local/bin/pengucoach-status
install -m 0755 "$APP/install/proxmox/pengucoach-db-utf8.sh" /usr/local/bin/pengucoach-db-utf8
for cmd in pengucoach-update pengucoach-backup pengucoach-status pengucoach-db-utf8; do
  ln -sf "/usr/local/bin/$cmd" "/usr/bin/$cmd"
done

DB_ENCODING="$(runuser -u postgres -- psql -d postgres -Atqc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='pengucoach'" 2>/dev/null || true)"
if [[ -n "$DB_ENCODING" && "$DB_ENCODING" != "UTF8" ]]; then
  echo "[PenguCoach] WARNING: database encoding is $DB_ENCODING, expected UTF8." >&2
  echo "[PenguCoach] Run 'pengucoach-db-utf8' after this update before starting a historical Garmin import." >&2
fi

# Keep the runtime-reported version aligned with the source package automatically.
if grep -q '^PENGUCOACH_APP_VERSION=' "$ENV_FILE"; then
  sed -i "s/^PENGUCOACH_APP_VERSION=.*/PENGUCOACH_APP_VERSION=${NEW_VERSION}/" "$ENV_FILE"
else
  echo "PENGUCOACH_APP_VERSION=${NEW_VERSION}" >> "$ENV_FILE"
fi

echo "[PenguCoach] Restarting services for ${NEW_VERSION}"
systemctl restart pengucoach-api pengucoach-worker pengucoach-scheduler pengucoach-web
sleep 3
curl -fsS http://127.0.0.1/healthz >/dev/null
trap - ERR
echo "[PenguCoach] Updated successfully to ${NEW_VERSION}: $OLD_SHA -> $NEW_SHA"
