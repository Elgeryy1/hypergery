# HyperGery Labs

HyperGery v0.3.0 starts turning the app into a laboratory manager instead of only a loose VM manager.

## Manifest Location

Lab manifests live at:

```text
~/.local/share/hypergery/labs/<lab-id>/lab.json
```

## Schema Version 2

```json
{
  "schema_version": 2,
  "lab_id": "security-lab",
  "name": "Security Lab",
  "description": "Training lab",
  "created_at": "2026-06-03T00:00:00+00:00",
  "updated_at": "2026-06-03T00:00:00+00:00",
  "network_id": "hg-net-security-lab",
  "network_mode": "nat",
  "subnet": "192.168.20.0/24",
  "bridge_name": "hgbr123abcd",
  "vms": [],
  "templates_used": [],
  "notes": ""
}
```

Legacy fields such as `disks` and `iso_references` may still exist for backward compatibility, but portable exports clear private disk and ISO paths.

## Lab ID Rules

Lab IDs are normalized from display names when needed:

- 3-48 characters.
- Lowercase letters, numbers, and dashes.
- No spaces.
- No path traversal.
- No leading dot.
- Reserved IDs such as `default`, `root`, `system`, and `libvirt` are rejected.

## Network Helpers

The backend provides deterministic helpers for:

- Libvirt network name: `hg-net-<lab-id>`.
- Linux bridge name: `hgbr<hash>`, always 15 characters or fewer and never `virbr0`.
- Subnet allocation avoiding `192.168.122.0/24` and collisions with existing labs.

## CLI

```bash
python -m hypergery_ubuntu.cli lab list
python -m hypergery_ubuntu.cli lab create "Security Lab" --description "Training"
python -m hypergery_ubuntu.cli lab show security-lab
python -m hypergery_ubuntu.cli lab rename security-lab blue-team-lab
python -m hypergery_ubuntu.cli lab export blue-team-lab /tmp/blue-team-lab.json
python -m hypergery_ubuntu.cli lab import /tmp/blue-team-lab.json --new-lab-id imported-lab
python -m hypergery_ubuntu.cli lab delete imported-lab
```

`delete_lab` does not delete VMs by default. VM deletion must be explicit and backed by real VM deletion logic.
