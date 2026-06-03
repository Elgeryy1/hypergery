# HyperGery v0.1 for Ubuntu

HyperGery is a first real desktop VM manager for Ubuntu using KVM/QEMU/libvirt. It is not a VirtualBox frontend and does not use mock VM data. The app calls `virsh`, `qemu-img`, and `virt-viewer`/`remote-viewer` to create, define, start, stop, snapshot, view, clone, and delete real libvirt domains.

## Target

- Ubuntu 22.04 LTS and Ubuntu 24.04 LTS
- KVM/QEMU/libvirt backend through `qemu:///system`
- Desktop UI implemented with Python/Tkinter to avoid PyPI/network bootstrap requirements
- VM disks default to `~/.local/share/hypergery/vms/<vm-name>/`
- Lab manifests live in `~/.local/share/hypergery/labs/<lab-id>/lab.json`
- Logs live in `~/.local/state/hypergery/logs/hypergery.log`

## Install Dependencies

Run:

```bash
./scripts/install-ubuntu-deps.sh
./scripts/install-desktop-launcher.sh
```

Manual equivalent:

```bash
sudo apt update
sudo apt install qemu-kvm qemu-system-x86 libvirt-daemon-system libvirt-clients virt-viewer qemu-utils ovmf python3-tk
sudo systemctl enable --now libvirtd
sudo usermod -aG kvm,libvirt "$USER"
```

Log out and back in after changing groups. Confirm:

```bash
test -e /dev/kvm
virsh --connect qemu:///system list --all
qemu-img --version
virt-viewer --version
```

## Run

```bash
./scripts/dev-run.sh
```

Or launch `HyperGery` from the Ubuntu application menu after running:

```bash
./scripts/install-desktop-launcher.sh
```

Or directly:

```bash
cd hypergery-ubuntu
python3 -m hypergery_ubuntu
```

Run preflight without opening the UI:

```bash
./scripts/preflight.sh
```

Run the real-host acceptance flow from an ISO:

```bash
./scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso --name hg-acceptance-ubuntu-test
```

This script uses the same backend as the UI. It creates a real 2 vCPU, 4096 MiB RAM, 40 GiB qcow2 VM, starts it, opens the real console, exercises snapshots, requests ACPI shutdown, and asks before deleting the VM disk.

Use the CLI directly:

```bash
cd hypergery-ubuntu
python3 -m hypergery_ubuntu.cli preflight
python3 -m hypergery_ubuntu.cli create-vm --name hg-acceptance-ubuntu-test --iso /path/to/ubuntu.iso --ram-mib 4096 --vcpus 2 --disk-gb 40
python3 -m hypergery_ubuntu.cli list-vms
python3 -m hypergery_ubuntu.cli start hg-acceptance-ubuntu-test
python3 -m hypergery_ubuntu.cli wait-state hg-acceptance-ubuntu-test running --timeout 90
python3 -m hypergery_ubuntu.cli open-console hg-acceptance-ubuntu-test
python3 -m hypergery_ubuntu.cli shutdown hg-acceptance-ubuntu-test
python3 -m hypergery_ubuntu.cli wait-state hg-acceptance-ubuntu-test "shut off" --timeout 180
python3 -m hypergery_ubuntu.cli snapshot create hg-acceptance-ubuntu-test before-install
python3 -m hypergery_ubuntu.cli snapshot revert hg-acceptance-ubuntu-test before-install
python3 -m hypergery_ubuntu.cli snapshot delete hg-acceptance-ubuntu-test before-install
python3 -m hypergery_ubuntu.cli delete-vm hg-acceptance-ubuntu-test --delete-disks
```

## Create a VM from an ISO

1. Open HyperGery.
2. Check the preflight panel. Errors include suggested install/fix commands.
3. Click `New`.
4. Select a real ISO, for example Ubuntu Server or Debian netinst.
5. Set `2` vCPUs, `4096` MiB RAM, and `40` GiB disk.
6. Use `nat` networking and Lab ID `default-lab`, or use another lab id to create a separate lab manifest/network.
7. Click `Create`.
8. Select the VM, click `Start`, then `Open Console`.
9. Use the real installer shown by `virt-viewer`.

HyperGery creates a real qcow2 disk with `qemu-img`, creates/starts a real lab libvirt network named like `hg-net-default-lab`, defines a real libvirt domain, and logs the operations.

## Real Host Validation Checklist

After creating a VM named `hg-acceptance-ubuntu-test`, these commands should show the real backend state:

```bash
virsh --connect qemu:///system domstate hg-acceptance-ubuntu-test
virsh --connect qemu:///system dumpxml hg-acceptance-ubuntu-test
virsh --connect qemu:///system net-info hg-net-default-lab
qemu-img info "$HOME/.local/share/hypergery/vms/hg-acceptance-ubuntu-test/hg-acceptance-ubuntu-test.qcow2"
cat "$HOME/.local/share/hypergery/labs/default-lab/lab.json"
tail -n 100 "$HOME/.local/state/hypergery/logs/hypergery.log"
```

HyperGery's own validation helper can print the same VM state from the app backend:

```bash
cd hypergery-ubuntu
python3 -m hypergery_ubuntu.cli validate-vm hg-acceptance-ubuntu-test
```

Snapshot validation:

```bash
virsh --connect qemu:///system snapshot-list --domain hg-acceptance-ubuntu-test
```

Console validation:

```bash
virt-viewer --connect qemu:///system hg-acceptance-ubuntu-test
```

If any command fails, HyperGery should show the same underlying libvirt or tool error in the UI instead of simulating success.

Run the guided acceptance flow on a real Ubuntu KVM host:

```bash
./scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso --name hg-acceptance-ubuntu-test
```

## Main Features

- System preflight for `/dev/kvm`, libvirt daemon, `qemu-system-x86_64`, `qemu-img`, `virsh`, and console viewer tools.
- VM creation from a local ISO with RAM, vCPU, qcow2 disk size/path, OS type, Lab ID, display mode, and NAT or isolated lab network.
- VM listing from real libvirt state.
- Start, ACPI shutdown, force off, delete with disk confirmation.
- Real graphical console through `virt-viewer` or `remote-viewer`.
- Storage details from `qemu-img info` when available.
- Lab manifest JSON with VM, disk, ISO, network, notes, and creation metadata.
- Real libvirt snapshots: create, list, revert, delete.
- Settings dialog for stopped VMs: RAM, vCPUs, boot ISO, network, and SPICE/VNC display mode.
- Clone stopped VMs by copying qcow2 disk and defining a new libvirt domain.
- Activity log panel backed by `~/.local/state/hypergery/logs/hypergery.log`.

## Common Fixes

Permission denied for KVM/libvirt:

```bash
sudo usermod -aG kvm,libvirt "$USER"
```

Then log out and back in.

`libvirtd` not running:

```bash
sudo systemctl enable --now libvirtd
```

No VM console opens:

```bash
sudo apt install virt-viewer
```

`virsh` cannot connect to `qemu:///system`:

```bash
systemctl status libvirtd
groups
virsh --connect qemu:///system list --all
```

## Notes

HyperGery v0.1 intentionally does not implement Android Hub, NAS, IsardVDI, live migration, GPU shadowing, P2P, or users/RBAC. This version stays focused on a basic real Ubuntu/KVM desktop VM manager.
