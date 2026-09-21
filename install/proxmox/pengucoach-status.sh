#!/usr/bin/env bash
set -u
printf '%-28s %s\n' "PenguCoach API" "$(systemctl is-active pengucoach-api 2>/dev/null)"
printf '%-28s %s\n' "PenguCoach Web" "$(systemctl is-active pengucoach-web 2>/dev/null)"
printf '%-28s %s\n' "PenguCoach Worker" "$(systemctl is-active pengucoach-worker 2>/dev/null)"
printf '%-28s %s\n' "PenguCoach Scheduler" "$(systemctl is-active pengucoach-scheduler 2>/dev/null)"
printf '%-28s %s\n' "PostgreSQL" "$(systemctl is-active postgresql 2>/dev/null)"
printf '%-28s %s\n' "Redis" "$(systemctl is-active redis-server 2>/dev/null)"
printf '%-28s %s\n' "Nginx" "$(systemctl is-active nginx 2>/dev/null)"
echo
curl -fsS http://127.0.0.1/healthz 2>/dev/null || true
echo

echo "Database encoding:"
runuser -u postgres -- psql -d postgres -Atqc "SELECT datname || ' = ' || pg_encoding_to_char(encoding) FROM pg_database WHERE datname='pengucoach';" 2>/dev/null || true
