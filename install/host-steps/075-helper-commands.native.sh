#!/usr/bin/env bash
# Refresh the shell commands from the root-owned release checkout.
set -Eeuo pipefail
SRC="$PENGUCOACH_SOURCE/install/proxmox"
for cmd in update backup status db-utf8; do
  install -m 0755 "$SRC/pengucoach-$cmd.sh" "/usr/local/bin/pengucoach-$cmd"
  ln -sf "/usr/local/bin/pengucoach-$cmd" "/usr/bin/pengucoach-$cmd"
done
