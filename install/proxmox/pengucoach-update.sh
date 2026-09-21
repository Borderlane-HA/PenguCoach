#!/usr/bin/env bash
set -Eeuo pipefail
APP=/opt/pengucoach
CHANNEL_FILE=/etc/pengucoach/channel
BRANCH="$(cat "$CHANNEL_FILE" 2>/dev/null || echo main)"
[[ $EUID -eq 0 ]] || { echo "Run as root inside the PenguCoach LXC." >&2; exit 1; }
cd "$APP"
git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
OLD_SHA="$(git rev-parse HEAD)"
echo "[PenguCoach] Current revision: $OLD_SHA"
BACKUP="$(pengucoach-backup | tail -n1)"
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

rollback(){
  echo "[PenguCoach] Update failed. Rolling source back to $OLD_SHA" >&2
  cd "$APP"; git reset --hard "$OLD_SHA" || true
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
. /etc/pengucoach/pengucoach.env
set +a
cd "$APP"; .venv/bin/alembic -c alembic.ini upgrade head
echo "[PenguCoach] Rebuilding frontend"
cd "$APP/apps/web"; npm install --no-audit --no-fund; NEXT_PUBLIC_API_BASE_URL=/api/v1 npm run build
chown -R pengucoach:pengucoach "$APP"
systemctl restart pengucoach-api pengucoach-worker pengucoach-scheduler pengucoach-web
sleep 3
curl -fsS http://127.0.0.1/healthz >/dev/null
trap - ERR
echo "[PenguCoach] Updated successfully: $OLD_SHA -> $NEW_SHA"
