# PenguCoach on Proxmox VE

PenguCoach uses a **native unprivileged LXC** deployment. Docker is not required inside the container.

## 1. Upload the repository to GitHub

The repository root must contain files such as `pyproject.toml`, `apps/`, `pengucoach/` and `install/`. Do not upload the ZIP as one file; extract it and upload/commit its contents to `Borderlane-HA/PenguCoach`.

## 2. Create the LXC

Run on the Proxmox VE host as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh)"
```

The script:

1. downloads a Debian 13 template if needed,
2. creates an unprivileged LXC,
3. configures DHCP networking,
4. clones `Borderlane-HA/PenguCoach`,
5. installs PostgreSQL and Redis,
6. creates a Python virtual environment,
7. generates JWT and encryption secrets,
8. applies Alembic migrations,
9. builds the Next.js frontend,
10. creates API/worker/scheduler/web systemd units,
11. configures Nginx,
12. performs `/healthz` verification.

## Default sizing

- 4 vCPU
- 4096 MB RAM
- 512 MB swap
- 32 GB root disk
- unprivileged LXC
- `onboot=1`

A larger FIT history can later be mounted below `/var/lib/pengucoach`.

## First login

Open `http://<LXC-IP>/` and create the first administrator. Then sign in and confirm the Development & Health Notice. Garmin can then be connected from **Garmin** in the top navigation; MFA is supported.

## Commands

Inside the LXC:

```bash
pengucoach-status
pengucoach-update
pengucoach-backup
```

From the Proxmox host:

```bash
pct exec <CTID> -- pengucoach-status
pct exec <CTID> -- pengucoach-update
pct exec <CTID> -- pengucoach-backup
```

## Logs

```bash
pct exec <CTID> -- journalctl -u pengucoach-api -f
pct exec <CTID> -- journalctl -u pengucoach-worker -f
pct exec <CTID> -- journalctl -u pengucoach-scheduler -f
pct exec <CTID> -- journalctl -u pengucoach-web -f
```

## Branch/update channel

The initial installer follows `main`. The selected branch is stored in `/etc/pengucoach/channel`. To test a different branch before installation:

```bash
PENGUCOACH_BRANCH=develop bash -c "$(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh)"
```

## Reverse proxy

PenguCoach serves HTTP on port 80 inside the LXC. An external Nginx Proxy Manager, NPMPlus, Traefik or another reverse proxy can terminate HTTPS. After HTTPS is configured, set `PENGUCOACH_COOKIE_SECURE=true` in `/etc/pengucoach/pengucoach.env` and restart the API.
