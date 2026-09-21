#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/Borderlane-HA/PenguCoach.git"
BRANCH="${PENGUCOACH_BRANCH:-main}"

[[ $EUID -eq 0 ]] || { echo "Run this on the Proxmox host as root." >&2; exit 1; }
command -v pct >/dev/null || { echo "pct not found. Run this on a Proxmox VE host." >&2; exit 1; }

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info(){ echo -e "${GREEN}[PenguCoach]${NC} $*"; }
warn(){ echo -e "${YELLOW}[PenguCoach]${NC} $*"; }
die(){ echo -e "${RED}[PenguCoach] ERROR:${NC} $*" >&2; exit 1; }
ask(){ local prompt="$1" default="$2" value; read -r -p "$prompt [$default]: " value || true; echo "${value:-$default}"; }

DEFAULT_CTID="$(pvesh get /cluster/nextid 2>/dev/null || echo 200)"
DEFAULT_ROOTFS="$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active"{print $1;exit}')"
DEFAULT_TMPL="$(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 && $3=="active"{print $1;exit}')"
DEFAULT_ROOTFS="${DEFAULT_ROOTFS:-local-lvm}"
DEFAULT_TMPL="${DEFAULT_TMPL:-local}"

echo
info "PenguCoach Proxmox LXC installer"
echo "Repository: $REPO_URL ($BRANCH)"
echo
CTID="$(ask "Container ID" "$DEFAULT_CTID")"
HOSTNAME="$(ask "Hostname" "pengucoach")"
CORES="$(ask "CPU cores" "4")"
MEMORY="$(ask "RAM MB" "4096")"
SWAP="$(ask "Swap MB" "512")"
DISK="$(ask "Root disk GB" "32")"
BRIDGE="$(ask "Network bridge" "vmbr0")"
ROOTFS_STORAGE="$(ask "Container storage" "$DEFAULT_ROOTFS")"
TMPL_STORAGE="$(ask "Template storage" "$DEFAULT_TMPL")"

pct status "$CTID" >/dev/null 2>&1 && die "Container $CTID already exists."

info "Refreshing Proxmox template list"
pveam update >/dev/null
HOST_ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
case "$HOST_ARCH" in
  amd64|arm64) TEMPLATE_ARCH="$HOST_ARCH" ;;
  *) die "Unsupported Proxmox host architecture: $HOST_ARCH" ;;
esac
TEMPLATE="$(pveam available --section system | awk -v arch="$TEMPLATE_ARCH" '$2 ~ /debian-13-standard/ && $2 ~ ("_" arch "\\.tar") {print $2}' | tail -n1)"
[[ -n "$TEMPLATE" ]] || die "No Debian 13 $TEMPLATE_ARCH template found in pveam. PenguCoach requires Python 3.12+ because of the current Garmin client."

if ! pveam list "$TMPL_STORAGE" 2>/dev/null | grep -q "${TEMPLATE##*/}"; then
  info "Downloading $TEMPLATE"
  pveam download "$TMPL_STORAGE" "$TEMPLATE"
fi
TEMPLATE_VOL="$TMPL_STORAGE:vztmpl/${TEMPLATE##*/}"

info "Creating unprivileged LXC $CTID"
pct create "$CTID" "$TEMPLATE_VOL" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" --memory "$MEMORY" --swap "$SWAP" \
  --rootfs "$ROOTFS_STORAGE:$DISK" \
  --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp,type=veth" \
  --unprivileged 1 \
  --onboot 1 --ostype debian

pct start "$CTID"
info "Waiting for network"
for _ in {1..60}; do
  if pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1; then break; fi
  sleep 2
done
pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1 || die "Container has no working DNS/network."

info "Bootstrapping Git and CA certificates"
pct exec "$CTID" -- bash -lc 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates git curl'

info "Cloning PenguCoach"
pct exec "$CTID" -- bash -lc "rm -rf /opt/pengucoach && git clone --branch '$BRANCH' --depth 1 '$REPO_URL' /opt/pengucoach"

info "Installing PenguCoach inside the LXC"
pct exec "$CTID" -- env PENGUCOACH_BRANCH="$BRANCH" bash /opt/pengucoach/install/proxmox/install-app.sh

IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')"
echo
info "Installation completed"
echo "  CT ID:   $CTID"
echo "  Hostname: $HOSTNAME"
echo "  URL:     http://${IP:-<container-ip>}"
echo
echo "Inside the LXC:"
echo "  pengucoach-status"
echo "  pengucoach-update"
echo "  pengucoach-backup"
echo
echo "First open the URL and create the administrator account."
