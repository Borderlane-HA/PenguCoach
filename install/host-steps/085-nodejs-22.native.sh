#!/usr/bin/env bash
# Node.js 20 is end-of-life (30 April 2026) and gets no more security fixes, e.g.
# for the bundled Brotli decoder (CVE-2026-111497). Move native installations to
# the maintained Node.js 22 line from NodeSource. The web build of this release
# runs on both, so the switch is safe right before the services start.
# A network or repository problem must not roll back the whole update: the step
# then only warns, and the update area keeps showing the recommendation.
set -Eeuo pipefail
WANT="22.23.4"
have="$(node -p 'process.versions.node' 2>/dev/null || echo 0.0.0)"
newer() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]; }
if newer "$have" "$WANT"; then
  echo "Node.js $have is current."
  exit 0
fi
echo "Node.js $have is outdated – installing Node.js 22 from NodeSource."
if ! curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/pengucoach-nodesource.sh; then
  echo "WARNING: NodeSource not reachable – Node.js stays at $have. Install it later as root: curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs" >&2
  exit 0
fi
if ! bash /tmp/pengucoach-nodesource.sh >/dev/null || ! DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs; then
  echo "WARNING: Node.js 22 could not be installed – Node.js stays at $have. Install it later as root: curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs" >&2
  rm -f /tmp/pengucoach-nodesource.sh
  exit 0
fi
rm -f /tmp/pengucoach-nodesource.sh
echo "Node.js $(node -p 'process.versions.node') installed."
