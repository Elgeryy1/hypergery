# TEST_RESULTS_V1 — v0.9/v1 overnight run (2026-06-06)

## Final results (after QA bug-fix round)

```text
QT_QPA_PLATFORM=offscreen ~/.venvs/hypergery/bin/python -m pytest
→ 474 passed, 1 skipped in 60.30s        (pytest 9.0.3, full suite incl. Qt offscreen)

python3 -m unittest discover -s tests
→ OK (skipped=70)                         (system Python, from the project dir)

python3 -m compileall hypergery-ubuntu    → OK
docker compose config                     → OK
```

Two QA passes (two independent adversarial reviews + dynamic probing) found
and fixed 9 issues, all with regression tests:
NAS path traversal, corrupt-commit listing, telemetry sample loss under
concurrency, memdiff partial files, misleading teleport rollback text,
accidental remote API exposure, orchestrator RAM double-count, dead
`nas commit --dry-run` flag, and non-atomic user/external-node store writes.
See V1_KNOWN_BUGS.md "Corregidos en la ronda de QA".

The single venv skip is `test_require_raises_without_battery`: psutil reports
the laptop's real battery, so the "no battery available" branch cannot be
forced on this hardware (covered by the sysfs-less code path on machines
without a battery).

Baseline at session start: 315 tests (v0.8). Added this session: **149 tests**
across 8 new test modules:

| Module | Tests | Covers |
| --- | --- | --- |
| test_v1_core.py | 13 | errors+codes, V1Settings (env/validation), structured logger, operation ids |
| test_v1_hosts_telemetry.py | 20 | telemetry readers/history/stale, alerts, host registry, health checks |
| test_v1_labs_providers.py | 21 | lab v0.9 fields/migration, validate_lab, filters, 3 VM providers |
| test_v1_nas.py | 10 | NAS health, commit dry-run/real, checksums, corruption, restore |
| test_v1_orchestrator_battery.py | 18 | battery tiers/modes/events, every orchestrator rule |
| test_v1_teleport_memdiff.py | 16 | memdiff roundtrip/corruption, teleport modes, rollback |
| test_v1_network_rbac_nodes.py | 19 | network conflicts, RBAC + guest limits, external nodes |
| test_v1_api.py | 15 | live HTTP server: envelope, all endpoints, error codes, confirm guard |
| test_v1_cli.py | 7 | v1 CLI: validation exit codes, NAS dry-run flow, guests, health |
| test_v1_integration.py | 5 | goal §20.2 flows 1–5 end to end |
| test_qt_ui.py (Control Center) | +5 | tabs, first-open refresh, inline errors, real collectors, export |

## Integration flows (goal §20.2)

1. **Create lab → validate → orchestrator plan → teleport dry-run** ✅
2. **Low battery (22%) → offload recommendations → plan moves heavy VM to home_pc** ✅
3. **NAS commit dry-run → real commit → checksum verify → restore** ✅
4. **MemDiff A/B → delta saved/loaded → apply → verify byte-identical** ✅
5. **Guest offload → PermissionDeniedError → audit log entry → orchestrator keeps local** ✅

## Real-hardware checks during the session

- Battery service read the laptop's real battery (57%, not_charging → tier
  normal, no actions — correct).
- `v1 network validate` validated the real `default-lab` network.
- v0.8 regression suite untouched and green throughout (no existing test
  modified except sidebar additions for the new pages).

### Single-machine REAL validation (no second physical host needed)

Using a second agent on the same laptop (separate host_id + data dir,
importing into the same live libvirt) against a local isolated Hub:

- **NAS commit `--confirm` REAL** to the mounted NAS: wrote
  `labs-commits/default-lab/<id>/` with checksums, verified, and **restored**
  it back with hash validation. (3.7 TB free on the NAS share.)
- **Teleport `local_loopback` REAL**: exported `ubuntu-test-v07` and imported
  it as `loop-test-v07` into live KVM, then cleaned up. Source untouched.
- **Teleport `suspend_copy_start` host→host REAL** (the previously
  "blocked" flow): source (shut off) packaged → uploaded to the local Hub →
  the second agent downloaded and imported it into **live libvirt** as
  `tp-real-v07` with a **regenerated UUID and MAC** (verified different from
  the source); migration status `done`; source VM left untouched; test VM,
  second agent, local Hub, and temp dirs all cleaned up afterward.
- This real run surfaced one improvement (teleport now supports
  `include_iso=False` / `--no-iso`, committed) — a VM whose ISO path is gone
  could not be teleported before.
- **Teleport of a RUNNING VM, REAL**: `ubuntu-test-v07` was started to a real
  `running` state, then teleported. The engine suspended it (`paused`),
  packaged the disk, the second agent imported it into live libvirt as
  `tp-running-v07`, **which then started and ran** on the "other" host. The
  source was left `paused` (so there are never two running copies). Note this
  is **not** live RAM migration: the running VM is frozen, its DISK is copied,
  and the target boots fresh from that disk — the guest's in-RAM state is not
  carried over (by design; see "no true live RAM migration"). Source restored
  to its exact original state (shut off, ISO re-attached) afterward.

The user's three real VMs (ubuntu-hub-e2e, ubuntu-migrated, ubuntu-test-v07)
were verified intact after every test.
