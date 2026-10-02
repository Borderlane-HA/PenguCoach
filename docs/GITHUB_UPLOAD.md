# Upload to GitHub and start the first Proxmox build

Target repository:

`https://github.com/Borderlane-HA/PenguCoach`

## Recommended upload method (Git CLI)

Extract the release ZIP somewhere on your PC. Then clone the existing repository and copy the extracted project contents into it:

```bash
git clone https://github.com/Borderlane-HA/PenguCoach.git
cd PenguCoach
```

Copy all files from the extracted `PenguCoach/` folder over this clone (do **not** copy another `.git` directory). Then:

```bash
git add .
git status
git commit -m "Initial PenguCoach alpha"
git push origin main
```

If you prefer the GitHub website, extract the ZIP first and upload the **contents of the `PenguCoach` directory**, not the ZIP file itself.

## Verify the installer is available

After the push, this URL must return the shell script:

```bash
curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh | head
```

## Create the LXC

Run on the Proxmox VE host as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/main/install/proxmox/pengucoach.sh)"
```

The host installer creates an unprivileged Debian 13 LXC and runs the in-container application installer.

## Update later

From the Proxmox host:

```bash
pct exec <CTID> -- pengucoach-update
```

Or enter the container:

```bash
pct enter <CTID>
pengucoach-update
```

## Status and logs

```bash
pct exec <CTID> -- pengucoach-status
pct exec <CTID> -- journalctl -u pengucoach-api -n 200 --no-pager
pct exec <CTID> -- journalctl -u pengucoach-web -n 200 --no-pager
pct exec <CTID> -- journalctl -u pengucoach-worker -n 200 --no-pager
```

## GitHub Actions

A push automatically starts `.github/workflows/ci.yml`. Check the repository's **Actions** tab. The workflow installs the real Python/npm dependencies, runs backend tests, builds the Next.js frontend, and validates the Proxmox shell scripts. Fix CI failures before treating the build as stable.

## Incremental web-update packages

For an existing installation, `github-web-update` ZIPs contain only changed/new repository files, directly at the archive root. Extract and upload those files into the root of the existing GitHub repository. The full release ZIP instead contains a `PenguCoach/` directory. Retired connector files are harmless compatibility stubs so an incremental web upload does not require deleting files. Run the normal updater after uploading, and restart every worker/scheduler along with the API and web app.

## Alpha.46.1 → Alpha.47 web update

The delta ZIP contains only new/changed repository files. Extract it and upload
**every included directory**, especially `apps`, `pengucoach`, `db`, `docs` and
`tests`, plus the included root files. Preserve the directory hierarchy. Uploading
only frontend files leaves the new API and migration unavailable.

Run the normal deployment update after committing all files. Alpha.47 includes
Alembic migration `0014_plan_evolution`. See [PLAN_EVOLUTION.md](PLAN_EVOLUTION.md)
for feature entry points and Docker update commands.
