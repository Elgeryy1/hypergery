# HyperGery Architecture

HyperGery is a real Ubuntu desktop VM manager built around a Python backend and a modern PySide6/Qt desktop UI. v0.3.0 development adds the backend foundation for Labs & Templates.

## UI

The primary desktop UI is implemented with PySide6/Qt in:

```text
hypergery_ubuntu/ui_qt/
```

It provides:

- A VM dashboard with state chips, host preflight, lab summary, details, and logs.
- A multi-page VM creation wizard.
- VM lifecycle actions: start, ACPI shutdown, force off, console, snapshots, clone, settings, and delete.
- Qt backend workers so long-running host operations do not block the UI thread.

The old Tkinter UI remains temporarily available in:

```text
hypergery_ubuntu/app_tk.py
```

`app_tk.py` is legacy migration fallback only. It is not the v0.2.0 primary UI.

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
