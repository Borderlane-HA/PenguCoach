# First real Proxmox install

After the repository contents are pushed to `Borderlane-HA/PenguCoach` on the `main` branch, run on the **Proxmox VE host as root**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh)"
```

The installer will ask for CT ID, hostname, CPU, RAM, disk, bridge and storage, then create an unprivileged Debian 13 LXC and install PenguCoach natively.

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
