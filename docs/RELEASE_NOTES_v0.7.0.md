# HyperGery v0.7.0 — Visual Refresh & Hub Transfer

HyperGery v0.7.0 modernizes the entire desktop experience and removes the
biggest operational requirement for VM migrations: hosts no longer need a
shared NAS mount — packages now travel through the Hub.

## Highlights

- **Modern UI refresh**: new app shell with sidebar navigation and status top
  bar, dashboard health cards, remote host cards, tabbed Settings with
  ENV/CONFIG/DEFAULT source chips, Diagnostics (doctor) panel, and a polished
  VM view and console window — all on a consistent dark design system.
- **Hub Transfer migrations**: `--transfer hub` uploads the migration package
  through the Hub and the target downloads it. The temporary Hub copy is
  deleted after a successful import. No shared mount, no identical paths.
- **NAS-hosted Hub**: the reference deployment runs the Hub in Docker on the
  NAS; the app's default Hub URL points at it, so fresh installs work with
  zero configuration.
- **Migrations history**: a read-only Migrations page listing every migration
  recorded on the Hub, with status colors and copyable ID/summary.
- **Remote VM inventory**: "View VMs" on a remote host card shows that host's
  VMs (read-only) as reported by its agent.
- **Agent service installer**: `scripts/install-agent-user-service.sh` sets up
  the agent as a systemd --user service (no sudo, no stored credentials).

## What changed

### UI
- App shell: sidebar (Dashboard, Virtual Machines, Labs, Templates, Remote
  Hosts, Migrations, Diagnostics, Settings) + top bar with Hub/Host/NAS chips.
- Dashboard health cards, warnings, and last-migration summary.
- Remote Hosts: hub status card, per-host capability cards, host test action,
  read-only remote VM inventory dialog.
- Settings: sectioned dialog with config-source chips; honest "planned for
  v0.8" callouts for not-yet-implemented sections.
- Diagnostics: doctor checks grouped by area, run in a background worker,
  copyable report.
- NAS Clone Migration wizard: 6 steps (Select VM, Target Host, Options,
  Preflight, Progress, Result) with progress states and automatic status
  polling.
- VM view: header with counters, 7-column table with state chips, Console
  status card (Host Key: Right Ctrl).
- Console window: grouped toolbar, status bar with display type/resolution,
  clear disconnected/powered-off/SPICE states. Closing the console never
  stops the VM.
- Migrations history page (read-only; never deletes records or packages).

### Hub / Agent
- Hub package staging endpoints: `PUT/GET /packages/<id>/<path>`,
  `GET /packages/<id>` (listing), `DELETE /packages/<id>` — streamed in 1 MiB
  chunks with path-traversal protection. Staging dir configurable via
  `HYPERGERY_HUB_STAGING` (Docker: `/hypergery/staging`).
- Agent `import_vm_package` supports `transfer: hub`: download from the Hub,
  validate checksums, import, then delete the local temp copy and the Hub
  staging copy.

### Migration
- New `--transfer hub|nas` flag on `migrate remote`; the UI wizard defaults to
  Hub Transfer and no longer requires a NAS path in that mode.
- Source VM and source disks remain untouched in both modes; target import
  regenerates UUID and MAC and refuses existing target VM names.

### Operations
- Default `hub_url` points at the NAS Hub; `HYPERGERY_HUB_URL` and
  `~/.config/hypergery/config.json` still override it.
- `scripts/start-second-host.sh`: one-command agent + app launcher for a
  secondary host.
- `scripts/install-agent-user-service.sh`: systemd --user unit installer with
  `--hub-url` and `--uninstall`; optional `loginctl enable-linger` hint for
  headless hosts.

### Docs / tests
- New `docs/QUICK_START_V07.md`; Hub Transfer documented in
  `docs/NAS_LIVE_MIGRATION.md` and `docs/HYPERGERY_HUB.md`; new
  troubleshooting sections for Hub Transfer failures.
- Test suite grew to 249 tests (Qt offscreen + system Python), including hub
  staging roundtrip, hub-transfer migration flow, agent download/cleanup,
  wizard transfer mode, migrations history, and script static checks.

## Validation

- Full test suite green: 249 OK (venv Qt/offscreen) and 249 OK on system
  Python (Qt tests skipped cleanly), `compileall`, `bash -n` on all scripts,
  `docker compose config`.
- Real two-host Hub Transfer E2E migrations passed on physical hardware:
  - small disk migration → done
  - migration including a 2.8 GiB ISO → done
  - migration with a ~5.8 GiB VM disk → done, target started after import
- In every run: source VM untouched, target imported with regenerated
  UUID/MAC, Hub staging copy deleted after import, target temp directory
  cleaned.

## Not included

- True live RAM migration, HG-MEMDIFF, or any dirty-page transfer protocol.
- AutoBoost, Android Hub, IsardVDI, P2P transfer.
- Remote VM power control or remote console (remote inventory is read-only).
- SPICE integrated console (external viewer fallback remains).
- Lab-specific visual workspace and advanced Settings sections (planned v0.8).

## Upgrade notes

- The default Hub URL changed from `http://127.0.0.1:8765` to the NAS Hub
  (`http://192.168.1.150:8765`). `HYPERGERY_HUB_URL` and the saved config
  still override the default.
- Use `scripts/install-agent-user-service.sh` to start the agent
  automatically per user session.
- Use `--transfer hub` (or simply the wizard default) for migrations without
  a shared mount; `--transfer nas --nas-path <path>` remains available as the
  shared-NAS fallback.
- A failed Hub Transfer migration keeps its staged package on the Hub for
  inspection; remove it with `DELETE /packages/<migration_id>` once diagnosed.
