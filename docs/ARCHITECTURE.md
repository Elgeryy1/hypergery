# HyperGery Architecture

HyperGery v0.1.0 is intentionally small and direct.

## UI

The desktop UI is implemented with Python Tkinter. It provides:

- Toolbar actions similar to common desktop VM managers.
- A VM list.
- VM detail tabs.
- Preflight status.
- Activity logs.

## Backend

The backend is Python and wraps real host tools:

- `virsh` for libvirt domains, networks, state, snapshots, and console display URIs.
- `qemu-img` for qcow2 disk creation and disk information.
- `virt-viewer` or `remote-viewer` for real graphical consoles.

Commands are executed with argument lists, not shell-concatenated strings.

## Libvirt

HyperGery targets:

- `qemu:///system`
- KVM/QEMU domains
- libvirt networks
- SPICE or VNC graphics

HyperGery-owned libvirt networks use names like `hg-net-<lab-id>` and Linux bridges like `hgbr<hash>`. HyperGery does not manage the libvirt `default` network.

## Labs

Labs are represented by JSON manifests under:

```text
~/.local/share/hypergery/labs/<lab-id>/lab.json
```

Each manifest records:

- lab id
- name
- created timestamp
- network id
- VMs
- disks
- ISO references
- notes

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
