# HyperGery

**A real Ubuntu desktop VM manager powered by KVM/QEMU/libvirt.**

![Version](https://img.shields.io/badge/version-v0.6.0--dev-blue)
![Platform](https://img.shields.io/badge/platform-Ubuntu-orange)
![Backend](https://img.shields.io/badge/backend-KVM%2FQEMU%2Flibvirt-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

HyperGery is a real desktop virtual machine manager for Ubuntu, functionally inspired by VirtualBox workflows but using KVM/QEMU/libvirt as its real backend through `virsh`, `qemu-img`, and `virt-viewer` or `remote-viewer`.

HyperGery v0.5.0 adds Lab Topology visualisation, an improved planned VM editor, ISO reuse in the instantiation wizard, a resource overview panel, and new CLI commands for template update and lab instantiation.

HyperGery v0.6.0 development is focused on NAS Live Migration: a NAS-backed control plane, host agents, host discovery, VM package export/import, migration preflight, and a UI action named **Live Migration**. The implementation is intentionally conservative: when a true live RAM/disk migration is not safe, HyperGery will perform or require a NAS Clone Migration strategy and keep the source VM untouched.

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

### Templates Manager (v0.3.0+)

- **VM Templates** describe reusable VM resource profiles (OS type, RAM, vCPUs, disk, network, display).
- **Lab Templates** describe reusable lab structures with a list of planned VMs.
- Create, delete, export, import, and **edit** templates via the Qt UI or CLI.
- **Create VM from Template**: opens the wizard with resource fields pre-filled; user chooses VM name, ISO, and lab.
- **Create Lab from Template** (v0.4.0): 3-page wizard — Lab Identity, ISO Mapping (per-VM ISO browse), and Review. Creates the lab and all planned VMs in a background worker with transactional rollback.
- Template IDs are normalized slugs: 3-64 lowercase alphanumeric characters with dashes.
- Templates stored at `~/.local/share/hypergery/templates/vm/` and `.../templates/lab/`.

### Lab Automation (v0.4.0)

- Planned VMs inside Lab Templates now carry `iso_required`, `role`, and `notes` fields.
- VM Template defaults are merged automatically when a planned VM references a `template_id`.
- `dry_run` mode validates the full instantiation plan without creating anything.
- Partial failure triggers automatic rollback of created VMs and the lab manifest.
- **Edit VM/Lab Template**: update any field in place without delete + re-create.
- **Add/Remove Planned VMs** from the Edit Lab Template dialog.
- **Duplicate Lab with VM Cloning**: Clone VMs checkbox enabled when VMs are present; clones qcow2 disks via `qemu-img convert`; requires all VMs shut off.

### Lab Topology (v0.5.0)

- **Visual topology tab** in the Lab Details panel: QPainter canvas showing the lab network node and VM nodes colour-coded by state.
- State colours: running = green, shut off = grey, paused = amber, not created = slate blue.
- VMs only in the lab manifest (not yet created in libvirt) shown as "not created".
- Click a VM node to select it in the main VM list.
- `build_lab_topology()` and `topology_to_json()` available for scripting.

### CLI (v0.5.0)

```bash
# Update template fields in place
python -m hypergery_ubuntu.cli template update vm ubuntu-base --set ram_mib=8192 --set notes="Updated"
python -m hypergery_ubuntu.cli template update lab asr-lab --set notes="v2"

# Print lab topology as JSON
python -m hypergery_ubuntu.cli lab-topology asr-lab

# Instantiate a lab template (dry-run or real)
python -m hypergery_ubuntu.cli lab-instantiate asr-lab "ASR Instance" \
  --iso server=/path/to/ubuntu.iso --iso client=/path/to/ubuntu.iso --dry-run
```

### Resource Overview (v0.5.0)

- **Resources…** button in the toolbar opens a read-only overview of all HyperGery-managed VMs, labs, VM templates, and lab templates.
- Nothing is deleted automatically — the dialog is a safe audit view.

### NAS Live Migration (v0.6.0 roadmap)

- NAS Control Plane registry for host discovery, command queueing, and migration status.
- HyperGery Agent on each participating host with safe command allowlist only.
- NAS staging directory for migration packages.
- VM package export/import for domain XML, qcow2 disks, attached ISO when requested, lab/network/template metadata, and migration logs.
- Migration preflight checks for source VM state, disk/ISO availability, staging path, target host health, target disk/RAM capacity, name conflicts, and running-VM safety.
- UI target: right-click a VM and choose **Live Migration**, then select target host, options, preflight, and progress.
- CLI target: registry, agent, host, and migrate commands.

v0.6.0 must not delete the source VM or original disks. Running VM copy is blocked unless HyperGery can use a real safe libvirt/QEMU strategy; otherwise users must choose paused/offline NAS Clone Migration.

### Not yet implemented

- True live RAM migration with custom dirty-page transfer.
- Lab topology zoom/pan and PNG/SVG export.
- VM role badges on topology nodes.
- Per-VM progress during lab instantiation.
- Android Hub, IsardVDI, P2P, GPU shadowing.

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
cd hypergery-ubuntu && python3 -m unittest discover -s tests
```

Full suite inside the venv (all 131 tests pass including Qt tests):

```bash
cd hypergery-ubuntu && ~/.venvs/hypergery/bin/python -m unittest discover -s tests
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

- v0.3.0 — Lab Manager + Templates Manager ✓
- v0.4.0 — Lab Automation (instantiation wizard, rollback, template editing, VM clone in duplicate) ✓
- v0.5.0 — Lab Topology view, planned VM editor, ISO reuse, resource overview, CLI update/instantiate ✓
- v0.6.0 — NAS Live Migration: registry, agents, host discovery, NAS staging, migration package export/import, UI action, CLI helpers
- v0.7.0 — topology export/polish, zoom/pan, role badges, additional UX refinement
- v1.0.0 — stable classroom-ready release

## License

MIT. See [LICENSE](LICENSE).
