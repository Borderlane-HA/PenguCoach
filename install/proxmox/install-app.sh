#!/usr/bin/env bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
# Debian always provides C.UTF-8. Use it from the first apt invocation so a
# brand-new minimal LXC never inherits an unavailable host locale.
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
APP_DIR=/opt/pengucoach
ENV_DIR=/etc/pengucoach
DATA_DIR=/var/lib/pengucoach
APP_USER=pengucoach

info(){ echo "[PenguCoach] $*"; }
die(){ echo "[PenguCoach] ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Run as root"
[[ -f "$APP_DIR/pyproject.toml" ]] || { echo "Repository missing at $APP_DIR" >&2; exit 1; }

info "Preparing UTF-8 locale"
apt-get update -qq
apt-get install -y -qq ca-certificates curl
# C.UTF-8 is present even in the minimal Debian 13 template and is sufficient
# for PostgreSQL UTF-8 databases as well as Python/Node processes.
locale charmap | grep -qi 'UTF-8' || die "No UTF-8 locale available in the container"

info "Installing system packages"
apt-get install -y -qq \
  python3 python3-venv python3-dev build-essential libpq-dev \
  postgresql postgresql-contrib redis-server nginx \
  nodejs npm git unzip jq openssl

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if (( NODE_MAJOR < 20 )); then
  info "Installing Node.js 22 from NodeSource"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi

id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$ENV_DIR" "$DATA_DIR"/{fit,parquet,backups,exports}
chown -R "$APP_USER:$APP_USER" "$DATA_DIR" "$APP_DIR"
chmod 750 "$DATA_DIR" "$ENV_DIR"

# Install helper commands early as well as after the final build. This keeps
# recovery/status tools available even if a later installation step aborts.
info "Installing helper commands"
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-update.sh" /usr/local/bin/pengucoach-update
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-backup.sh" /usr/local/bin/pengucoach-backup
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-status.sh" /usr/local/bin/pengucoach-status
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-db-utf8.sh" /usr/local/bin/pengucoach-db-utf8
for cmd in pengucoach-update pengucoach-backup pengucoach-status pengucoach-db-utf8; do
  ln -sf "/usr/local/bin/$cmd" "/usr/bin/$cmd"
done

info "Configuring PostgreSQL"
systemctl enable --now postgresql >/dev/null
DB_PASS="$(openssl rand -hex 24)"
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='pengucoach'" | grep -q 1; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE pengucoach LOGIN PASSWORD '$DB_PASS';"
else
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER ROLE pengucoach WITH PASSWORD '$DB_PASS';"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='pengucoach'" | grep -q 1; then
  runuser -u postgres -- createdb \
    --owner=pengucoach \
    --encoding=UTF8 \
    --locale=C.UTF-8 \
    --template=template0 \
    pengucoach
fi
DB_ENCODING="$(runuser -u postgres -- psql -d postgres -Atqc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='pengucoach'")"
if [[ "$DB_ENCODING" != "UTF8" ]]; then
  die "Database 'pengucoach' uses $DB_ENCODING instead of UTF8. Run $APP_DIR/install/proxmox/pengucoach-db-utf8.sh before continuing."
fi

info "Configuring Redis"
systemctl enable --now redis-server >/dev/null

info "Creating Python virtual environment"
python3 - <<'PYVER'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(f"PenguCoach requires Python >=3.12, found {sys.version.split()[0]}")
PYVER
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel >/dev/null
.venv/bin/pip install .

JWT_SECRET="$(openssl rand -hex 48)"
FERNET_KEY="$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
APP_VERSION="$(.venv/bin/python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
cat > "$ENV_DIR/pengucoach.env" <<ENV
PENGUCOACH_ENV=production
PENGUCOACH_APP_VERSION=${APP_VERSION}
PENGUCOACH_DATABASE_URL=postgresql+asyncpg://pengucoach:${DB_PASS}@127.0.0.1:5432/pengucoach
PENGUCOACH_REDIS_URL=redis://127.0.0.1:6379/0
PENGUCOACH_JWT_SECRET=${JWT_SECRET}
PENGUCOACH_ENCRYPTION_KEY=${FERNET_KEY}
PENGUCOACH_SESSION_DAYS=30
PENGUCOACH_FRONTEND_ORIGIN=http://localhost
PENGUCOACH_COOKIE_SECURE=false
PENGUCOACH_DATA_DIR=${DATA_DIR}
PENGUCOACH_GARMIN_DEFAULT_INTERVAL_MINUTES=30
PENGUCOACH_GARMIN_RATE_LIMIT_COOLDOWN_MINUTES=30
PENGUCOACH_AI_REQUEST_TIMEOUT_SECONDS=300
PENGUCOACH_LOG_LEVEL=INFO
ENV
chown root:"$APP_USER" "$ENV_DIR/pengucoach.env"
chmod 640 "$ENV_DIR/pengucoach.env"
echo "${PENGUCOACH_BRANCH:-main}" > "$ENV_DIR/channel"

info "Preparing database schema"
set -a
# shellcheck disable=SC1090
. "$ENV_DIR/pengucoach.env"
set +a
cd "$APP_DIR"

# A fresh database has no PenguCoach application tables. Bootstrap the current
# reviewed schema directly, then stamp Alembic at head. Existing installations
# keep using the normal migration chain. A stale alembic_version left by an
# interrupted first install is intentionally ignored when there are no app tables.
APP_TABLE_COUNT="$(runuser -u postgres -- psql -d pengucoach -Atqc "
SELECT count(*)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename <> 'alembic_version';
")"

if [[ "${APP_TABLE_COUNT:-0}" == "0" ]]; then
  info "Fresh database detected; creating current schema"
  .venv/bin/python install/proxmox/bootstrap-db.py
  .venv/bin/alembic -c alembic.ini stamp head
else
  info "Existing database detected; applying Alembic migrations"
  .venv/bin/alembic -c alembic.ini upgrade head
fi

info "Verifying database schema"
.venv/bin/python - <<'PYSCHEMA'
import asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from pengucoach.common.config import settings

REQUIRED_TABLES = {
    "users", "activities", "ai_runs", "garmin_connections",
    "source_records", "daily_health", "sleep_sessions", "hrv_daily",
}

async def verify():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            def check(sync_conn):
                inspector = inspect(sync_conn)
                tables = set(inspector.get_table_names())
                missing = sorted(REQUIRED_TABLES - tables)
                if missing:
                    raise RuntimeError(f"Missing required database tables: {', '.join(missing)}")
                activity_columns = {c["name"] for c in inspector.get_columns("activities")}
                if "vo2max" not in activity_columns:
                    raise RuntimeError("Database schema is missing activities.vo2max")
            await conn.run_sync(check)
    finally:
        await engine.dispose()

asyncio.run(verify())
PYSCHEMA

info "Building web application"
cd "$APP_DIR/apps/web"
npm install --no-audit --no-fund
NEXT_PUBLIC_API_BASE_URL=/api/v1 npm run build
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

info "Creating systemd services"
cat > /etc/systemd/system/pengucoach-api.service <<UNIT
[Unit]
Description=PenguCoach API
After=network-online.target postgresql.service redis-server.service
Wants=network-online.target
[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_DIR/pengucoach.env
ExecStart=$APP_DIR/.venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/pengucoach-worker.service <<UNIT
[Unit]
Description=PenguCoach Worker
After=network-online.target postgresql.service redis-server.service
[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_DIR/pengucoach.env
ExecStart=$APP_DIR/.venv/bin/celery -A worker.celery_app:app worker -l INFO -Q garmin,fit,maintenance --concurrency=2
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/pengucoach-scheduler.service <<UNIT
[Unit]
Description=PenguCoach Scheduler
After=network-online.target redis-server.service
[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_DIR/pengucoach.env
ExecStart=$APP_DIR/.venv/bin/celery -A worker.celery_app:app beat -l INFO --schedule=$DATA_DIR/celerybeat-schedule
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/pengucoach-web.service <<UNIT
[Unit]
Description=PenguCoach Web
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/apps/web
Environment=NODE_ENV=production
ExecStart=/usr/bin/npm start -- --hostname 127.0.0.1 --port 3000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/nginx/sites-available/pengucoach <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 20m;

    location /api/ {
        proxy_connect_timeout 30s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /healthz {
        proxy_pass http://127.0.0.1:8000/health;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/pengucoach /etc/nginx/sites-enabled/pengucoach
nginx -t

install -m 0755 "$APP_DIR/install/proxmox/pengucoach-update.sh" /usr/local/bin/pengucoach-update
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-backup.sh" /usr/local/bin/pengucoach-backup
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-status.sh" /usr/local/bin/pengucoach-status
install -m 0755 "$APP_DIR/install/proxmox/pengucoach-db-utf8.sh" /usr/local/bin/pengucoach-db-utf8
for cmd in pengucoach-update pengucoach-backup pengucoach-status pengucoach-db-utf8; do
  ln -sf "/usr/local/bin/$cmd" "/usr/bin/$cmd"
done

systemctl daemon-reload
systemctl enable --now pengucoach-api pengucoach-worker pengucoach-scheduler pengucoach-web nginx >/dev/null
# nginx is often already running because the package starts it during install.
# Explicitly reload after writing the PenguCoach site so /healthz uses the new config.
nginx -t
systemctl reload nginx
sleep 3
curl -fsS http://127.0.0.1/healthz >/dev/null || { journalctl -u pengucoach-api -n 80 --no-pager; exit 1; }
info "PenguCoach services are healthy"
