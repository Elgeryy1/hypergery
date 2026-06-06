# HyperGery v0.9/v1.0 Quick Start

The v1 service layer lives in `hypergery_ubuntu/v1/` on `develop`, on top of
the closed v0.8 base. Everything is **dry-run-first**: nothing destructive
happens without an explicit `--confirm` (CLI) or `"confirm": true` (API).

Start from the [v0.8 Quick Start](QUICK_START_V08.md) for Hub deployment,
remote power control, and the Labs workspace — all unchanged. This guide
covers the v1 additions: health/telemetry, NAS commit/restore, the
orchestrator and battery manager, teleport (including state-preserving
`save_restore`), and the v1 API.

## 1. Install

Same as the main [README](../README.md):

```bash
git clone https://github.com/Elgeryy1/hypergery.git
cd hypergery
git checkout develop          # v1 is on develop, not on main (v0.7.0)
./scripts/dev-run.sh          # checks deps, creates ~/.venvs/hypergery, opens the app
```

## 2. Run the tests

```bash
cd hypergery-ubuntu
QT_QPA_PLATFORM=offscreen ~/.venvs/hypergery/bin/python -m pytest -q
# or, without PySide6 (Qt tests skip cleanly):
python3 -m unittest discover -s tests
```

Expected: green on both interpreters. The only venv skip is a
hardware-dependent battery test (machines with a real battery cannot force
the "no battery" branch).

## 3. Hub (NAS control plane)

The reference Hub runs in Docker on the NAS (see
[NAS_DEPLOYMENT.md](NAS_DEPLOYMENT.md) and [HYPERGERY_HUB.md](HYPERGERY_HUB.md)):

```bash
curl http://192.168.1.150:8765/health     # reference NAS Hub
```

Or run one locally for testing:

```bash
python -m hypergery_ubuntu.cli hub serve --host 127.0.0.1 --port 8765
```

## 4. Agent (one per host)

```bash
export HYPERGERY_HUB_URL=http://192.168.1.150:8765
python -m hypergery_ubuntu.cli agent run
# or as a systemd --user service:
./scripts/install-agent-user-service.sh
```

## 5. v1 CLI tour (all local, non-destructive)

```bash
PY=~/.venvs/hypergery/bin/python

$PY -m hypergery_ubuntu.cli v1 health              # hosts + NAS + battery
$PY -m hypergery_ubuntu.cli v1 hosts               # unified registry (local + Hub)
$PY -m hypergery_ubuntu.cli v1 telemetry           # CPU/RAM/disk/battery + alerts
$PY -m hypergery_ubuntu.cli v1 battery             # real battery, tier, actions
$PY -m hypergery_ubuntu.cli v1 labs validate       # lab manifests v0.9
$PY -m hypergery_ubuntu.cli v1 network validate    # CIDR/gateway/DHCP conflicts
$PY -m hypergery_ubuntu.cli v1 orchestrator plan   # explainable plans; never executes
$PY -m hypergery_ubuntu.cli v1 guests list         # RBAC users

# NAS commit/restore (dry-run by default; --confirm writes metadata to the NAS)
$PY -m hypergery_ubuntu.cli v1 nas status
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --confirm
$PY -m hypergery_ubuntu.cli v1 nas restore --lab default-lab --commit-id <id> \
  --destination /tmp/hg-restore --confirm
```

In the Qt app, the **Control Center** sidebar page exposes the same services
in 8 tabs (read-only/dry-run) with an Export Report action.

## 6. v1 API (Android-ready, LAN only, no auth)

```bash
$PY -m hypergery_ubuntu.cli v1 api serve           # 127.0.0.1:8799 by default
curl -s http://127.0.0.1:8799/health
curl -s http://127.0.0.1:8799/battery
curl -s http://127.0.0.1:8799/orchestrator/plan
```

Non-loopback binds require an explicit `--allow-remote` because the API is
unauthenticated. Full endpoint reference: [API_V1.md](API_V1.md).

## 7. Teleport

```bash
# Validation only — copies nothing:
$PY -m hypergery_ubuntu.cli v1 teleport dry-run --vm <vm> --target <host_id>

# Real local loopback: exports and re-imports on this host as <vm>-loopback
# (real KVM, source untouched; delete the loopback VM afterwards if unwanted):
$PY -m hypergery_ubuntu.cli v1 teleport loopback --vm <vm> --staging-dir /tmp/hg-teleport

# State-preserving teleport: freezes the VM (virsh save = RAM+CPU dump),
# ships disk+state through the Hub, target restores it → the VM CONTINUES
# where it left off (not a reboot). If shipping fails after the freeze, the
# engine resumes the VM locally — it is never left stopped.
$PY -m hypergery_ubuntu.cli v1 teleport save-restore --vm <vm> --target <host_id>
```

`save_restore` keeps the VM identity (name + UUID); the target must not
already define that VM name. Cross-host shipping requires the source process
to read the libvirt saved-state file — on `qemu:///system` that file is
root-owned, so it needs `qemu:///session`, shared storage, or an ACL grant.
`suspend_copy_start` (disk copy with regenerated UUID/MAC, no RAM state)
remains available for the general case.

## 8. Known limitations (honest scope)

- **No true live-RAM migration**: `save_restore` preserves state but the VM is
  offline during transfer; MemDiff is an experimental block-delta estimator.
- **No API/Hub authentication**: trusted LAN only; planned for v1.2
  ([NEXT_STEPS_V12_SECURITY.md](../NEXT_STEPS_V12_SECURITY.md)).
- **Control Center shows raw JSON**: rich per-module screens are planned for
  v1.1 ([NEXT_STEPS_V11.md](../NEXT_STEPS_V11.md)).
- The orchestrator never executes its plans; battery modes only auto-execute
  data-safe actions.
- Full list: [V1_KNOWN_BUGS.md](../V1_KNOWN_BUGS.md).

## 9. Pending validation

Everything above is validated on real KVM on a single machine (including a
real second-agent host→host teleport and a real state-preserving restore).
The remaining manual step is the **smoke with two physical hosts**
(laptop + home PC + NAS): see [V1_MANUAL_SMOKE.md](../V1_MANUAL_SMOKE.md).
No merge to `main`, tag, or release happens before that smoke and an explicit
decision.
