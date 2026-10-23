#!/usr/bin/env bash
# Build tools now use their own cache. Remove npm/pip caches that Alpha.73/74
# updates wrote into the service user's home, which is the data directory.
set -Eeuo pipefail
USER_NAME="${PENGUCOACH_SERVICE_USER:-pengucoach}"
install -d -m 0750 -o "$USER_NAME" -g "$USER_NAME" /var/cache/pengucoach-build
for item in .npm .cache; do
  path="$PENGUCOACH_DATA/$item"
  if [[ -d "$path" && ! -L "$path" ]]; then
    rm -rf --one-file-system -- "$path"
  fi
done
