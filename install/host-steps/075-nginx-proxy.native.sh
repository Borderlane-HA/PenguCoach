#!/usr/bin/env bash
# Generous API timeouts for local models and the 20 MB request limit for chunked uploads.
set -Eeuo pipefail
SITE=/etc/nginx/sites-available/pengucoach
[[ -f "$SITE" ]] || exit 0
BACKUP="$(mktemp)"
cp -p "$SITE" "$BACKUP"
trap 'rm -f "$BACKUP"' EXIT
if ! grep -q 'proxy_read_timeout 300s;' "$SITE"; then
  sed -i '/location \/api\/ {/a\        proxy_connect_timeout 30s;\n        proxy_send_timeout 300s;\n        proxy_read_timeout 300s;' "$SITE"
fi
if ! grep -q 'client_max_body_size' "$SITE"; then
  sed -i '0,/^\([[:space:]]*\)server_name /s//\1client_max_body_size 20m;\n\1server_name /' "$SITE"
fi
if cmp -s "$SITE" "$BACKUP"; then exit 0; fi
if nginx -t >/dev/null 2>&1; then
  systemctl reload nginx
else
  cp -p "$BACKUP" "$SITE"
  echo 'nginx configuration test failed; previous site restored' >&2
  exit 1
fi
