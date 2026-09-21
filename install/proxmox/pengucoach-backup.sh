#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP_ROOT=/var/lib/pengucoach/backups
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"
echo "[PenguCoach] Backing up database"
runuser -u postgres -- pg_dump -Fc pengucoach > "$DEST/pengucoach.pgdump"
echo "[PenguCoach] Backing up data and configuration"
tar -C /var/lib -czf "$DEST/data.tar.gz" --exclude='pengucoach/backups' pengucoach
tar -C /etc -czf "$DEST/config.tar.gz" pengucoach
sha256sum "$DEST"/* > "$DEST/SHA256SUMS"
chmod -R go-rwx "$DEST"
echo "$DEST"
