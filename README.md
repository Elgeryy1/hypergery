# HyperGery

**A real Ubuntu desktop VM manager powered by KVM/QEMU/libvirt.**

![Version](https://img.shields.io/badge/version-v0.3.0--dev-blue)
![Platform](https://img.shields.io/badge/platform-Ubuntu-orange)
![Backend](https://img.shields.io/badge/backend-KVM%2FQEMU%2Flibvirt-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

HyperGery is a real desktop virtual machine manager for Ubuntu, functionally inspired by VirtualBox workflows but using KVM/QEMU/libvirt as its real backend through `virsh`, `qemu-img`, and `virt-viewer` or `remote-viewer`.

HyperGery v0.3.0 extends the modern PySide6/Qt desktop UI with Lab Manager and Templates Manager, turning the app into a reusable laboratory environment manager.

## Screenshots

![HyperGery v0.2.0 PySide6 dashboard](docs/screenshots/hypergery-v0.2-main.png)

## Features

### VM Management (v0.1.0+)

- Real KVM/QEMU/libvirt backend via `virsh` and `qemu-img`.
- VM creation from a local ISO with qcow2 disks.
- NAT and isolated libvirt networks per lab.
- SPICE/VNC console through `virt-viewer` or `remote-viewer`.
- Start, ACPI shutdown, and force off.
- Snapshots: create, list, revert, delete.
- Clone stopped VMs.
- Safe delete with disk confirmation.
- Preflight checks for KVM, libvirt, QEMU tools, viewer tools, and user groups.

### Lab Manager (v0.3.0)

- Labs are isolated virtual environments with their own libvirt network, bridge, and subnet.
- Create, rename, delete, duplicate, export, and import labs via the Qt UI or CLI.
- Each lab gets a deterministic `hg-net-<lab-id>` network and `hgbr<hash>` bridge.
- Subnets are allocated without collisions against existing labs and `192.168.122.0/24`.
- VM list can be filtered by lab (All VMs / Selected Lab).
- Lab manifests are JSON files at `~/.local/share/hypergery/labs/<lab-id>/lab.json`.
- `templates_used` field tracks which templates contributed to the lab.

### Templates Manager (v0.3.0)

- **VM Templates** describe reusable VM resource profiles (OS type, RAM, vCPUs, disk, network, display).
- **Lab Templates** describe reusable lab structures with a list of planned VMs.
- Create, delete, export, and import templates via the Qt UI or CLI.
- **Create VM from Template**: opens the wizard with resource fields pre-filled; user chooses VM name, ISO, and lab.
- **Create Lab from Template**: creates a lab with name, description, and network mode from the template; planned VMs are listed but not created automatically yet.
- Template IDs are normalized slugs: 3-64 lowercase alphanumeric characters with dashes.
- Templates stored at `~/.local/share/hypergery/templates/vm/` and `.../templates/lab/`.

### Not yet implemented

- Auto-create planned VMs from a lab template (requires per-VM ISO selection).
- Edit templates in place (workaround: delete + re-create).
- Clone VM disks during lab duplicate.
- Android Hub, NAS, IsardVDI, P2P, live migration, GPU shadowing.

## Requirements

Target platforms:

- Ubuntu 22.04 LTS
- Ubuntu 24.04 LTS
- Compatible Ubuntu-based systems with KVM/QEMU/libvirt

Required system packages:

```bash
sudo apt install qemu-system-x86 qemu-utils \
  libvirt-daemon-system libvirt-clients \
  libvirt-daemon-driver-qemu libvirt-daemon-config-network \
  virt-viewer ovmf dnsmasq-base \
  python3-pip python3-venv python3-dev python3-tk \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0
```

Python dependency: `PySide6` (installed in the virtualenv, see below).

The current user must belong to the `kvm` and `libvirt` groups.

## Installation

Install system dependencies:

```bash
./scripts/install-ubuntu-deps.sh
sudo systemctl enable --now libvirtd
sudo usermod -aG kvm,libvirt "$USER"
# Log out and back in after changing groups
```

Install HyperGery. If the repository lives on a local filesystem:

```bash
cd hypergery-ubuntu && python3 -m pip install -e .
```

Recommended setup when on a NAS or filesystem without reliable symlink support:

```bash
python3 -m venv --copies ~/.venvs/hypergery
source ~/.venvs/hypergery/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./hypergery-ubuntu
```

Optional desktop launcher:

```bash
./scripts/install-desktop-launcher.sh
```

## Run

Run preflight:

```bash
./scripts/preflight.sh
```

Run the Qt desktop app:

```bash
source ~/.venvs/hypergery/bin/activate
./scripts/dev-run.sh
# or: python -m hypergery_ubuntu
```

Run the CLI:

```bash
python3 -m hypergery_ubuntu.cli preflight
python3 -m hypergery_ubuntu.cli lab list
python3 -m hypergery_ubuntu.cli template list vm
python3 -m hypergery_ubuntu.cli create-vm --name my-vm --iso /path/to/ubuntu.iso \
  --ram-mib 4096 --vcpus 2 --disk-gb 40
```

Run the acceptance script with a real ISO:

```bash
./scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso --name hg-acceptance-ubuntu-test
```

## Tests

System Python (no PySide6 — Qt tests are skipped cleanly):

```bash
python3 -m unittest discover -s hypergery-ubuntu/tests
```

Full suite inside the venv (all 101 tests pass including Qt tests):

```bash
/home/gerard/.venvs/hypergery/bin/python -m unittest discover -s hypergery-ubuntu/tests
```

## Safety

HyperGery runtime data is kept outside the repository:

- VM disks: `~/.local/share/hypergery/vms/`
- Lab manifests: `~/.local/share/hypergery/labs/`
- VM templates: `~/.local/share/hypergery/templates/vm/`
- Lab templates: `~/.local/share/hypergery/templates/lab/`
- Logs: `~/.local/state/hypergery/logs/`

The repository `.gitignore` excludes ISOs, virtual disks, logs, local runtime folders, `.env` files, credentials, keys, and certificates. Do not commit private ISOs, VM disks, credentials, or student data.

## Roadmap

- v0.3.0 — Lab Manager + Templates Manager (current develop branch, RC)
- v0.4.0 — auto-create VMs from lab template, edit templates, clone VM disks in lab duplicate
- v0.5.0 — NAS commit prototype
- v1.0.0 — stable classroom-ready release

## License

MIT. See [LICENSE](LICENSE).
