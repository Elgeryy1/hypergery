# Troubleshooting

## Hub Not Reachable

If Remote Hosts or Live Migration shows `Hub not reachable`, start the Docker service or point the app/agent at the NAS Hub:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
curl http://192.168.1.150:8765/health
```

On the NAS:

```bash
cd /share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/docker
docker compose up -d
docker compose logs -f
```

Do not put passwords, SSH keys, or SMB credentials in `.env`.

## Docker Container Unhealthy

Check the Hub container health and logs:

```bash
cd /share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/docker
docker compose ps
docker inspect --format '{{.State.Health.Status}}' hypergery-hub
docker compose logs --tail=100
curl http://127.0.0.1:8765/health
```

If the healthcheck fails, confirm port `8765` is not already occupied and rebuild the image:

```bash
docker compose config
docker compose build
docker compose up -d --force-recreate
```

Do not run `docker compose down -v` unless you intentionally want to remove the Hub DB volume.

## SQLite DB Locked or Corrupted

The Hub SQLite DB must live in Docker volume `hypergery-hub-data`, not on the NAS/SMB share. If logs show `sqlite3.OperationalError: database is locked`, confirm Compose maps `/data` to a Docker volume:

```bash
cd docker
docker compose config | grep -A4 /data
```

Expected: `/data` is a volume. The NAS bind mount should appear only as `/hypergery`.

If the old `docker/data/hypergery-hub.sqlite` file exists from a failed smoke, stop the container and move that local repo artifact aside. Do not delete NAS migration packages.

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

## Hub Is Not Reachable

Confirm the Hub is running and the URL matches on every host:

```bash
python -m hypergery_ubuntu.cli hub health --hub-url http://nas-or-hub-host:8765
python -m hypergery_ubuntu.cli host list --hub-url http://nas-or-hub-host:8765
```

In the Qt app, the Remote Hosts panel uses `HYPERGERY_HUB_URL`, then the compatible `HYPERGERY_REGISTRY_URL` fallback, then `http://127.0.0.1:8765`.

## Target Host Is Offline or Blocked

The Hub marks a host offline when its heartbeat is stale. Run the agent on the target host:

```bash
python -m hypergery_ubuntu.cli agent once
python -m hypergery_ubuntu.cli agent run
```

If KVM or libvirt shows blocked, rerun preflight on that target host:

```bash
python -m hypergery_ubuntu.cli preflight
```

Fix `/dev/kvm`, `libvirt` group membership, or libvirt service issues before starting migration.

## Agent Not Showing

Verify the effective Hub URL, host ID, host name, and NAS staging path:

```bash
python -m hypergery_ubuntu.cli agent config show
python -m hypergery_ubuntu.cli doctor
```

Then send one heartbeat:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
export HYPERGERY_HOST_ID=<stable-host-id>
export HYPERGERY_HOST_NAME="<readable host name>"
export HYPERGERY_NAS_STAGING_PATH=/mnt/hypergery-nas/hypergery
python -m hypergery_ubuntu.cli agent once
python -m hypergery_ubuntu.cli host list
```

Host IDs must be stable and unique per physical host.

## NAS Staging Not Writable

Confirm the path exists on every participating host and is writable by the current user:

```bash
mkdir -p /mnt/hypergery-nas/hypergery/migrations
touch /mnt/hypergery-nas/hypergery/migrations/write-test
rm /mnt/hypergery-nas/hypergery/migrations/write-test
```

Do not use Windows paths. Use the same Linux NAS mount path on source and target when possible.

## Live Migration Blocked Because VM Is Running

v0.6.0 does not implement true live RAM migration or HG-MEMDIFF. Running VM copy is blocked by design. Shut down the source VM before NAS Clone Migration:

```bash
python -m hypergery_ubuntu.cli validate-vm <vm-name>
python -m hypergery_ubuntu.cli shutdown <vm-name>
python -m hypergery_ubuntu.cli wait-state <vm-name> "shut off" --timeout 120
```

Use Force Off only for disposable test VMs when ACPI shutdown does not respond.

## Target Name Already Exists

Migration preflight blocks target name conflicts. Pick a new target name or clean up only the test target VM you created:

```bash
virsh --connect qemu:///system dominfo <target-name>
python -m hypergery_ubuntu.cli migrate preflight <source-vm> \
  --target-vm-name <new-target-name> \
  --nas-path /mnt/hypergery-nas/hypergery
```

## Target Agent Cannot Import Package

`import_vm_package` accepts only package paths inside the agent `nas_staging_path` or its `migrations/` child. Configure the same Linux NAS mount on source and target, for example `/mnt/hypergery-nas`, and do not use Windows paths.

```bash
python -m hypergery_ubuntu.cli agent config show
python -m hypergery_ubuntu.cli migrate validate-package /mnt/hypergery-nas/migrations/<migration_id>
```

## HyperGery Console Window Does Not Connect

The HyperGery Console window currently targets local VNC displays. Check the VM display mode:

```bash
virsh --connect qemu:///system dumpxml <vm-name> | grep graphics
virsh --connect qemu:///system domdisplay <vm-name>
```

Expected for the integrated console:

```xml
<graphics type="vnc" autoport="yes" listen="127.0.0.1"/>
```

For a running VNC VM, **Console** opens the HyperGery Console window and connects automatically. **Scale to Fit** is enabled by default, keeps aspect ratio, and centers the framebuffer. Disable **Scale to Fit** to inspect the guest framebuffer at real size with scrollbars.

If the VM uses SPICE, the HyperGery Console window shows a card instead of a black screen. Use **Open External Viewer** for SPICE, or use **Switch to VNC** while the VM is shut off. HyperGery will configure the display as local VNC with `listen="127.0.0.1"` and `autoport="yes"`.

If libvirt reports `spice audio is not supported without spice graphics` or a localized variant such as `Sonido de especia no esta admitido sin graficos de especia`, the VM XML still has SPICE audio while using VNC graphics. HyperGery removes `audio type="spice"` and SPICE-only channels when switching a shut off VM to VNC.

If the integrated console says authentication is required, use **External Console**. The built-in client intentionally supports only local no-auth VNC because libvirt binds it to `127.0.0.1`.

Click inside the console window to capture keyboard and mouse input only after a VNC connection is active. Press Right Ctrl to release input. Right Ctrl does not apply to SPICE fallback mode. Disconnecting or closing the console window does not stop the VM.

## Hub Transfer Upload Fails

Symptoms: the wizard fails during `packaging`/upload with `Package upload failed`.

Checks:

- Hub reachable: `curl http://192.168.1.150:8765/health`.
- Free space on the Hub staging storage (NAS): packages need roughly the VM
  disk size plus ISO size. The staging directory is `HYPERGERY_HUB_STAGING`
  (`/hypergery/staging` in the Docker deployment).
- Free space on the source host for the temporary local copy under
  `~/.local/share/hypergery/hub-transfer/outgoing` (deleted automatically
  after upload).
- Very large files: each file upload streams with a 600 s timeout. On slow
  Wi-Fi a >20 GB disk can exceed it; prefer a wired link or `--transfer nas`.

## Hub Transfer Download or Import Fails on the Target

Symptoms: migration reaches `waiting_target`/`importing` and then `failed`.

Checks:

- Target agent running and online (`host list`).
- Free space on the target for the download
  (`~/.local/share/hypergery/hub-transfer/incoming/<migration_id>`) plus the
  imported disks under `~/.local/share/hypergery/vms/`.
- Checksum errors mean the staged package is incomplete or was modified; the
  import refuses it. Re-run the migration.
- A failed migration leaves the package staged on the Hub for inspection.
  After diagnosing, remove it manually:
  `curl -X DELETE http://192.168.1.150:8765/packages/<migration_id>`.

## Hub Transfer: Target VM Already Exists

The import refuses to overwrite an existing VM: the migration fails with
`Target VM already exists: <name>` (or `Target VM disk directory already
exists`). Pick a different target VM name in the wizard, or delete the old
test VM on the target first if you genuinely no longer need it.

## Migrations History Empty or Hub Not Reachable

The **Migrations** section reads history from the Hub. If it shows
"Hub not reachable", check the Hub URL chip in the top bar and
`curl http://192.168.1.150:8765/migrations`. History is stored in the Hub
SQLite DB; the UI never deletes records or packages.
