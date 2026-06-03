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

## Logs

Runtime logs are stored under:

```text
~/.local/state/hypergery/logs/hypergery.log
```
