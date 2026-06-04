# NAS Live Migration

HyperGery v0.6.0 development uses the product label **Live Migration**, but the safe baseline implementation is NAS Clone Migration.

The source VM, source disks, source lab manifest, and source templates are not deleted or modified by migration packaging.

## Safety Model

- Running VMs are blocked by preflight.
- Paused VMs require an explicit `--allow-paused` option.
- Shut off VMs are the preferred source state.
- Missing VM disks are blocking errors.
- Missing attached ISO media blocks packaging when ISO inclusion is enabled; optional ISO packaging can be disabled with `--no-iso`.
- Package import generates a new domain UUID and new interface MAC addresses.
- Import rollback removes only target-side files/directories created during the failed import.

## Package Layout

```text
migrations/<migration_id>/
  manifest.json
  domain.xml
  disks/
  isos/
  snapshots/
  labs/lab.json
  templates/
    lab/*.json
    vm/*.json
  logs/migration.log
```

`manifest.json` includes:

- migration id and creation timestamp
- source VM name and target VM name
- `source_will_be_deleted: false`
- source VM state, lab id, RAM, vCPUs, network, and graphics
- disk, ISO, and snapshot assets with size and SHA-256 checksums
- lab metadata and referenced templates when available

## CLI Workflow

Run preflight:

```bash
python -m hypergery_ubuntu.cli migrate preflight hg-demo \
  --target-vm-name hg-demo-target \
  --nas-path /mnt/hypergery-nas
```

Create package:

```bash
python -m hypergery_ubuntu.cli migrate package hg-demo /mnt/hypergery-nas \
  --target-vm-name hg-demo-target
```

Validate package:

```bash
python -m hypergery_ubuntu.cli migrate validate-package /mnt/hypergery-nas/migrations/<migration_id>
```

Import on target host:

```bash
python -m hypergery_ubuntu.cli migrate import /mnt/hypergery-nas/migrations/<migration_id> \
  --target-vm-name hg-demo-target
```

List staged packages:

```bash
python -m hypergery_ubuntu.cli migrate list --path /mnt/hypergery-nas
```

## Not Implemented Yet

- Remote orchestration from the Qt UI.
- Target host capacity checks through the registry.
- Streaming progress from agent commands.
- True live RAM migration.
