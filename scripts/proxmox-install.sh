#!/usr/bin/env bash
set -Eeuo pipefail

# PenguCost guided Proxmox VE installer
# - Proxmox VE 8 -> Debian 12 LXC
# - Proxmox VE 9 -> Debian 13 LXC
# - Unprivileged LXC, Docker inside the container
# - Guided quick/advanced setup before anything is created
# - Source is downloaded before LXC creation to avoid half-created containers

REPO="Borderlane-HA/PenguCost"
REPO_URL="https://github.com/${REPO}"

# Environment overrides are kept for scripted installs.
VMID="${VMID:-}"
CT_HOSTNAME="${PENGUCOST_CT_HOSTNAME:-pengucost}"
STORAGE="${STORAGE:-}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-}"
BRIDGE="${BRIDGE:-vmbr0}"
CORES="${CORES:-2}"
MEMORY="${MEMORY:-2048}"
SWAP="${SWAP:-512}"
DISK="${DISK:-8}"
APP_PORT="${APP_PORT:-8080}"
NETWORK_MODE="${NETWORK_MODE:-dhcp}"
STATIC_IP="${STATIC_IP:-}"
GATEWAY="${GATEWAY:-}"
VLAN_TAG="${VLAN_TAG:-}"
INSTALL_CHANNEL="${PENGUCOST_CHANNEL:-main}"
EXACT_TAG="${PENGUCOST_TAG:-}"
ONBOOT="${ONBOOT:-1}"
AUTO_CLEANUP="${AUTO_CLEANUP:-ask}"

CREATED=0
SUCCESS=0
TMPDIR=""

ESC=$'\033'
C_CYAN="${ESC}[36m"
C_GREEN="${ESC}[32m"
C_YELLOW="${ESC}[33m"
C_RED="${ESC}[31m"
C_BOLD="${ESC}[1m"
C_DIM="${ESC}[2m"
C_RESET="${ESC}[0m"

info()  { printf '%b›%b %s\n' "$C_CYAN" "$C_RESET" "$*"; }
ok()    { printf '%b✓%b %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%b!%b %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
fail()  { printf '%b✗%b %s\n' "$C_RED" "$C_RESET" "$*" >&2; }

banner() {
  clear 2>/dev/null || true
  printf '%b' "$C_CYAN"
  cat <<'ART'
 ____  _____ _   _  ____ _   _  ____ ___  ____ _____
|  _ \| ____| \ | |/ ___| | | |/ ___/ _ \/ ___|_   _|
| |_) |  _| |  \| | |  _| | | | |  | | | \___ \ | |
|  __/| |___| |\  | |_| | |_| | |__| |_| |___) || |
|_|   |_____|_| \_|\____|\___/ \____\___/|____/ |_|
ART
  printf '%b\n' "$C_RESET"
  printf '%bGuided Proxmox VE installer%b\n\n' "$C_BOLD" "$C_RESET"
}

prompt() {
  local label="$1" default="${2:-}" value
  if [[ -n "$default" ]]; then
    read -r -p "$label [$default]: " value
    printf '%s' "${value:-$default}"
  else
    read -r -p "$label: " value
    printf '%s' "$value"
  fi
}

confirm() {
  local label="$1" default="${2:-y}" answer suffix
  if [[ "$default" == "y" ]]; then suffix="Y/n"; else suffix="y/N"; fi
  read -r -p "$label [$suffix]: " answer || true
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy]$ ]]
}

choose_setup() {
  echo "Choose setup mode:"
  echo "  1) Quick setup      ${C_DIM}(recommended defaults, DHCP, main branch)${C_RESET}"
  echo "  2) Advanced setup   ${C_DIM}(resources, storage, network, release source)${C_RESET}"
  local choice
  choice="$(prompt 'Selection' '1')"
  case "$choice" in
    1) SETUP_MODE="quick" ;;
    2) SETUP_MODE="advanced" ;;
    *) fail "Invalid selection."; exit 1 ;;
  esac
}

list_storage_names() {
  local content="$1"
  pvesm status --content "$content" 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}' | paste -sd ', ' -
}

resolve_source() {
  case "$INSTALL_CHANNEL" in
    main)
      SOURCE_REF="main"
      SOURCE_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"
      ;;
    stable)
      info "Resolving latest PenguCost release …"
      SOURCE_REF="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1 || true)"
      if [[ -z "$SOURCE_REF" ]]; then
        SOURCE_REF="$(curl -fsSL "https://api.github.com/repos/${REPO}/tags?per_page=1" \
          | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1 || true)"
      fi
      [[ -n "$SOURCE_REF" ]] || { fail "Could not resolve a stable PenguCost tag."; exit 1; }
      SOURCE_URL="${REPO_URL}/archive/refs/tags/${SOURCE_REF}.tar.gz"
      ;;
    tag)
      [[ -n "$EXACT_TAG" ]] || { fail "No exact tag specified."; exit 1; }
      SOURCE_REF="$EXACT_TAG"
      SOURCE_URL="${REPO_URL}/archive/refs/tags/${SOURCE_REF}.tar.gz"
      ;;
    *)
      fail "Unknown install channel: $INSTALL_CHANNEL"
      exit 1
      ;;
  esac
}

advanced_setup() {
  echo
  printf '%bContainer%b\n' "$C_BOLD" "$C_RESET"
  VMID="$(prompt 'Container ID' "$VMID")"
  CT_HOSTNAME="$(prompt 'Hostname' "$CT_HOSTNAME")"
  CORES="$(prompt 'CPU cores' "$CORES")"
  MEMORY="$(prompt 'RAM in MB' "$MEMORY")"
  SWAP="$(prompt 'Swap in MB' "$SWAP")"
  DISK="$(prompt 'Disk in GB' "$DISK")"

  echo
  printf '%bStorage%b\n' "$C_BOLD" "$C_RESET"
  echo "RootFS-capable storage: $(list_storage_names rootdir)"
  STORAGE="$(prompt 'Container storage' "$STORAGE")"
  echo "Template-capable storage: $(list_storage_names vztmpl)"
  TEMPLATE_STORAGE="$(prompt 'Template storage' "$TEMPLATE_STORAGE")"

  echo
  printf '%bNetwork%b\n' "$C_BOLD" "$C_RESET"
  BRIDGE="$(prompt 'Bridge' "$BRIDGE")"
  echo "  1) DHCP"
  echo "  2) Static IPv4"
  local net_choice
  net_choice="$(prompt 'Network mode' "$([[ "$NETWORK_MODE" == "static" ]] && echo 2 || echo 1)")"
  case "$net_choice" in
    1) NETWORK_MODE="dhcp" ;;
    2)
      NETWORK_MODE="static"
      STATIC_IP="$(prompt 'IPv4/CIDR (example 10.10.4.50/24)' "$STATIC_IP")"
      GATEWAY="$(prompt 'Gateway (example 10.10.4.1)' "$GATEWAY")"
      [[ -n "$STATIC_IP" && -n "$GATEWAY" ]] || { fail "Static networking requires IP/CIDR and gateway."; exit 1; }
      ;;
    *) fail "Invalid network mode."; exit 1 ;;
  esac
  VLAN_TAG="$(prompt 'VLAN tag (blank = none)' "$VLAN_TAG")"
  APP_PORT="$(prompt 'PenguCost web port' "$APP_PORT")"

  echo
  printf '%bPenguCost source%b\n' "$C_BOLD" "$C_RESET"
  echo "  1) Main branch      (current development build)"
  echo "  2) Stable           (latest GitHub release/tag)"
  echo "  3) Exact tag"
  local source_default=1 source_choice
  [[ "$INSTALL_CHANNEL" == "stable" ]] && source_default=2
  [[ "$INSTALL_CHANNEL" == "tag" ]] && source_default=3
  source_choice="$(prompt 'Source' "$source_default")"
  case "$source_choice" in
    1) INSTALL_CHANNEL="main" ;;
    2) INSTALL_CHANNEL="stable" ;;
    3)
      INSTALL_CHANNEL="tag"
      EXACT_TAG="$(prompt 'Tag (example v0.3.0)' "$EXACT_TAG")"
      ;;
    *) fail "Invalid source selection."; exit 1 ;;
  esac
}

show_summary() {
  local network_desc
  if [[ "$NETWORK_MODE" == "dhcp" ]]; then
    network_desc="DHCP"
  else
    network_desc="${STATIC_IP} via ${GATEWAY}"
  fi
  [[ -n "$VLAN_TAG" ]] && network_desc+=" · VLAN ${VLAN_TAG}"

  echo
  printf '%b────────────────────────────────────────────────────────────%b\n' "$C_CYAN" "$C_RESET"
  printf '%bInstallation summary%b\n' "$C_BOLD" "$C_RESET"
  printf '  Proxmox VE     : %s\n' "$PVE_MAJOR"
  printf '  Debian LXC     : %s (unprivileged)\n' "$DEBIAN_MAJOR"
  printf '  VMID / Host    : %s / %s\n' "$VMID" "$CT_HOSTNAME"
  printf '  Resources      : %s vCPU · %s MB RAM · %s MB swap · %s GB disk\n' "$CORES" "$MEMORY" "$SWAP" "$DISK"
  printf '  Storage        : %s (template: %s)\n' "$STORAGE" "$TEMPLATE_STORAGE"
  printf '  Network        : %s · %s\n' "$BRIDGE" "$network_desc"
  printf '  Web port       : %s\n' "$APP_PORT"
  printf '  PenguCost      : %s\n' "$SOURCE_REF"
  printf '%b────────────────────────────────────────────────────────────%b\n\n' "$C_CYAN" "$C_RESET"
}

cleanup_tmp() {
  [[ -n "$TMPDIR" && -d "$TMPDIR" ]] && rm -rf "$TMPDIR"
}

handle_error() {
  local code="$1" line="$2"
  trap - ERR
  set +e
  echo
  fail "Installation failed at line ${line} (exit code ${code})."
  if (( CREATED == 1 && SUCCESS == 0 )); then
    warn "LXC ${VMID} was created but PenguCost did not finish installing."
    local remove="n"
    case "$AUTO_CLEANUP" in
      yes|y|1) remove="y" ;;
      no|n|0) remove="n" ;;
      *) confirm "Remove incomplete LXC ${VMID} now?" "y" && remove="y" || remove="n" ;;
    esac
    if [[ "$remove" == "y" ]]; then
      pct stop "$VMID" >/dev/null 2>&1 || true
      pct destroy "$VMID" --purge 1 >/dev/null 2>&1 || true
      ok "Incomplete LXC ${VMID} removed."
    else
      warn "LXC ${VMID} was kept for troubleshooting."
    fi
  fi
  cleanup_tmp
  exit "$code"
}

trap 'handle_error $? $LINENO' ERR
trap cleanup_tmp EXIT

# ── Host validation ──────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || { fail "Run this script as root on the Proxmox VE host."; exit 1; }
command -v pveversion >/dev/null 2>&1 || { fail "This does not look like a Proxmox VE host."; exit 1; }
command -v pct >/dev/null 2>&1 || { fail "pct was not found."; exit 1; }
command -v curl >/dev/null 2>&1 || { fail "curl is required on the Proxmox host."; exit 1; }

PVE_MAJOR="$(pveversion | sed -n 's/.*pve-manager\/\([0-9]\+\).*/\1/p' | head -1)"
[[ "$PVE_MAJOR" =~ ^(8|9)$ ]] || { fail "Supported Proxmox VE versions: 8.x and 9.x. Detected: ${PVE_MAJOR:-unknown}"; exit 1; }
DEBIAN_MAJOR=12
[[ "$PVE_MAJOR" == "9" ]] && DEBIAN_MAJOR=13

[[ -n "$VMID" ]] || VMID="$(pvesh get /cluster/nextid 2>/dev/null || echo 120)"
[[ -n "$STORAGE" ]] || STORAGE="$(pvesm status --content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')"
[[ -n "$TEMPLATE_STORAGE" ]] || TEMPLATE_STORAGE="$(pvesm status --content vztmpl 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')"
[[ -n "$STORAGE" && -n "$TEMPLATE_STORAGE" ]] || { fail "Could not auto-detect suitable Proxmox storage."; exit 1; }

banner
ok "Detected Proxmox VE ${PVE_MAJOR} → Debian ${DEBIAN_MAJOR} LXC"
choose_setup
[[ "$SETUP_MODE" == "advanced" ]] && advanced_setup

[[ "$VMID" =~ ^[0-9]+$ ]] || { fail "VMID must be numeric."; exit 1; }
[[ "$CORES" =~ ^[0-9]+$ && "$MEMORY" =~ ^[0-9]+$ && "$SWAP" =~ ^[0-9]+$ && "$DISK" =~ ^[0-9]+$ ]] || { fail "CPU/RAM/swap/disk values must be numeric."; exit 1; }
[[ "$APP_PORT" =~ ^[0-9]+$ ]] && (( APP_PORT >= 1 && APP_PORT <= 65535 )) || { fail "Invalid web port."; exit 1; }
if pct status "$VMID" >/dev/null 2>&1; then fail "VMID $VMID already exists."; exit 1; fi

resolve_source
show_summary
confirm "Create this LXC and install PenguCost?" "y" || { warn "Installation cancelled. Nothing was changed."; exit 0; }

TMPDIR="$(mktemp -d)"

# Download source BEFORE creating a container. If GitHub/ref is unavailable,
# there is nothing to clean up on the Proxmox host.
info "Checking PenguCost source ${SOURCE_REF} …"
curl -fL --retry 2 --connect-timeout 15 "$SOURCE_URL" -o "$TMPDIR/pengucost-source.tar.gz"
ok "PenguCost source downloaded."

# Locate/download Debian template BEFORE creating the LXC as well.
TEMPLATE="$(pveam list "$TEMPLATE_STORAGE" 2>/dev/null | awk -v d="debian-${DEBIAN_MAJOR}-standard" '$1 ~ d {print $1}' | tail -1)"
if [[ -z "$TEMPLATE" ]]; then
  info "Downloading Debian ${DEBIAN_MAJOR} LXC template …"
  pveam update >/dev/null
  TEMPLATE_NAME="$(pveam available --section system | awk -v d="debian-${DEBIAN_MAJOR}-standard" '$2 ~ d {print $2}' | tail -1)"
  [[ -n "$TEMPLATE_NAME" ]] || { fail "No Debian ${DEBIAN_MAJOR} template found."; exit 1; }
  # Keep pveam output out of command substitution; this also avoids the
  # template-path bug seen in early PenguLab installers.
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_NAME"
  TEMPLATE="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE_NAME}"
fi
ok "Template ready: ${TEMPLATE}"

NET0="name=eth0,bridge=${BRIDGE},type=veth"
if [[ "$NETWORK_MODE" == "dhcp" ]]; then
  NET0+=",ip=dhcp"
else
  NET0+=",ip=${STATIC_IP},gw=${GATEWAY}"
fi
[[ -n "$VLAN_TAG" ]] && NET0+=",tag=${VLAN_TAG}"

info "Creating unprivileged LXC ${VMID} …"
pct create "$VMID" "$TEMPLATE" \
  --hostname "$CT_HOSTNAME" \
  --unprivileged 1 \
  --features nesting=1,keyctl=1 \
  --cores "$CORES" \
  --memory "$MEMORY" \
  --swap "$SWAP" \
  --rootfs "${STORAGE}:${DISK}" \
  --net0 "$NET0" \
  --onboot "$ONBOOT" \
  --start 1
CREATED=1
ok "LXC ${VMID} created."

info "Waiting for network inside the LXC …"
for _ in {1..30}; do
  if pct exec "$VMID" -- bash -lc 'ip route | grep -q default' >/dev/null 2>&1; then break; fi
  sleep 1
done
pct exec "$VMID" -- bash -lc 'ip route | grep -q default'

info "Installing Docker inside LXC ${VMID} …"
pct exec "$VMID" -- bash -lc '
  set -Eeuo pipefail
  export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8
  apt-get update
  # Debian 13 splits the Docker CLI into a recommended docker-cli package.
  # Keep package recommendations enabled here so Debian 12 and 13 both get
  # a complete Docker installation.
  apt-get install -y ca-certificates curl docker.io tar
  if ! command -v docker >/dev/null 2>&1; then
    apt-get install -y docker-cli
  fi
  if ! apt-get install -y docker-compose; then
    apt-get install -y docker-compose-v2
  fi
  systemctl enable --now docker
  command -v docker >/dev/null 2>&1
  docker --version
  if docker compose version >/dev/null 2>&1; then
    docker compose version
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose --version
  else
    echo "Docker Compose is not available after installation." >&2
    exit 1
  fi
'
ok "Docker is ready."

info "Copying PenguCost ${SOURCE_REF} into the LXC …"
pct push "$VMID" "$TMPDIR/pengucost-source.tar.gz" /root/pengucost-source.tar.gz
pct exec "$VMID" -- bash -lc '
  set -Eeuo pipefail
  rm -rf /opt/pengucost-src
  mkdir -p /opt/pengucost-src
  tar xzf /root/pengucost-source.tar.gz -C /opt/pengucost-src --strip-components=1
  rm -f /root/pengucost-source.tar.gz
'

SAFE_REF="$(printf '%s' "$SOURCE_REF" | tr -cs 'A-Za-z0-9_.-' '-')"
IMAGE="pengucost:${SAFE_REF}"

info "Building PenguCost ${SOURCE_REF} inside the LXC …"
pct exec "$VMID" -- bash -lc "cd /opt/pengucost-src && docker build -f backend/Dockerfile -t '${IMAGE}' ."

info "Starting PenguCost …"
cat > "$TMPDIR/compose.yml" <<YAML
services:
  pengucost:
    image: ${IMAGE}
    container_name: pengucost
    restart: unless-stopped
    ports:
      - '${APP_PORT}:8080'
    volumes:
      - pengucost_data:/data
    environment:
      - TZ=Europe/Berlin
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
volumes:
  pengucost_data:
YAML
pct exec "$VMID" -- bash -lc 'mkdir -p /opt/pengucost /var/backups/pengucost'
pct push "$VMID" "$TMPDIR/compose.yml" /opt/pengucost/compose.yml
pct exec "$VMID" -- bash -lc "printf '%s\\n' '${SOURCE_REF}' > /opt/pengucost/installed-version; cd /opt/pengucost; if docker compose version >/dev/null 2>&1; then docker compose up -d; else docker-compose up -d; fi"

# Small helper commands, similar to the PenguLab/PenguCoach LXC setup.
info "Installing PenguCost maintenance helpers …"
cat > "$TMPDIR/pengucost-status" <<'STATUS'
#!/usr/bin/env bash
set -Eeuo pipefail
REF=$(cat /opt/pengucost/installed-version 2>/dev/null || echo unknown)
echo "PenguCost: $REF"
docker ps --filter name=^pengucost$ --format 'Container: {{.Status}}'
if curl -fsS http://127.0.0.1:__PORT__/api/health >/dev/null; then
  echo 'Health: OK'
else
  echo 'Health: FAILED'
  exit 1
fi
STATUS
sed -i "s/__PORT__/${APP_PORT}/g" "$TMPDIR/pengucost-status"

cat > "$TMPDIR/pengucost-backup" <<'BACKUP'
#!/usr/bin/env bash
set -Eeuo pipefail
OUT="${1:-/var/backups/pengucost/pengucost-backup-$(date +%Y%m%d-%H%M%S).tar.gz}"
mkdir -p "$(dirname "$OUT")"
exec bash /opt/pengucost-src/scripts/backup.sh "$OUT"
BACKUP

cat > "$TMPDIR/pengucost-restore" <<'RESTORE'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 1 ]] || { echo 'Usage: pengucost-restore BACKUP.tar.gz' >&2; exit 1; }
exec bash /opt/pengucost-src/scripts/restore.sh "$1"
RESTORE

cat > "$TMPDIR/pengucost-update" <<'UPDATE'
#!/usr/bin/env bash
set -Eeuo pipefail
REPO='__REPO__'
PORT='__PORT__'
TARGET="${1:-main}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if [[ "$TARGET" == latest || "$TARGET" == stable ]]; then
  TARGET=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null | grep -m1 '"tag_name"' | cut -d '"' -f4 || true)
  if [[ -z "$TARGET" ]]; then
    TARGET=$(curl -fsSL "https://api.github.com/repos/${REPO}/tags?per_page=1" | grep -m1 '"name"' | cut -d '"' -f4 || true)
  fi
  [[ -n "$TARGET" ]] || { echo 'Could not resolve latest release/tag.' >&2; exit 1; }
  URL="https://github.com/${REPO}/archive/refs/tags/${TARGET}.tar.gz"
elif [[ "$TARGET" == main ]]; then
  URL="https://github.com/${REPO}/archive/refs/heads/main.tar.gz"
else
  URL="https://github.com/${REPO}/archive/refs/tags/${TARGET}.tar.gz"
fi

mkdir -p /var/backups/pengucost
BACKUP="/var/backups/pengucost/pengucost-preupdate-$(date +%Y%m%d-%H%M%S).tar.gz"
bash /opt/pengucost-src/scripts/backup.sh "$BACKUP"
echo "Backup: $BACKUP"

curl -fL --retry 2 "$URL" -o "$TMP/source.tar.gz"
mkdir -p "$TMP/source"
tar xzf "$TMP/source.tar.gz" -C "$TMP/source" --strip-components=1
SAFE=$(printf '%s' "$TARGET" | tr -cs 'A-Za-z0-9_.-' '-')
IMAGE="pengucost:${SAFE}"
OLD_IMAGE=$(awk '$1=="image:" {print $2; exit}' /opt/pengucost/compose.yml)

cd "$TMP/source"
docker build -f backend/Dockerfile -t "$IMAGE" .
sed -i "s#^[[:space:]]*image:.*#    image: ${IMAGE}#" /opt/pengucost/compose.yml
cd /opt/pengucost
if docker compose version >/dev/null 2>&1; then docker compose up -d; else docker-compose up -d; fi

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    rm -rf /opt/pengucost-src
    mv "$TMP/source" /opt/pengucost-src
    printf '%s\n' "$TARGET" > /opt/pengucost/installed-version
    echo "PenguCost updated to $TARGET"
    exit 0
  fi
  sleep 2
done

echo 'Health check failed after update; restoring previous image reference.' >&2
if [[ -n "$OLD_IMAGE" ]]; then
  sed -i "s#^[[:space:]]*image:.*#    image: ${OLD_IMAGE}#" /opt/pengucost/compose.yml
  cd /opt/pengucost
  if docker compose version >/dev/null 2>&1; then docker compose up -d; else docker-compose up -d; fi
fi
echo "Data backup kept at: $BACKUP" >&2
exit 1
UPDATE
sed -i "s#__REPO__#${REPO}#g; s#__PORT__#${APP_PORT}#g" "$TMPDIR/pengucost-update"

for helper in pengucost-status pengucost-backup pengucost-restore pengucost-update; do
  pct push "$VMID" "$TMPDIR/$helper" "/usr/local/sbin/$helper"
done
pct exec "$VMID" -- chmod 0755 \
  /usr/local/sbin/pengucost-status \
  /usr/local/sbin/pengucost-backup \
  /usr/local/sbin/pengucost-restore \
  /usr/local/sbin/pengucost-update

info "Running health check …"
for _ in {1..40}; do
  if pct exec "$VMID" -- curl -fsS "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null 2>&1; then
    SUCCESS=1
    break
  fi
  sleep 2
done
[[ "$SUCCESS" == "1" ]] || { fail "PenguCost did not pass its health check."; false; }

IP="$(pct exec "$VMID" -- hostname -I | awk '{print $1}')"
echo
ok "PenguCost installation completed."
printf '\n%bAccess%b\n' "$C_BOLD" "$C_RESET"
printf '  URL       : http://%s:%s\n' "$IP" "$APP_PORT"
printf '  LXC       : %s (%s)\n' "$VMID" "$CT_HOSTNAME"
printf '  Version   : %s\n' "$SOURCE_REF"
printf '\n%bManagement from the Proxmox host%b\n' "$C_BOLD" "$C_RESET"
printf '  Status    : pct exec %s -- /usr/local/sbin/pengucost-status\n' "$VMID"
printf '  Backup    : pct exec %s -- /usr/local/sbin/pengucost-backup\n' "$VMID"
printf '  Update    : pct exec %s -- /usr/local/sbin/pengucost-update main\n' "$VMID"
printf '  Stable    : pct exec %s -- /usr/local/sbin/pengucost-update stable\n' "$VMID"
printf '\n%bOffline%b\n' "$C_BOLD" "$C_RESET"
printf '  Normal PenguCost operation does not require Internet access.\n'
printf '  Internet is only required for updates and optional external AI endpoints.\n\n'
