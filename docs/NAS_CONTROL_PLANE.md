# NAS Control Plane

HyperGery v0.6.0 uses HyperGery Hub plus host agents for NAS Live Migration orchestration. The existing `registry` module and CLI remain as compatibility aliases.

Docker/QNAP deployment is documented in [HYPERGERY_HUB.md](HYPERGERY_HUB.md) and [NAS_DEPLOYMENT.md](NAS_DEPLOYMENT.md).

## Components

- Hub/Registry: HTTP service backed by SQLite. It stores host heartbeats, VM inventory, safe commands, migration status, and events.
- Agent: runs on each participating Linux host. It heartbeats capabilities and executes only allowlisted commands.
- NAS staging path: shared path mounted at the same logical Linux path on source and target hosts, for example `/mnt/hypergery-nas`.

## Start

```bash
python -m hypergery_ubuntu.cli hub serve --host 0.0.0.0 --port 8765
python -m hypergery_ubuntu.cli agent config show
python -m hypergery_ubuntu.cli agent run
```

Agent config is JSON and must not contain passwords:

```json
{
  "registry_url": "http://nas-or-hub-host:8765",
  "host_id": "ubuntu-laptop-1",
  "name": "Ubuntu Laptop 1",
  "nas_staging_path": "/mnt/hypergery-nas",
  "heartbeat_interval_seconds": 15
}
```

## Host Commands

```bash
python -m hypergery_ubuntu.cli host list --registry-url http://nas-or-registry-host:8765
python -m hypergery_ubuntu.cli host show ubuntu-laptop-1 --registry-url http://nas-or-registry-host:8765
python -m hypergery_ubuntu.cli host test ubuntu-laptop-1 --registry-url http://nas-or-registry-host:8765
```

`host test` queues a safe `ping` command. The target agent marks it `running` then `done` on its next cycle.

Preferred Hub URL form:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
python -m hypergery_ubuntu.cli host list
python -m hypergery_ubuntu.cli hub vms
```

## Allowed Agent Commands

- `ping`
- `preflight`
- `list_vms`
- `receive_vm_package`
- `import_vm_package`
- `migration_status`

Package commands reject paths outside the configured NAS staging path or its `migrations/` child.
