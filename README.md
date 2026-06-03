# HyperGery

**A real Ubuntu desktop VM manager powered by KVM/QEMU/libvirt.**

![Version](https://img.shields.io/badge/version-v0.2.0--dev-blue)
![Platform](https://img.shields.io/badge/platform-Ubuntu-orange)
![Backend](https://img.shields.io/badge/backend-KVM%2FQEMU%2Flibvirt-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

HyperGery is a first real version of a desktop virtual machine manager for Ubuntu. It is functionally inspired by VirtualBox workflows, but it is not a VirtualBox frontend: HyperGery uses KVM/QEMU/libvirt as its real backend through `virsh`, `qemu-img`, and `virt-viewer` or `remote-viewer`.

HyperGery v0.2.0 uses a modern PySide6/Qt desktop UI as the primary interface while keeping the real KVM/QEMU/libvirt backend from v0.1.0. The legacy Tkinter UI remains temporarily available in `hypergery_ubuntu.app_tk` as a migration fallback.

## Screenshots

![HyperGery v0.2.0 PySide6 dashboard](docs/screenshots/hypergery-v0.2-main.png)

## Features

- Real KVM/QEMU/libvirt backend.
- VM creation from ISO.
- qcow2 disk creation.
- NAT and isolated lab networks.
- SPICE/VNC console through `virt-viewer` or `remote-viewer`.
- Start, ACPI shutdown, and force off.
- Snapshots: create, list, revert, delete.
- Clone stopped VMs.
- Safe delete with disk confirmation.
- Preflight checks for KVM, libvirt, QEMU tools, viewer tools, and user groups.
- Logs and lab manifests.

## What Works in v0.1.0

HyperGery v0.1.0 was validated on a real Ubuntu host with the acceptance script. The validation covered:

- Real preflight against `/dev/kvm`, libvirt, QEMU tools, and viewer tools.
- Real VM creation from an Ubuntu ISO.
- Real qcow2 disk creation.
- Real libvirt network creation for `hg-net-default-lab` with a HyperGery-owned bridge.
- Real SPICE console opened with `virt-viewer`.
- Real snapshots: create, list, revert, delete.
- Real clone of a stopped VM with an independent qcow2 disk.
- Safe delete of managed test VMs and disks.

## Not Included Yet

- Android Hub is not included yet.
- NAS sync is not included yet.
- IsardVDI integration is not included yet.
- P2P/offload is not included yet.
- Live migration is not included yet.
- GPU shadowing is not included yet.

## Requirements

Target platforms:

- Ubuntu 22.04 LTS.
- Ubuntu 24.04 LTS.
- Compatible Ubuntu-based systems with KVM/QEMU/libvirt.

Required packages:

- `qemu-system-x86`
- `qemu-utils`
- `libvirt-daemon-system`
- `libvirt-clients`
- `libvirt-daemon-driver-qemu`
- `libvirt-daemon-config-network`
- `virt-viewer`
- `ovmf`
- `python3-tk`
- `python3-pip`
- `python3-venv`
- `python3-dev`
- `dnsmasq-base`
- `libxcb-cursor0`
- `libxcb-icccm4`
- `libxcb-image0`
- `libxcb-keysyms1`
- `libxcb-render-util0`
- `libxkbcommon-x11-0`

Python package dependencies:

- `PySide6`

The current user must be able to access KVM and libvirt, normally through the `kvm` and `libvirt` groups.

## Installation

Install dependencies:

```bash
./scripts/install-ubuntu-deps.sh
```

Install Python dependencies for the Qt UI. If the repository is stored on a normal local Linux filesystem:

```bash
cd hypergery-ubuntu
python3 -m pip install -e .
```

Recommended setup when the repository is stored on a NAS or on a filesystem that does not support Python virtualenv symlinks reliably:

```bash
python3 -m venv --copies ~/.venvs/hypergery
source ~/.venvs/hypergery/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./hypergery-ubuntu
```

Then run HyperGery from the activated environment:

```bash
python -m hypergery_ubuntu
```

Manual equivalent:

```bash
sudo apt update
sudo apt install qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients libvirt-daemon-driver-qemu libvirt-daemon-config-network virt-viewer ovmf dnsmasq-base python3-pip python3-venv python3-dev python3-tk libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0
sudo systemctl enable --now libvirtd
sudo usermod -aG kvm,libvirt "$USER"
```

Log out and back in after changing groups.

Optional desktop launcher:

```bash
./scripts/install-desktop-launcher.sh
```

## Run

Run preflight:

```bash
./scripts/preflight.sh
```

Run the desktop app:

```bash
./scripts/dev-run.sh
```

Or directly:

```bash
cd hypergery-ubuntu
python3 -m hypergery_ubuntu
```

The default desktop UI on `develop` is the PySide6/Qt interface. The previous Tkinter UI is kept temporarily in `hypergery_ubuntu.app_tk` during migration.

If PySide6 is installed in a virtualenv, activate it before running:

```bash
source ~/.venvs/hypergery/bin/activate
./scripts/dev-run.sh
```

Run the acceptance flow with a real ISO:

```bash
./scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso --name hg-acceptance-ubuntu-test
```

Use the CLI directly:

```bash
cd hypergery-ubuntu
python3 -m hypergery_ubuntu.cli preflight
python3 -m hypergery_ubuntu.cli create-vm --name hg-acceptance-ubuntu-test --iso /path/to/ubuntu.iso --ram-mib 4096 --vcpus 2 --disk-gb 40
python3 -m hypergery_ubuntu.cli start hg-acceptance-ubuntu-test
python3 -m hypergery_ubuntu.cli open-console hg-acceptance-ubuntu-test
python3 -m hypergery_ubuntu.cli snapshot create hg-acceptance-ubuntu-test before-install
python3 -m hypergery_ubuntu.cli delete-vm hg-acceptance-ubuntu-test --delete-disks
```

## Safety

HyperGery runtime data is kept outside the repository. By default:

- VM disks are created under `~/.local/share/hypergery/vms/`.
- Lab manifests are stored under `~/.local/share/hypergery/labs/`.
- Logs are stored under `~/.local/state/hypergery/logs/`.

The repository `.gitignore` excludes ISOs, virtual disks, logs, local runtime folders, `.env` files, credentials, keys, certificates, and common secret file patterns. Do not commit private ISOs, VM disks, credentials, or customer/student data.

## Roadmap

- v0.2.0 UI/UX upgrade.
- v0.3.0 lab templates.
- v0.4.0 stronger snapshot/lab workflows.
- v0.5.0 NAS commit prototype.
- v1.0.0 stable classroom-ready release.

## License

MIT. See [LICENSE](LICENSE).
