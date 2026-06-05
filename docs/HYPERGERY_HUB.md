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

All endpoints return JSON. Unsupported commands and invalid payloads return JSON errors.

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

## Configuration

App and agent URL resolution:

1. `HYPERGERY_HUB_URL`
2. `HYPERGERY_REGISTRY_URL`
3. local config if present
4. `http://127.0.0.1:8765`

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
