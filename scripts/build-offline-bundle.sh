#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="${1:-0.3.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${2:-$ROOT/dist}"
IMAGE="pengucost:${VERSION}"
mkdir -p "$OUT/bundle"
rm -f "$OUT/bundle"/*
cd "$ROOT"
echo "Building $IMAGE …"
docker build -f backend/Dockerfile -t "$IMAGE" .
docker save "$IMAGE" -o "$OUT/bundle/pengucost-image.tar"
cat > "$OUT/bundle/compose.offline.yml" <<YAML
services:
  pengucost:
    image: ${IMAGE}
    container_name: pengucost
    restart: unless-stopped
    ports: ["8080:8080"]
    volumes: ["pengucost_data:/data"]
    environment: ["TZ=Europe/Berlin"]
    security_opt: ["no-new-privileges:true"]
    cap_drop: ["ALL"]
volumes:
  pengucost_data:
YAML
cp scripts/install-offline.sh "$OUT/bundle/"
tar czf "$OUT/pengucost-offline-amd64.tar.gz" -C "$OUT/bundle" pengucost-image.tar compose.offline.yml install-offline.sh
echo "$OUT/pengucost-offline-amd64.tar.gz"
