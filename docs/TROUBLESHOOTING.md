# Troubleshooting

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
