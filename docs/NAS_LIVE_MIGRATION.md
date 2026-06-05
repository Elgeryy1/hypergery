# NAS Live Migration

HyperGery v0.6.0 uses the product label **Live Migration**, but the safe shipped implementation is NAS Clone Migration.

Final release status: local NAS Clone Migration E2E passed with two logical agents on one libvirt host, and a real two-physical-host NAS Clone Migration smoke passed with `hg-source` and `hg-target` through Hub `http://192.168.1.44:8765`.

The source VM, source disks, source lab manifest, and source templates are not deleted or modified by migration packaging.

HyperGery Hub coordinates the remote flow: the app reads hosts and inventory from the Hub, the source creates a package under `/mnt/hypergery-nas/hypergery/migrations`, the Hub queues `import_vm_package`, and the target agent imports and reports progress.

For the real NAS:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
export HYPERGERY_NAS_STAGING_PATH=/mnt/hypergery-nas/hypergery
```

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

Remote Hub/agent orchestration (shared NAS mode):

```bash
python -m hypergery_ubuntu.cli migrate remote hg-demo \
  --transfer nas \
  --nas-path /mnt/hypergery-nas \
  --source-host-id source-host \
  --target-host-id target-host \
  --target-vm-name hg-demo-target \
  --hub-url http://nas-or-hub-host:8765

python -m hypergery_ubuntu.cli migrate status \
  --migration-id <migration_id> \
  --hub-url http://nas-or-hub-host:8765
```

Remote flow (shared NAS mode):

1. Source runs preflight and records `preflight`.
2. Source exports package into NAS staging and records `packaging` then `uploaded`.
3. Hub creates `import_vm_package` for the target host and records `waiting_target`.
4. Target agent picks up the command and records `importing`.
5. Target import defines the VM, rewrites identity/media paths, and records `defining_vm` then `done`.
6. Any exception records `failed` with a clear error.

## Hub Transfer (v0.7)

Shared NAS mode requires every host to see the package at the **same absolute
path** (e.g. `/mnt/hypergery-nas` mounted everywhere). Hub Transfer removes
that requirement: the package travels through the Hub over HTTP, so hosts only
need the Hub URL.

```bash
python -m hypergery_ubuntu.cli migrate remote hg-demo \
  --transfer hub \
  --source-host-id source-host \
  --target-host-id target-host \
  --target-vm-name hg-demo-target \
  --hub-url http://nas-or-hub-host:8765
```

Hub Transfer flow:

1. Source runs preflight (`preflight`) against a local scratch directory
   (`<data_dir>/hub-transfer/outgoing`), no NAS path needed.
2. Source exports the package locally (`packaging`), uploads every file to the
   Hub staging area, deletes its local temporary copy, and records `uploaded`
   with `package_path = hub://<migration_id>`.
3. Hub queues `import_vm_package` with `transfer: hub` (`waiting_target`).
4. Target agent downloads the package from the Hub into
   `<data_dir>/hub-transfer/incoming/<migration_id>` and records `importing`.
5. Target validates checksums and imports as usual (`defining_vm`, `done`).
6. After a successful import the target deletes its downloaded copy **and the
   Hub staging copy** (`hub_package_deleted: true` in the result). The source
   VM and its disks are never touched in either mode.

Hub staging details:

- Staging endpoints: `PUT/GET /packages/<migration_id>/<relative_path>`,
  `GET /packages/<migration_id>` (listing), `DELETE /packages/<migration_id>`.
- Files stream in 1 MiB chunks in both directions; uploads require
  `Content-Length` and paths are validated against traversal.
- The staging directory defaults to `<db_dir>/staging` and can be overridden
  with `HYPERGERY_HUB_STAGING` (the Docker compose sets `/hypergery/staging`,
  which lands on the NAS storage).
- A failed migration may leave its package staged on the Hub for inspection;
  nothing deletes it automatically. Remove it manually with
  `DELETE /packages/<migration_id>` once diagnosed.

Choosing a mode:

- `--transfer hub` (wizard default): zero host requirements; data flows
  source → Hub → target.
- `--transfer nas`: one copy instead of upload+download when a fast shared
  mount already exists on both hosts.

## Agent Commands

The Hub can queue only allowlisted commands. For migration packages, the agent supports:

- `preflight` with `vm_name`: runs VM migration preflight and returns `done` only when the VM can be packaged safely.
- `receive_vm_package`: validates a staged package manifest and checksums.
- `import_vm_package`: imports a validated staged package on the target host.
- `migration_status`: reports whether a package is staged/valid/invalid.

`receive_vm_package`, `import_vm_package`, and package-based `migration_status` reject paths outside the configured `nas_staging_path` or its `migrations/` child.

## Qt UI

The first v0.6 UI entry point is the **Live Migration** VM action in the main toolbar. It opens a dialog that:

- sets target VM name and NAS staging path
- chooses whether to include ISO and snapshot file assets
- optionally allows paused VM packaging
- runs migration preflight
- enables package creation only after a successful preflight

The UI now includes a **Remote Hosts** panel and a **Live Migration** dialog. The dialog loads real target hosts from the Hub, blocks offline or KVM/libvirt-unready hosts, runs local preflight, creates the NAS package, queues the target import command, and records migration IDs for status polling.

## Not Implemented Yet

- True live RAM migration.
- HG-MEMDIFF or any custom dirty-page transfer protocol.
- AutoBoost.
- Android Hub.
- IsardVDI.
- SPICE integrated console.
- Streaming byte-level progress from agent commands.
