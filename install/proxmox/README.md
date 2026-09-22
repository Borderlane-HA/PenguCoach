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
2. creates an unprivileged LXC with `nesting=1` (required by Debian 13/systemd services such as Redis),
3. configures DHCP networking,
4. clones `Borderlane-HA/PenguCoach`,
5. configures `en_US.UTF-8` and installs PostgreSQL/Redis,
6. creates the PenguCoach database explicitly as UTF-8 and creates a Python virtual environment,
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
- `nesting=1`
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
pengucoach-db-utf8
```

From the Proxmox host:

```bash
pct exec <CTID> -- pengucoach-status
pct exec <CTID> -- pengucoach-update
pct exec <CTID> -- pengucoach-backup
pct exec <CTID> -- pengucoach-db-utf8
```


## Update behavior

`pengucoach-update` treats `/opt/pengucoach` as a deployment checkout, not as a development workspace. Before every update it creates a backup and then aligns the source tree directly with `origin/<channel>`. Local source edits are replaced automatically; there is no overwrite confirmation and no `Local source changes detected` abort.

Persistent runtime data is not stored in the Git checkout: PostgreSQL, FIT/Parquet data, uploaded user assets and `/etc/pengucoach/pengucoach.env` are preserved. This makes it safe to publish a release by replacing the repository files in GitHub and then run `pengucoach-update`.

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

## Upgrading an early alpha database

Early `0.1.0-alpha.1` Proxmox installs could create PostgreSQL with `SQL_ASCII` when the requested UTF-8 locale was missing. This can fail on Garmin JSON containing Unicode escapes. After updating the source, check with `pengucoach-status`. If the active database is not UTF-8, run:

```bash
pengucoach-db-utf8
```

If this is the first update from `0.1.0-alpha.1` and the helper has not yet been copied to `/usr/local/bin`, run the repository script directly once:

```bash
bash /opt/pengucoach/install/proxmox/pengucoach-db-utf8.sh
```

The repair command creates a PostgreSQL custom-format backup, restores into a new UTF-8 database, keeps the old SQL_ASCII database under a timestamped name, restarts PenguCoach, and performs an API health check. Do not delete the retained old database until the application and Garmin history have been verified.
