# First real Proxmox install

After the repository contents are pushed to `Borderlane-HA/PenguCoach` on the `main` branch, run on the **Proxmox VE host as root**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh)"
```

The installer will ask for CT ID, hostname, CPU, RAM, disk, bridge and storage, then create an unprivileged Debian 13 LXC with `nesting=1` and install PenguCoach natively. It configures an UTF-8 locale before PostgreSQL is installed and creates the application database as UTF-8.

After installation, open the URL printed by the script and:

1. Create the first administrator.
2. Sign in and acknowledge the Development & Health Notice.
3. Configure Garmin Connect and complete MFA if Garmin requests it.
4. Configure the desired sync interval/history import.
5. Optionally configure Ollama/OpenAI/Anthropic in Admin > AI.

## Update

From the Proxmox host:

```bash
pct exec <CTID> -- pengucoach-update
```

Or inside the LXC:

```bash
pengucoach-update
```

## Status

```bash
pct exec <CTID> -- pengucoach-status
```

## Backup

```bash
pct exec <CTID> -- pengucoach-backup
```

## Useful logs

```bash
pct exec <CTID> -- journalctl -u pengucoach-api -n 200 --no-pager
pct exec <CTID> -- journalctl -u pengucoach-web -n 200 --no-pager
pct exec <CTID> -- journalctl -u pengucoach-worker -n 200 --no-pager
pct exec <CTID> -- journalctl -u pengucoach-scheduler -n 200 --no-pager
```

## Database encoding check / early-alpha repair

`pengucoach-status` shows the active database encoding. It should be `UTF8`. An early alpha installation that still reports `SQL_ASCII` can be repaired with:

```bash
pct exec <CTID> -- pengucoach-db-utf8
```

For the first update from `0.1.0-alpha.1`, if that helper is not present yet:

```bash
pct exec <CTID> -- bash /opt/pengucoach/install/proxmox/pengucoach-db-utf8.sh
```

The repair keeps both a dump and the old database until you remove them manually after validation.
