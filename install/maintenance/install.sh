#!/usr/bin/env bash
set -Eeuo pipefail
MODE="${1:-native}"
PROJECT="$(cd "${2:-/opt/pengucoach}" && pwd)"
[[ "$MODE" == native || "$MODE" == docker ]] || { echo 'Usage: install.sh native|docker /absolute/project/path'; exit 1; }
[[ -f "$PROJECT/pyproject.toml" ]] || { echo 'PenguCoach source not found'; exit 1; }
if [[ "$MODE" == docker ]]; then
  command -v docker >/dev/null
  docker compose version >/dev/null
  cd "$PROJECT"
  # Stop an existing helper only after acquiring its shared lock in a separate container.
  # This check happens before Compose can restart any application service.
  EXISTING_API="$(docker compose ps -a -q api 2>/dev/null || true)"
  if [[ -n "$EXISTING_API" ]]; then
    EXISTING_PROJECT="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$EXISTING_API")"
    EXISTING_NAME="pengucoach-maintenance-${EXISTING_PROJECT}"
    EXISTING_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$EXISTING_NAME" 2>/dev/null || true)"
    if [[ -n "$EXISTING_IMAGE" ]]; then
      docker run --rm --entrypoint python3 -v "${EXISTING_PROJECT}_maintenance_state:/state" \
        -v /var/run/docker.sock:/var/run/docker.sock "$EXISTING_IMAGE" -c '
import fcntl,subprocess,sys
with open("/state/operation.lock","a+") as lock:
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit("A maintenance operation is running. Try activation again after it finishes.")
    subprocess.run(["docker","stop",sys.argv[1]],check=True,timeout=180)
' "$EXISTING_NAME"
    fi
  fi
  # Creates the shared control-socket volume; app containers never receive docker.sock.
  docker compose up -d --build
  docker compose run --rm --no-deps maintenance-setup
  echo '[PenguCoach] Docker maintenance verified.'
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo 'Run as root inside the PenguCoach LXC.'; exit 1; }
BASE=/opt/pengucoach-maintenance
mkdir -p /var/lib/pengucoach-maintenance
exec 9>/var/lib/pengucoach-maintenance/operation.lock
flock -n 9 || { echo 'A maintenance operation is running. Retry after it finishes.'; exit 75; }
systemctl stop pengucoach-maintenance 2>/dev/null || true
mkdir -p "$BASE/program/pengucoach/maintenance" /var/lib/pengucoach-maintenance /run/pengucoach-maintenance
chmod 700 /var/lib/pengucoach-maintenance
chown root:pengucoach /run/pengucoach-maintenance
chmod 750 /run/pengucoach-maintenance
if [[ ! -x "$BASE/venv/bin/python" ]]; then
  python3 -m venv "$BASE/venv"
fi
# Retry incomplete environments after interrupted venv creation or dependency download.
if ! "$BASE/venv/bin/python" -c 'from cryptography.hazmat.primitives.ciphers.aead import AESGCM; from cryptography import __version__; assert 45 <= int(__version__.split(".")[0]) < 47' >/dev/null 2>&1; then
  "$BASE/venv/bin/python" -m ensurepip --upgrade
  "$BASE/venv/bin/python" -m pip install 'cryptography>=45,<47'
fi
install -m 0644 "$PROJECT"/pengucoach/maintenance/*.py "$BASE/program/pengucoach/maintenance/"
touch "$BASE/program/pengucoach/__init__.py"
python3 - "$PROJECT" <<'PY'
import grp,json,os,pathlib,sys
path=pathlib.Path('/etc/pengucoach-maintenance.json')
config=json.loads(path.read_text()) if path.exists() else {}
config.update(deployment='native',project=sys.argv[1],environment='/etc/pengucoach/pengucoach.env',data='/var/lib/pengucoach',state='/var/lib/pengucoach-maintenance',socket='/run/pengucoach-maintenance/control.sock',socket_gid=grp.getgrnam('pengucoach').gr_gid,user='pengucoach',repository='https://github.com/Borderlane-HA/PenguCoach.git',branch=pathlib.Path('/etc/pengucoach/channel').read_text().strip() if pathlib.Path('/etc/pengucoach/channel').exists() else 'main',program='/opt/pengucoach-maintenance/program/pengucoach/maintenance',restart_after_update=True)
path.write_text(json.dumps(config));os.chmod(path,0o600)
PY
cat > /etc/systemd/system/pengucoach-maintenance.service <<'UNIT'
[Unit]
Description=PenguCoach host maintenance
After=network-online.target postgresql.service redis-server.service
Wants=network-online.target
[Service]
Type=simple
User=root
WorkingDirectory=/opt/pengucoach-maintenance/program
ExecStart=/opt/pengucoach-maintenance/venv/bin/python -m pengucoach.maintenance.agent --config /etc/pengucoach-maintenance.json
Restart=always
RestartSec=2
UMask=0077
RuntimeDirectory=pengucoach-maintenance
RuntimeDirectoryMode=0750
Group=pengucoach
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /usr/local/bin/pengucoach-maintenance <<'CLI'
#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/pengucoach-maintenance/program
exec /opt/pengucoach-maintenance/venv/bin/python -m pengucoach.maintenance.cli "$@"
CLI
chmod 0755 /usr/local/bin/pengucoach-maintenance
ln -sf /usr/local/bin/pengucoach-maintenance /usr/bin/pengucoach-maintenance
flock -u 9
exec 9>&-
systemctl daemon-reload
systemctl enable pengucoach-maintenance
systemctl restart pengucoach-maintenance
# Existing shell entry points are preserved and delegate to the same engine.
for command in update backup; do
  install -m 0755 "$PROJECT/install/proxmox/pengucoach-$command.sh" "/usr/local/bin/pengucoach-$command"
done
echo '[PenguCoach] Native maintenance enabled. Shell commands remain available.'
