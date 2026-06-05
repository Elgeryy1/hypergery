# NAS Deployment

This is the v0.6.0 deployment shape for HyperGery Hub on the QNAP/NAS.

Final release status: Hub Docker, local Hub/Agent/NAS Clone Migration smoke, and a real two-physical-host NAS Clone Migration smoke passed for v0.6.0.

Real paths:

- NAS IP: `192.168.1.150`
- QNAP repo path: `/share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox`
- QNAP HyperGery data path: `/share/CACHEDEV2_DATA/Gerard/hypergery`
- Ubuntu repo mount: `/mnt/hypergery-nas/proyectos_hacen_bulto_en_CV/miversiondevirtualbox`
- Ubuntu HyperGery data mount: `/mnt/hypergery-nas/hypergery`
- Ubuntu migration staging: `/mnt/hypergery-nas/hypergery/migrations`
- Container migration staging: `/hypergery/migrations`

## Start Hub On NAS

```bash
cd /share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/docker
cp .env.example .env
mkdir -p /share/CACHEDEV2_DATA/Gerard/hypergery/migrations
docker compose config
docker compose build
docker compose up -d
docker compose logs -f
curl http://192.168.1.150:8765/health
```

Do not store passwords, SSH keys, or SMB credentials in `.env`, scripts, or docs.

The Hub SQLite DB is stored in the Docker volume `hypergery-hub-data`, not in the NAS share. The NAS bind mount is only for migration packages and assets under `/hypergery`.

## Ubuntu Agent

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
export HYPERGERY_HOST_ID=ubuntu-hyperv
export HYPERGERY_HOST_NAME="Ubuntu Hyper-V"
export HYPERGERY_NAS_STAGING_PATH=/mnt/hypergery-nas/hypergery
python -m hypergery_ubuntu.cli agent run
```

## App

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
python -m hypergery_ubuntu.app
```

Remote Hosts and Live Migration use the Hub for host list, target selection, command creation, migration status, and VM inventory.

## Roles

- Hub: control plane and metadata.
- Agents: workers on libvirt hosts.
- App: Qt UI.
- NAS folder: migration packages and asset storage.
- DB: metadata and state.

Source VMs and source disks remain untouched during NAS clone migration.

v0.6.0 does not include true live RAM migration, HG-MEMDIFF/custom dirty-page transfer, AutoBoost, Android Hub, IsardVDI, or a SPICE integrated console.
