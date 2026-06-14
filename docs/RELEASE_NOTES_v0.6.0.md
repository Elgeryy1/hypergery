# HyperGery v0.6.0 - NAS Clone Migration

HyperGery v0.6.0 is the NAS Clone Migration release. The UI action is named **Live Migration**, but this release intentionally ships the conservative NAS Clone Migration strategy: package the source VM on NAS storage, import it on the target host, regenerate target identity, and keep the source VM and original disks untouched.

## Highlights

- HyperGery Hub Docker control plane for host registration, heartbeats, VM inventory, commands, migration state, events, and healthchecks.
- HyperGery Agent for safe host capability reporting and allowlisted command execution.
- Remote Hosts UI and CLI host discovery.
- NAS Clone Migration package export/import and remote orchestration through Hub/Agent.
- VM Console Window for VNC-backed guests, with external viewer fallback for SPICE.
- App Settings for Hub URL, host identity, NAS staging path, default display, default ISO folder, and default VM storage path.
- CLI `doctor` for non-destructive host, Hub, libvirt, KVM, NAS, Docker, and VM inventory diagnostics.
- Docker Compose Hub deployment with persistent SQLite volume and NAS package bind mount.

## Validation

- Two-host physical NAS Clone Migration smoke: passed.
- Source host: `hg-source`.
- Target host: `hg-target`.
- Hub: `http://192.168.1.44:8765`.
- Migration ID: `hg-v06-2host-source-f67154f7803b`.
- Package path: `/mnt/hypergery-nas/hypergery/migrations/hg-v06-2host-source-f67154f7803b`.
- Source VM remained intact: UUID `9ede2302-fabf-4b3a-a6c0-67bd20e217fb`, MAC `52:54:00:cb:ed:8f`, disk present, VM shut off.
- Target VM imported as `hg-v06-2host-target`.
- Target UUID regenerated: `113d0d29-1726-4a7e-a703-de84f81e2602`.
- Target MAC regenerated: `52:54:a5:a1:4e:be`.
- Target booted and reached `running`.
- Target cleanup completed for `hg-v06-2host-target`; NAS package retained.
- Final tests: 214 tests OK in the Qt/offscreen venv; 214 tests OK with 15 skipped on system Python; `compileall`, shell syntax checks, and `docker compose config` passed.

## Not Included

- True live RAM migration or HG-MEMDIFF/custom dirty-page transfer.
- AutoBoost.
- Android Hub.
- IsardVDI.
- SPICE integrated console.
