# HyperGery v0.7 Quick Start

HyperGery v0.7.0 is the Visual Refresh & UX Stabilization release
with Hub Transfer migrations. The big practical change versus v0.6: hosts no
longer need a shared NAS mount to migrate VMs — packages travel through the
Hub over HTTP.

## 1. Start HyperGery Hub on the NAS

The reference deployment runs the Hub in Container Station on the NAS, so one
`IP:port` serves coordination, DB, and temporary package staging:

```bash
# On the NAS (QNAP Container Station / docker compose):
cd /share/CACHEDEV2_DATA/Gerard/hypergery/hub
docker compose up -d
curl http://192.168.1.150:8765/health
```

Compose environment used by v0.7:

- `HYPERGERY_HUB_DB=/data/hypergery-hub.sqlite` (bind/volume off the share)
- `HYPERGERY_HUB_STAGING=/hypergery/staging` (temporary Hub Transfer packages)
- `HYPERGERY_NAS_ROOT=/hypergery`

Do not store SMB passwords, SSH keys, or tokens in the repo, `.env`, docs, or scripts.

## 2. Configure App Settings (mostly optional in v0.7)

The v0.7 app default Hub URL already points at the NAS Hub
(`http://192.168.1.150:8765`), so a fresh install works without configuration.
Open **Settings** to confirm — each field shows an ENV/CONFIG/DEFAULT source chip.

Override order: `HYPERGERY_HUB_URL` env > `~/.config/hypergery/config.json` > default.

A NAS staging path is only needed if you plan to use shared-NAS transfer mode.

## 3. Run Doctor / Diagnostics

UI: open the **Diagnostics** section and press **Run Doctor**.

CLI:

```bash
python -m hypergery_ubuntu.cli doctor
```

`doctor` does not install, delete, migrate, or modify VMs.

## 4. Start Agents

Easiest (per user, autostarts with your session, no sudo):

```bash
./scripts/install-agent-user-service.sh
# optional, for headless hosts:
#   sudo loginctl enable-linger $USER
```

Secondary host one-shot launcher (agent + app against the NAS Hub):

```bash
./scripts/start-second-host.sh
```

Manual:

```bash
python -m hypergery_ubuntu.cli agent run
```

Check from any host:

```bash
python -m hypergery_ubuntu.cli host list
```

## 5. Open the App

```bash
./scripts/dev-run.sh --no-install
```

v0.7 navigation: sidebar with Dashboard, Virtual Machines, Labs, Templates,
Remote Hosts, Migrations, Diagnostics, Settings. The top bar shows Hub/Host/NAS
status chips. **Remote Hosts** should show the Hub online and one card per
agent host.

## 6. Run a Hub Transfer Migration

UI: select a shut-off VM → **Live Migration** → pick the online target host →
Options already default to **Hub transfer** (no NAS path needed) → Run
Preflight → Start Migration. Progress auto-refreshes until `done`.

CLI:

```bash
python -m hypergery_ubuntu.cli migrate remote my-vm \
  --transfer hub \
  --source-host-id <source-host-id> \
  --target-host-id <target-host-id> \
  --target-vm-name my-vm-migrated
```

Expected:

- Status reaches `done` (watch it in the **Migrations** section).
- Target VM imported with new UUID and MAC; it can start.
- Source VM and source disks remain intact.
- The Hub staging copy is deleted after the import
  (`hub_package_deleted: true`).

Shared-NAS mode remains available with `--transfer nas --nas-path <path>` when
both hosts mount the same path.

## 7. Review History

The **Migrations** section lists every migration recorded on the Hub
(read-only): status, hosts, strategy, timestamps, and copyable ID/summary.

## 8. Cleanup

Clean only test resources you created:

```bash
python -m hypergery_ubuntu.cli delete-vm my-vm-migrated --delete-disks
```

Do not delete personal VMs. Migration history and packages are never deleted
by the UI.
