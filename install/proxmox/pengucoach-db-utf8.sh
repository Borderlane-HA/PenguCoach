#!/usr/bin/env bash
set -Eeuo pipefail

DB_NAME="${PENGUCOACH_DB_NAME:-pengucoach}"
TEMP_DB="${DB_NAME}_utf8_repair"
STAMP="$(date +%Y%m%d%H%M%S)"
OLD_DB="${DB_NAME}_sqlascii_${STAMP}"
BACKUP_DIR="/var/lib/postgresql/pengucoach-repair-backups"
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}-before-utf8-${STAMP}.dump"

info(){ echo "[PenguCoach] $*"; }
die(){ echo "[PenguCoach] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root inside the PenguCoach LXC."
command -v psql >/dev/null 2>&1 || die "PostgreSQL client not found."

if ! locale -a 2>/dev/null | grep -qi '^en_US\.utf8$'; then
  info "Installing/generating en_US.UTF-8 locale"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq locales
  sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
  locale-gen en_US.UTF-8 >/dev/null
  update-locale LANG=en_US.UTF-8
fi
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

ENCODING="$(runuser -u postgres -- psql -d postgres -Atqc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='${DB_NAME}'")"
[[ -n "$ENCODING" ]] || die "Database '$DB_NAME' does not exist."
if [[ "$ENCODING" == "UTF8" ]]; then
  info "Database '$DB_NAME' is already UTF8. Nothing to do."
  exit 0
fi
[[ "$ENCODING" == "SQL_ASCII" ]] || die "Unexpected database encoding '$ENCODING'. Automatic repair only supports SQL_ASCII -> UTF8."

OWNER="$(runuser -u postgres -- psql -d postgres -Atqc "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='${DB_NAME}'")"
[[ -n "$OWNER" ]] || die "Could not determine database owner."

install -d -o postgres -g postgres -m 0700 "$BACKUP_DIR"

restart_services(){
  systemctl start pengucoach-api pengucoach-worker pengucoach-scheduler 2>/dev/null || true
}
trap restart_services EXIT

info "Stopping PenguCoach database clients"
systemctl stop pengucoach-api pengucoach-worker pengucoach-scheduler 2>/dev/null || true

info "Creating safety backup: $BACKUP_FILE"
runuser -u postgres -- pg_dump --format=custom --encoding=UTF8 --file="$BACKUP_FILE" "$DB_NAME"
chmod 0600 "$BACKUP_FILE"

info "Creating temporary UTF8 database"
runuser -u postgres -- psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$TEMP_DB\" WITH (FORCE);" >/dev/null
runuser -u postgres -- createdb \
  --owner="$OWNER" \
  --encoding=UTF8 \
  --locale=en_US.UTF-8 \
  --template=template0 \
  "$TEMP_DB"

info "Restoring backup into UTF8 database"
runuser -u postgres -- pg_restore \
  --exit-on-error \
  --no-owner \
  --role="$OWNER" \
  --dbname="$TEMP_DB" \
  "$BACKUP_FILE"

NEW_ENCODING="$(runuser -u postgres -- psql -d postgres -Atqc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='${TEMP_DB}'")"
[[ "$NEW_ENCODING" == "UTF8" ]] || die "Temporary database is not UTF8. Aborting before switchover."

info "Switching databases (old database remains available as $OLD_DB)"
runuser -u postgres -- psql -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB_NAME', '$TEMP_DB') AND pid <> pg_backend_pid();" >/dev/null
runuser -u postgres -- psql -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE "$DB_NAME" RENAME TO "$OLD_DB";"
if ! runuser -u postgres -- psql -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE "$TEMP_DB" RENAME TO "$DB_NAME";"; then
  echo "[PenguCoach] Switchover failed; restoring the original database name." >&2
  runuser -u postgres -- psql -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE "$OLD_DB" RENAME TO "$DB_NAME";" || true
  die "Could not activate the UTF8 database. Original database was preserved."
fi

info "Starting PenguCoach services"
restart_services
sleep 3

FINAL_ENCODING="$(runuser -u postgres -- psql -d postgres -Atqc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='${DB_NAME}'")"
[[ "$FINAL_ENCODING" == "UTF8" ]] || die "Switchover completed but active database is not UTF8."

if systemctl cat pengucoach-api.service >/dev/null 2>&1; then
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    info "API health check passed"
  else
    die "API health check failed. Old database is still preserved as '$OLD_DB'."
  fi
else
  info "API unit is not installed yet; skipping application health check."
fi

trap - EXIT
info "Database repair completed successfully."
info "Active database: $DB_NAME (UTF8)"
info "Old database retained: $OLD_DB"
info "Backup retained: $BACKUP_FILE"
info "After validation, the old database can be removed manually with:"
echo "  runuser -u postgres -- dropdb '$OLD_DB'"
