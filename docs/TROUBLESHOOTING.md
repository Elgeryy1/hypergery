# Troubleshooting

## First Run on a Fresh Ubuntu Laptop

Use the first-run launcher:

```bash
git clone https://github.com/Elgeryy1/hypergery.git
cd hypergery
./scripts/dev-run.sh
```

The script checks:

- `qemu-system-x86_64`, `qemu-img`, `virsh`, and a console viewer (`virt-viewer` or `remote-viewer`).
- `libvirtd` or modular `virtqemud` services.
- `/dev/kvm` existence and current-user access.
- `kvm` and `libvirt` group membership.
- `python3`, `python3-venv`, `python3-pip`.
- PySide6 and HyperGery inside `~/.venvs/hypergery`.

If anything is missing, the script prints a summary and asks before installing. It does not run sudo silently. `--install` skips the interactive question but sudo/pkexec can still ask for your password.

```bash
./scripts/dev-run.sh --check-only
./scripts/dev-run.sh --no-install
./scripts/dev-run.sh --install
```

The launcher always creates the venv at `~/.venvs/hypergery` with `--copies`; it does not create a local `.venv` inside the repository.

If the script adds you to `kvm` or `libvirt`, log out and back in before expecting `/dev/kvm` and `qemu:///system` access to work reliably.

## Virtualenv Fails on a NAS or Filesystem Without Symlinks

Some NAS mounts and shared filesystems do not handle Python virtualenv symlinks
reliably. Create the virtual environment on a local Linux filesystem and use
copies instead of symlinks:

```bash
python3 -m venv --copies ~/.venvs/hypergery
source ~/.venvs/hypergery/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./hypergery-ubuntu
```

If you are already inside `hypergery-ubuntu`, install the current directory:

```bash
python -m pip install -e .
```

## `qemu-kvm` Has No Installation Candidate

Some Ubuntu versions or derivatives package QEMU differently. Install the explicit packages:

```bash
sudo apt update
sudo apt install qemu-system-x86 qemu-utils
```

## `libvirtd` vs `virtqemud`

Ubuntu 22.04 commonly uses `libvirtd`. Some newer libvirt setups may use modular daemons such as `virtqemud`.

Try:

```bash
sudo systemctl enable --now libvirtd
```

If that service does not exist:

```bash
sudo systemctl enable --now virtqemud
```

## User Is Not in `kvm` or `libvirt`

Add the current user to both groups:

```bash
sudo usermod -aG kvm,libvirt "$USER"
```

Log out and back in before rerunning HyperGery.

If `/etc/group` already lists your user in `libvirt` but `id -nG` does not, the current login session has not inherited the new group yet. Log out completely and back in, or use a temporary subsession:

```bash
sg libvirt -c 'cd /path/to/hypergery && ./scripts/dev-run.sh --no-install'
```

## VM State Looks Wrong or Does Not Refresh

HyperGery v0.2.0 forces external commands to locale `C` and normalizes known localized libvirt states such as `ejecutando`. If state still looks wrong, compare:

```bash
virsh --connect qemu:///system list --all
cd hypergery-ubuntu
python -m hypergery_ubuntu.cli list-vms
```

Then press Refresh in the Qt UI.

## Conflict with `virbr0` or `192.168.122.0/24`

The libvirt `default` network commonly owns `virbr0` and `192.168.122.0/24`. HyperGery networks must not use `virbr0` or that default subnet.

HyperGery v0.1.0 detects stale HyperGery networks named `hg-net-*` with invalid bridge/IP settings, destroys them if active, undefines them, and recreates them. It does not touch the libvirt `default` network.

## ISO or Disk Permission Denied with `libvirt-qemu`

`qemu:///system` runs QEMU as a libvirt-managed user. That user needs execute permission through parent directories and read/write access to VM disks.

HyperGery attempts to apply minimal ACLs for `libvirt-qemu`. If permission issues remain, place ISOs in a libvirt-friendly location such as:

```bash
sudo mkdir -p /var/lib/libvirt/isos
sudo cp /path/to/installer.iso /var/lib/libvirt/isos/
sudo chown root:libvirt-qemu /var/lib/libvirt/isos/installer.iso
sudo chmod 0640 /var/lib/libvirt/isos/installer.iso
```

Then select that ISO in HyperGery.

## `virt-viewer` Is Not Installed

Install:

```bash
sudo apt install virt-viewer
```

HyperGery can also use `remote-viewer` when available.

## Console Fails When Running from a Snap-Based Editor

Some snap-based editor environments inject variables that can break native viewer tools. HyperGery sanitizes the viewer environment before launching `virt-viewer` or `remote-viewer`.

If this still fails, launch HyperGery from a normal terminal:

```bash
./scripts/dev-run.sh
```

## ACPI Shutdown Does Not Respond

Installer ISOs and early boot environments may ignore ACPI shutdown. Use Force Off for test VMs when ACPI does not complete within a reasonable timeout.

The acceptance script falls back to force off before testing snapshots on a stopped VM.

## Registry Is Not Reachable

Confirm the registry is running and the URL matches on every host:

```bash
python -m hypergery_ubuntu.cli registry health --registry-url http://nas-or-registry-host:8765
python -m hypergery_ubuntu.cli host list --registry-url http://nas-or-registry-host:8765
```

In the Qt app, the Remote Hosts panel uses `HYPERGERY_REGISTRY_URL` or `http://127.0.0.1:8765`.

## Target Host Is Offline or Blocked

The registry marks a host offline when its heartbeat is stale. Run the agent on the target host:

```bash
python -m hypergery_ubuntu.cli agent once
python -m hypergery_ubuntu.cli agent run
```

If KVM or libvirt shows blocked, rerun preflight on that target host:

```bash
python -m hypergery_ubuntu.cli preflight
```

Fix `/dev/kvm`, `libvirt` group membership, or libvirt service issues before starting migration.

## Target Agent Cannot Import Package

`import_vm_package` accepts only package paths inside the agent `nas_staging_path` or its `migrations/` child. Configure the same Linux NAS mount on source and target, for example `/mnt/hypergery-nas`, and do not use Windows paths.

```bash
python -m hypergery_ubuntu.cli agent config show
python -m hypergery_ubuntu.cli migrate validate-package /mnt/hypergery-nas/migrations/<migration_id>
```
