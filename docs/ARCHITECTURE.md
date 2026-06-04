# HyperGery Architecture

HyperGery is a real Ubuntu desktop VM manager built around a Python backend and a modern PySide6/Qt desktop UI. v0.3.0 adds a Lab Manager and a Templates Manager.

## UI

The primary desktop UI is implemented with PySide6/Qt in:

```text
hypergery_ubuntu/ui_qt/
```

It provides:

- A VM dashboard with state chips, host preflight, lab detail panel, VM detail tabs, and activity log.
- A multi-page VM creation wizard (Identity → Resources → Storage & Network → Review).
- VM lifecycle actions: start, ACPI shutdown, force off, console, snapshots, clone, settings, delete.
- **Lab Manager** (Instances tab): create, rename, delete, duplicate, export, import labs with real `LabStore`; VM filter by lab; lab detail panel showing network resources and `templates_used`.
- **Templates Manager** (Templates tab):
  - VM Templates sub-tab: create, delete, export, import VM templates; detail panel per selection.
  - Lab Templates sub-tab: create, delete, export, import lab templates; detail panel with planned VM count.
  - **Create VM from Template**: opens the VM wizard with OS type, RAM, vCPUs, disk, network, display pre-filled from the template; user provides VM name, boot ISO, and lab.
  - **Create Lab from Template** (v0.4.0 wizard): 3-page `InstantiateLabTemplateWizard` — Lab Identity with live preview, ISO Mapping table with per-VM Browse, Review summary. Calls `instantiate_lab_template()` in a background worker; handles rollback errors from partial failures.
  - **Edit VM/Lab Template**: `EditVmTemplateDialog` and improved `EditLabTemplateDialog` with `QTableWidget` (add/edit/remove planned VMs via `PlannedVmDialog`; double-click to edit).
  - **Lab Duplicate with VM Cloning**: `DuplicateLabDialog` enables clone checkbox when VMs exist; passes `clone_vm_callback` and `vm_state_callback` from the real backend.
  - **Lab Topology** (`topology.py`): `LabTopologyWidget` QPainter canvas; lab details panel has "Details" + "Topology" sub-tabs; click a VM node to select it in the VM list.
  - **Resource Overview**: `CleanupPreviewDialog` shows all VMs, labs, and templates — read-only.
- Qt backend workers so long-running host operations do not block the UI thread.

The old Tkinter UI remains temporarily available in:

```text
hypergery_ubuntu/app_tk.py
```

`app_tk.py` is legacy migration fallback only. It is not the primary UI from v0.2.0 onward.

## Backend

The backend is Python and wraps real host tools:

- `virsh` for libvirt domains, networks, state, snapshots, and console display URIs.
- `qemu-img` for qcow2 disk creation and disk information.
- `virt-viewer` or `remote-viewer` for real graphical consoles.

Commands are executed with argument lists, not shell-concatenated strings. External command output is forced to locale `C` where possible so VM states remain stable even on localized desktops.

## NAS Live Migration (v0.6.0 target)

v0.6.0 development is focused on NAS-backed migration between HyperGery hosts. The user-facing action is named **Live Migration**, but the safe baseline strategy is NAS Clone Migration: package the VM on the source host, stage the package on shared NAS storage, and import it on the target host while leaving the source VM untouched.

The migration architecture has four parts:

- **NAS Control Plane / Registry**: an HTTP API backed by SQLite local to the registry process. It stores host registrations, heartbeats, command queue state, and migration status. SQLite must not be used directly over SMB/NFS with multiple writers.
- **HyperGery Agent**: a local process on each host that registers with the registry, sends heartbeats, reports host capability, and executes only allowlisted migration commands.
- **NAS Migration Staging**: a shared path such as `/mnt/hypergery-nas/migrations` where VM migration packages are written. Packages are immutable once created; existing package directories are not overwritten.
- **VM Package Export/Import**: source-side packaging collects libvirt domain XML, qcow2 disks, optional attached ISO, lab/network/template metadata, checksums, and logs. Target-side import validates the package, regenerates UUID/MAC identity, copies disks into local HyperGery storage, defines the domain in libvirt, and updates lab metadata.

Running VM copy is not treated as safe by default. If HyperGery cannot use a real libvirt/QEMU-safe strategy, preflight blocks the migration with a clear error and asks for paused/offline packaging. The source VM, source disks, and source lab metadata are never deleted by v0.6.0 migration flows.

The registry command queue is not a shell execution mechanism. Supported command types are explicit and limited to safe operations such as `ping`, `preflight`, `list_vms`, `receive_vm_package`, `import_vm_package`, and `migration_status`.

The first migration implementation lives in `hypergery_ubuntu.migration` and is intentionally offline-first:

- `collect_vm_assets()` parses libvirt domain XML and records disk, ISO, and snapshot-related file assets.
- `migration_preflight()` blocks running VMs, checks missing media, staging path writability/free space, host preflight state, and target-name conflicts.
- `export_vm_package()` writes `migrations/<migration_id>/` with `manifest.json`, `domain.xml`, `disks/`, `isos/`, `snapshots/`, `labs/lab.json`, `templates/`, and `logs/migration.log`.
- `validate_vm_package()` verifies manifest schema, required package files, sizes, and SHA-256 checksums.
- `import_vm_package()` validates the package, generates a new VM UUID and MAC addresses, copies disks to `~/.local/share/hypergery/vms/<target-vm>/`, copies packaged ISOs to `~/.local/share/hypergery/isos/`, defines the libvirt domain, and updates lab metadata.

Import rollback removes only files/directories created during the failed import and undefines only the partially created target domain when present. It never removes source VM resources.

## Libvirt

HyperGery targets:

- `qemu:///system`
- KVM/QEMU domains
- libvirt networks
- SPICE or VNC graphics

HyperGery-owned libvirt networks use names like `hg-net-<lab-id>` and Linux bridges like `hgbr<hash>`. HyperGery does not manage the libvirt `default` network.

## Qt Workers

Backend actions run through Qt worker threads to keep the UI responsive. Workers avoid passing arbitrary Python objects through PySide signal payloads; results are stored on the worker object and read by the UI on completion. Completed workers are retained briefly to avoid premature Shiboken destruction crashes.

## Labs

Labs are represented by JSON manifests under:

```text
~/.local/share/hypergery/labs/<lab-id>/lab.json
```

v0.3 lab manifests use `schema_version: 2` and record:

- lab id
- name
- description
- created timestamp
- updated timestamp
- network id
- network mode
- subnet
- bridge name
- VMs
- templates used
- notes

Old manifests are loaded and migrated in place with missing fields filled.

## Templates

VM templates are stored under:

```text
~/.local/share/hypergery/templates/vm/
```

Lab templates are stored under:

```text
~/.local/share/hypergery/templates/lab/
```

Templates intentionally avoid private ISO paths by default. They describe reusable resources, display mode, network mode, and per-lab VM shape, leaving actual ISO/media choices to VM creation flows.

## Storage

Default VM disks are stored under:

```text
~/.local/share/hypergery/vms/<vm-name>/
```

Disks use qcow2. ISO files are referenced, not copied by default.

Migration imports may copy ISO media into local HyperGery ISO storage or register an internal package path, depending on import options. Source ISO files are never modified.

## Logs

Runtime logs are stored under:

```text
~/.local/state/hypergery/logs/hypergery.log
```
