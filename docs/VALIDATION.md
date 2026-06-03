# HyperGery v0.1.0 Validation

HyperGery v0.1.0 was validated on a real Ubuntu KVM/libvirt host.

## Preflight

The preflight verified:

- `/dev/kvm` exists and is accessible.
- User is in `kvm` and `libvirt` groups.
- `qemu-system-x86_64` is installed.
- `qemu-img` is installed.
- `virsh` is installed.
- `virt-viewer` is installed.
- `libvirtd` is active.
- `qemu:///system` is reachable.

## VM Creation

The acceptance flow created a real VM from an Ubuntu ISO:

- 2 vCPUs.
- 4096 MiB RAM.
- 40 GiB qcow2 disk.
- `default-lab` lab manifest.
- `hg-net-default-lab` libvirt network.

## Network

The libvirt network was created with:

- A HyperGery network name: `hg-net-default-lab`.
- A HyperGery bridge name: `hgbr...`.
- A non-default subnet, avoiding libvirt's common `192.168.122.0/24` default network.

## Console

The VM exposed a SPICE console through libvirt and opened successfully with `virt-viewer`.

## Snapshots

The validation created, listed, reverted, and deleted a real libvirt snapshot.

## Clone

The validation cloned a stopped VM to a new libvirt domain with an independent qcow2 disk. The clone was started successfully.

## Delete

The validation deleted test VMs and their HyperGery-managed disks. The libvirt `default` network was not modified.

## Repeating Validation

Run:

```bash
./scripts/preflight.sh
./scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso --name hg-acceptance-ubuntu-test
```
