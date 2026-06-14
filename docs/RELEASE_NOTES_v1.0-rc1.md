# HyperGery v1.0-rc1 — Release Candidate 1

**Release candidate, not a final release.** v1.0-rc1 packages the closed v0.8
(Remote Cluster Workflows) plus the v0.9/v1.0 service layer
(`hypergery_ubuntu/v1/`), after a successful **real two-physical-host smoke**.
v1.0 final will follow after the v1.1 bugfix/UX round; v1.2 covers security
hardening (API/Hub auth).

## Executive summary

HyperGery is a real Ubuntu desktop VM manager on KVM/QEMU/libvirt with a NAS
control plane (Hub), per-host agents, lab workspaces, and migrations. On top
of that, v1.0-rc1 adds the v1 service layer: structured logging and errors,
unified host registry, real telemetry with alerts, NAS lab commit/restore with
checksums, an explainable Auto-Boost orchestrator, a battery manager on real
hardware, a teleport engine (including state-preserving `save_restore`),
per-lab network validation, local RBAC, external nodes, an Android-ready local
API, a `v1` CLI group, and a Control Center UI page. Everything destructive is
dry-run-first / confirm-gated, and the source VM is never deleted by any flow.

The full automated suite is green on two interpreters (the only venv skip is
hardware-dependent), and the release was validated on real hardware — two
physical hosts plus the NAS — before this candidate was cut.

## Physical smoke result (gate for this RC)

Executed 2026-06-06 on `develop@02bbb24`, recorded in
[V1_MANUAL_SMOKE_RESULT.md](V1_MANUAL_SMOKE_RESULT.md):

> **23 PASS · 0 FAIL · 1 BLOCKED · 1 SKIP → apt for v1.0-rc1**

Validated components:

- **Hub on the NAS** (`192.168.1.150:8765`, Docker/Container Station): health,
  hosts, migrations, packages endpoints.
- **Two physical agents online**: desktop `gerard-MS-7E26` (Ryzen 7 7700X) and
  laptop `gery-Lenovo-ideapad-330S-14IKB`, with offline→online detection
  verified by stopping/restarting the laptop agent.
- **v1 CLI/API**: `v1 health`, `v1 hosts`, `v1 telemetry`, `v1 battery` (real
  battery: 55%, tier normal; clean degradation on the battery-less desktop),
  `v1 labs validate`, `v1 network validate`, `v1 guests list`; API v1 with the
  stable ok/data/error envelope, JSON errors for unknown endpoints, and the
  `confirm: true` guard on `/teleport/start`.
- **NAS commit/restore with checksums**: real commit to the NAS
  (`verified: true`), hash-validated restore, nothing live touched.
- **Orchestrator plans**: 6 explainable placement plans (weight, battery tier,
  fallback, confidence) over the real hosts/VMs; never executes.
- **Teleport loopback** (real KVM): export+import on the same host with a
  regenerated UUID; source untouched.
- **Teleport host→host between two physical machines** (the flow this RC was
  waiting for): desktop → laptop via Hub Transfer, migration `done` in ~80 s,
  target VM running on the laptop with regenerated UUID and MAC, source VM
  intact, Hub staging cleaned to 0 packages after import.
- **`save_restore` safe rollback on a real running VM**: the engine froze the
  VM, detected the unreadable state file, **resumed the VM locally** (verified
  back to `running`) and returned a clear actionable error — nothing lost.

All smoke artifacts were cleaned up; the pre-existing VMs on both hosts were
verified intact.

## Known limitations (documented, not hidden)

1. **`save_restore` cross-host shipping is BLOCKED on stock `qemu:///system`**:
   the libvirt saved-state file is root-owned, so the source process cannot
   read it for upload. The freeze→detect→resume-locally recovery is validated
   on real hardware; cross-host state shipping needs `qemu:///session`, shared
   storage, or an ACL grant on the state file. `suspend_copy_start` (disk
   copy, regenerated identity) remains the general-purpose path.
2. **Control Center manual GUI check was SKIP** in the smoke (it needs an
   interactive desktop session); the page is covered by the offscreen Qt test
   suite, which is green. Rich per-module screens are planned for v1.1.
3. **The `/mnt/hypergery-nas` bind mount is not persistent** on the desktop
   host. The smoke used the fstab-mounted share via
   `HYPERGERY_NAS_STAGING_PATH=/home/gerard/NAS_Gerard/hypergery` (same NAS).
   Recommended fix: make the bind mount persistent in fstab (or a systemd
   mount unit).
4. **`--no-iso` was needed for teleport of VMs whose attached ISO lives under
   the unmounted path** — expected behavior with a clear error and an existing
   flag, but worth knowing operationally.
5. **No API/Hub authentication yet** (trusted LAN only; binds are loopback by
   default and non-loopback requires `--allow-remote`). Planned for v1.2 —
   see [NEXT_STEPS_V12_SECURITY.md](NEXT_STEPS_V12_SECURITY.md).
6. **No true live-RAM migration**: `save_restore` preserves state with a
   transfer pause; MemDiff remains an experimental estimator.

## Decision

> **Apt for v1.0-rc1. NOT v1.0 final.**

v1.0 final will be cut after the v1.1 bugfix/UX round
([NEXT_STEPS_V11.md](NEXT_STEPS_V11.md)) addresses the known-bugs list
([V1_KNOWN_BUGS.md](V1_KNOWN_BUGS.md)) and the limitations above that are
fixable in code.

## Versioning

- Package version: `1.0.0rc1` (PEP 440) in `hypergery_ubuntu/__init__.py` and
  `pyproject.toml`; UI shows `v1.0-rc1`.
- Tag: `v1.0-rc1` on `main` (merge of `develop`).

## Reference documents

- [V1_MANUAL_SMOKE_RESULT.md](V1_MANUAL_SMOKE_RESULT.md) — full PASS/FAIL table and commands
- [CHANGELOG.md](CHANGELOG.md) — complete change history
- [docs/QUICK_START_V1.md](QUICK_START_V1.md) — v1 quick start
- [docs/API_V1.md](API_V1.md) — API v1 reference
- [ARCHITECTURE_V1.md](ARCHITECTURE_V1.md) — v1 architecture
- [V1_KNOWN_BUGS.md](V1_KNOWN_BUGS.md) — known bugs and debt targeted at v1.1
