# HyperGery v0.6 Quick Start

HyperGery v0.6.0 is RC-candidate work, not a final release. Docker Hub, Hub/Agent smoke, UI smoke, and local NAS Clone Migration E2E have passed. A real two-physical-host NAS Clone Migration smoke is still required before final release.

## 1. Mount NAS Storage

Expected Ubuntu mount:

```bash
/mnt/hypergery-nas/hypergery
```

Create the migration staging directory and test write access:

```bash
mkdir -p /mnt/hypergery-nas/hypergery/migrations
touch /mnt/hypergery-nas/hypergery/migrations/write-test
rm /mnt/hypergery-nas/hypergery/migrations/write-test
```

Do not store SMB passwords, SSH keys, or tokens in the repo, `.env`, docs, or scripts.

## 2. Start HyperGery Hub

On the NAS/QNAP:

```bash
cd /share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/docker
cp -n .env.example .env
mkdir -p /share/CACHEDEV2_DATA/Gerard/hypergery/migrations
docker compose config
docker compose build
docker compose up -d
docker compose ps
curl http://192.168.1.150:8765/health
```

The Hub SQLite DB is stored in Docker volume `hypergery-hub-data`. The NAS bind mount is only for migration packages under `/hypergery/migrations`.

## 3. Configure App Settings

Open HyperGery and select **App Settings**.

Minimum settings:

- Hub URL: `http://192.168.1.150:8765`
- Host ID: a stable ID such as `ubuntu-hyperv-source`
- Host name: a readable name
- NAS staging path: `/mnt/hypergery-nas/hypergery`
- Default display: `vnc` for integrated console, `spice` for external viewer

Settings are saved at:

```bash
~/.config/hypergery/config.json
```

Environment variables such as `HYPERGERY_HUB_URL`, `HYPERGERY_HOST_ID`, and `HYPERGERY_NAS_STAGING_PATH` override saved settings.

## 4. Run Doctor

```bash
cd /mnt/hypergery-nas/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/hypergery-ubuntu
source ~/.venvs/hypergery/bin/activate
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
export HYPERGERY_NAS_STAGING_PATH=/mnt/hypergery-nas/hypergery
python -m hypergery_ubuntu.cli doctor
```

`doctor` does not install, delete, migrate, or modify VMs. It reports Python, KVM, libvirt, tools, Hub, NAS staging, Docker Compose, and Hub VM inventory.

## 5. Start Agent

On each libvirt host:

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
export HYPERGERY_HOST_ID=ubuntu-hyperv-source
export HYPERGERY_HOST_NAME="Ubuntu Hyper-V Source"
export HYPERGERY_NAS_STAGING_PATH=/mnt/hypergery-nas/hypergery
python -m hypergery_ubuntu.cli agent run
```

Use a different `HYPERGERY_HOST_ID` on the target host.

Smoke:

```bash
python -m hypergery_ubuntu.cli host list
python -m hypergery_ubuntu.cli hub vms
python -m hypergery_ubuntu.cli host test <target-host-id>
```

Run the target agent once more if the test command is pending:

```bash
python -m hypergery_ubuntu.cli agent once
```

## 6. Open App And Check Remote Hosts

```bash
cd /mnt/hypergery-nas/proyectos_hacen_bulto_en_CV/miversiondevirtualbox
./scripts/dev-run.sh --no-install
```

In **Remote Hosts**:

- Hub status should be online.
- Source and target hosts should appear.
- KVM and libvirt should be OK.
- NAS staging should be writable.

## 7. Create A Test VM

Create only a disposable VM with a clear prefix:

```bash
python -m hypergery_ubuntu.cli create-vm \
  --name hg-v06-e2e-source \
  --iso /path/to/ubuntu.iso \
  --ram-mib 1024 \
  --vcpus 1 \
  --disk-gb 2 \
  --display vnc
```

Keep it shut off before migration.

## 8. Test Console

For VNC VMs:

- Start the VM.
- Select **Console**.
- Confirm the separate console window connects.
- Press Right Ctrl to release input.

For SPICE VMs:

- Select **Console** to confirm the VNC-required card.
- Select **External Console** to open `virt-viewer` or `remote-viewer`.

## 9. Run NAS Clone Migration

CLI:

```bash
python -m hypergery_ubuntu.cli migrate remote hg-v06-e2e-source \
  --source-host-id <source-host-id> \
  --target-host-id <target-host-id> \
  --target-vm-name hg-v06-e2e-target \
  --nas-path /mnt/hypergery-nas/hypergery \
  --no-snapshots
```

Poll:

```bash
python -m hypergery_ubuntu.cli migrate status --migration-id <migration_id>
```

Expected:

- Status reaches `done`.
- Package exists under `/mnt/hypergery-nas/hypergery/migrations/<migration_id>`.
- Source VM and source disk remain intact.
- Target VM is imported with new UUID and MAC.
- Target VM can start.

## 10. Cleanup

Clean only test resources you created:

```bash
python -m hypergery_ubuntu.cli delete-vm hg-v06-e2e-target --delete-disks
```

Do not delete personal VMs. Do not delete NAS data outside the specific migration package you intentionally decide to clean.
