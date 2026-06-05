# HyperGery Hub

HyperGery Hub is the v0.6.0 NAS control-plane service. It exposes an HTTP JSON API on port `8765` and coordinates hosts, agents, command queues, VM inventory, migration status, and basic events.

Current validation status: v0.6.0 final validation passed. Docker Hub, Hub/Agent smoke, UI smoke, local NAS Clone Migration E2E, and a real two-physical-host NAS Clone Migration smoke passed. The final automated check ran 214 tests OK in the Qt/offscreen venv and 214 tests OK with 15 skipped on system Python.

The existing `registry` module remains as the compatible implementation name. User-facing commands can use `hub`:

```bash
python -m hypergery_ubuntu.cli hub serve --host 0.0.0.0 --port 8765
python -m hypergery_ubuntu.cli hub health --hub-url http://192.168.1.150:8765
python -m hypergery_ubuntu.cli hub init-db
python -m hypergery_ubuntu.cli hub vms
python -m hypergery_ubuntu.cli hub vms ubuntu-hyperv
```

Compatibility aliases remain:

```bash
python -m hypergery_ubuntu.cli registry serve
python -m hypergery_ubuntu.cli registry health
```

## API

- `GET /health`
- `POST /hosts/register`
- `POST /hosts/heartbeat`
- `GET /hosts`
- `GET /hosts/{host_id}`
- `POST /vms/report`
- `GET /vms`
- `GET /vms/{host_id}`
- `POST /commands`
- `GET /commands/{host_id}`
- `GET /commands/id/{command_id}`
- `POST /commands/{command_id}/result`
- `POST /migrations`
- `GET /migrations`
- `GET /migrations/{migration_id}`
- `POST /migrations/{migration_id}/status`
- `GET /events`
- `POST /events`

Package staging (v0.7, Hub Transfer):

- `PUT /packages/{migration_id}/{relative_path}` — upload one package file (streamed, requires `Content-Length`)
- `GET /packages/{migration_id}` — list staged files with sizes
- `GET /packages/{migration_id}/{relative_path}` — download one file (streamed)
- `DELETE /packages/{migration_id}` — remove a staged package (whole package only)

All endpoints return JSON except package file downloads (`application/octet-stream`). Unsupported commands and invalid payloads return JSON errors. Package paths are validated against directory traversal.

### Command allowlist

`POST /commands` only accepts an explicit allowlist of command types; anything
else is rejected by the Hub **and** re-validated by the target agent:

- `ping`, `preflight`, `list_vms` — diagnostics and inventory.
- `receive_vm_package`, `import_vm_package`, `migration_status` — migrations.
- `vm_start`, `vm_shutdown`, `vm_force_off` — remote VM power control (v0.8).

Remote power commands require `payload.vm_name` and flow App → Hub → target
Agent → libvirt; the agent checks that the VM exists locally, is
HyperGery-managed, and that its current state allows the action, then returns
a structured result (`previous_state`, `new_state`, `message`) recorded on the
command. The agent re-reports its inventory right after acting so the UI sees
the new state quickly.

Intentionally **not** remote-controllable: VM delete, undefine, disk deletion,
XML edits, console access, and arbitrary shell commands. `vm_reboot`/`vm_reset`
is not offered yet (no safe backend method). Limitations: the target agent must
be online, libvirt must be healthy on the target host, actions depend on the
VM's current state, and Force Off can corrupt guest data (the UI always asks
for confirmation).

## Data Model

The Hub stores metadata and state in SQLite. The DB must live in the container-local persistent volume, not directly on a shared SMB/NFS path with multiple writers.

Tables:

- `hosts`
- `host_vms`
- `commands`
- `migrations`
- `events`

NAS storage is only for migration packages, disks, and ISO assets. In Docker the NAS root is mounted at `/hypergery`, with migration packages under `/hypergery/migrations`.

The Docker deployment persists `/data` in the Docker volume `hypergery-hub-data` so SQLite does not live on the NAS share.

### Hub Transfer staging (v0.7)

For `--transfer hub` migrations the Hub temporarily stores packages in a
staging directory:

- Default: `<db_dir>/staging`; override with `HYPERGERY_HUB_STAGING` or
  `hub serve --staging-dir`.
- The Docker compose sets `HYPERGERY_HUB_STAGING=/hypergery/staging` so large
  packages land on NAS storage, not in the container layer.
- Staged packages are **temporary by design**: after a successful target
  import the target agent deletes the staged copy (`hub_package_deleted: true`
  in the migration result). Failed migrations keep their staged package for
  inspection; clean up manually with `DELETE /packages/{migration_id}`.

### Running the Hub on the NAS (Container Station)

The reference deployment runs the Hub in Docker on the NAS itself, so a single
`IP:port` serves DB, coordination, and staging storage. Hosts only need
`HYPERGERY_HUB_URL=http://<nas-ip>:8765` (the v0.7 app default already points
at the NAS Hub). DB and staging live on NAS disks via bind mounts; nothing is
stored on the participating hosts.

## Configuration

App and agent URL resolution:

1. `HYPERGERY_HUB_URL`
2. `HYPERGERY_REGISTRY_URL`
3. local config if present
4. `http://192.168.1.150:8765` (v0.7 default: the Hub on the NAS)

For the NAS:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
```

Agent example:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
export HYPERGERY_HOST_ID=ubuntu-hyperv
export HYPERGERY_HOST_NAME="Ubuntu Hyper-V"
export HYPERGERY_NAS_STAGING_PATH=/mnt/hypergery-nas/hypergery
python -m hypergery_ubuntu.cli agent run
```

Saved app settings live at:

```bash
~/.config/hypergery/config.json
```

Environment variables have priority over saved settings. The compatible `HYPERGERY_REGISTRY_URL` fallback remains available for older scripts.

Run non-destructive diagnostics:

```bash
python -m hypergery_ubuntu.cli doctor
```

No passwords, SSH keys, SMB credentials, or other secrets are stored by the Hub.

## Not Included

- True live RAM migration.
- HG-MEMDIFF or any custom dirty-page transfer protocol.
- AutoBoost.
- Android Hub.
- IsardVDI.
- SPICE integrated console.
