# HyperGery Validation

## v0.6.0 — NAS Live Migration Validation Plan

v0.6.0 is not a release yet. Validation must prove NAS Clone Migration behavior without deleting the source VM or original disks.

Required automated checks:

```bash
cd hypergery-ubuntu && python3 -m unittest discover -s tests
cd hypergery-ubuntu && ~/.venvs/hypergery/bin/python -m unittest discover -s tests
python3 -m compileall hypergery-ubuntu
bash -n scripts/dev-run.sh scripts/bootstrap-ubuntu.sh scripts/preflight.sh scripts/acceptance-ubuntu.sh scripts/acceptance-real-host.sh scripts/install-ubuntu-deps.sh scripts/install-desktop-launcher.sh
```

First-run bootstrap smoke:

- [ ] `./scripts/dev-run.sh --check-only` prints system/package/service/group/Python readiness and does not install.
- [ ] `./scripts/dev-run.sh --no-install` exits clearly if anything is missing.
- [ ] On a prepared host, `./scripts/dev-run.sh --no-install` runs preflight and starts the Qt app without reinstalling.
- [ ] On a fresh Ubuntu laptop, `./scripts/dev-run.sh` asks before installing packages.
- [ ] `./scripts/dev-run.sh --install` installs/fixes missing items without the interactive question, while sudo/pkexec still prompts normally.
- [ ] If `kvm`/`libvirt` membership changes, the script prints the logout/login warning.
- [ ] The venv is created at `~/.venvs/hypergery` with `--copies`, not inside the repo.

Bootstrap smoke on prepared host (2026-06-04):

- [x] `./scripts/dev-run.sh --check-only` reported no missing system tools, no inactive services, no missing groups, and Python environment ready.
- [x] `timeout 8s ./scripts/dev-run.sh --no-install` did not reinstall anything, ran preflight successfully, and reached Qt app startup before the controlled timeout.

Required local smoke:

- [ ] Start local registry on port `8765`: `python -m hypergery_ubuntu.cli registry serve`.
- [ ] Start local HyperGery agent or run one cycle: `python -m hypergery_ubuntu.cli agent once`.
- [ ] Confirm local host registration and heartbeat with `python -m hypergery_ubuntu.cli host list`.
- [ ] List hosts from CLI and UI.
- [ ] Create a safe `ping` command with `python -m hypergery_ubuntu.cli host test <host_id>` and confirm the agent returns a result.
- [ ] Start a remote migration with `python -m hypergery_ubuntu.cli migrate remote <vm_name> --nas-path /mnt/hypergery-nas --source-host-id <source> --target-host-id <target> --target-vm-name <target_name>`.
- [ ] Poll it with `python -m hypergery_ubuntu.cli migrate status --migration-id <migration_id>`.
- [ ] Run migration preflight with a fake/offline target and confirm a clear blocking error.
- [ ] Package an existing stopped test VM if available.
- [ ] Validate the migration package manifest and checksums.
- [ ] Import package locally in dry-run or isolated test mode if no second host is available.
- [ ] Confirm source VM still exists and source disks remain untouched.

Registry/agent local smoke on prepared host (2026-06-04):

- [x] Started local registry with a temporary SQLite DB on `127.0.0.1:18765`.
- [x] Ran `agent once` with a temporary config and registered `local-smoke`.
- [x] Listed hosts through CLI and confirmed `local-smoke` was present.
- [x] Queued a safe `ping` command through `host test local-smoke`.
- [x] Ran `agent once` again and confirmed command status `done` with `pong=true`.

Migration package unit/CLI smoke on prepared host (2026-06-04):

- [x] `migration_preflight()` blocks a running VM with `source_will_be_deleted=false`.
- [x] `export_vm_package()` creates `manifest.json`, `domain.xml`, copied disk/ISO assets, checksums, lab metadata, and migration log in `migrations/<migration_id>/`.
- [x] `validate_vm_package()` accepts a clean package and reports checksum mismatch after asset tampering.
- [x] `import_vm_package()` rewrites target VM name, UUID, MAC address, disk paths, ISO paths, network metadata, and lab association using a simulated backend.
- [x] CLI `migrate preflight` returns JSON and preserves `source_will_be_deleted=false`.
- [x] Agent `preflight` command runs VM migration preflight and fails safely for running VMs.
- [x] Agent `receive_vm_package` validates only packages inside configured NAS staging.
- [x] Agent `import_vm_package` calls the package import flow and blocks paths outside staging.
- [x] Qt **Live Migration** dialog runs VM preflight and keeps package creation disabled for running VMs.

Recommended real NAS/two-host smoke:

- [ ] Run registry on the NAS or a machine acting as NAS.
- [ ] Configure shared staging path on source and target hosts.
- [ ] Start agent on source host and target host.
- [ ] Confirm CLI `host list` and the Qt Remote Hosts panel show both hosts online with KVM/libvirt OK.
- [ ] Queue `host test <target_host_id>`, run the target agent, and confirm command status `done`.
- [ ] Use a stopped test VM with a mounted ISO.
- [ ] Right-click VM -> **Live Migration**.
- [ ] Select target host and run preflight.
- [ ] Start migration using offline or paused NAS Clone strategy.
- [ ] Poll `migrate status --migration-id <migration_id>` until `done`.
- [ ] Confirm package exists under `/mnt/hypergery-nas/migrations/<migration_id>`.
- [ ] Confirm source VM remains on the source host.
- [ ] Confirm target VM appears on destination with new UUID and MAC.
- [ ] Confirm disks, ISO, lab metadata, network metadata, templates used, and migration log are present.
- [ ] Start target VM.
- [ ] Clean up only the test target VM/package after confirmation.

Blocking conditions:

- Running VM copy must be blocked unless a real safe libvirt/QEMU strategy is implemented.
- Missing disks are critical errors.
- Missing ISO is an error when `include_iso=True`.
- Target host offline, missing staging path, insufficient space, and target name conflicts must block Start Migration.
- No v0.6.0 release may be created until this checklist is completed.

## v0.5.0 RC — Automated Tests Status

Run with system Python (PySide6 not required):

```bash
cd hypergery-ubuntu && python3 -m unittest discover -s tests
# Expected: Ran 131 tests — OK (skipped=4)
```

Run inside the venv (all tests including Qt):

```bash
cd hypergery-ubuntu && ~/.venvs/hypergery/bin/python -m unittest discover -s tests
# Expected: Ran 131 tests — OK
```

The 4 skipped tests are Qt widget tests that require PySide6. They pass cleanly in the venv.

New in v0.5.0: 10 additional tests covering `build_lab_topology` (empty, live VMs, not-created VMs, cross-lab exclusion, deduplication, JSON export), CLI `template update`, CLI `lab-topology`, CLI `lab-instantiate --dry-run`, and libvirt KiB memory parsing.

Offscreen Qt smoke (2026-06-03):

```bash
QT_QPA_PLATFORM=offscreen python -c "
from PySide6.QtWidgets import QApplication; import sys
from hypergery_ubuntu.ui_qt.topology import LabTopologyWidget
from hypergery_ubuntu.ui_qt.lab_helpers import build_lab_topology
from hypergery_ubuntu.backend import VmSummary
app = QApplication(sys.argv)
w = LabTopologyWidget(); w.resize(500, 300)
lab = {'lab_id': 'asr-lab', 'name': 'ASR Lab', 'network_mode': 'isolated',
       'network_id': 'hg-net-asr-lab-isolated', 'subnet': '192.168.30.0/24',
       'bridge_name': 'hgbr1234567', 'vms': ['server', 'ghost']}
vms = [VmSummary(name='server', state='running', lab_id='asr-lab', ram_mib=4096, vcpus=2)]
w.set_topology(build_lab_topology(lab, vms)); w.show()
print(w.grab().width())  # should print 500
"
```

Result: widget renders at 500×300 px, 2 VM nodes (server=live/running, ghost=not created). OK.

## v0.5.0 RC — Manual/Host Smoke Validated (2026-06-04)

Validated on a real Ubuntu/KVM/libvirt host from `develop`. The UI-specific interactions were exercised with the real PySide6 widgets using Qt's test driver/offscreen rendering because the active desktop session was Wayland and no desktop automation/screenshot tools were available to the agent. Real libvirt resources were created, started, paused, force-powered-off, opened through the console flow, and cleaned up.

### Preparation

- [x] `git switch develop`
- [x] `git pull origin develop`
- [x] `./scripts/preflight.sh`
- [x] System Python tests: `Ran 131 tests — OK`
- [x] Venv PySide6 tests: `Ran 131 tests — OK`
- [x] `python3 -m compileall hypergery-ubuntu`
- [x] `bash -n` for all release scripts
- [x] `./scripts/dev-run.sh` launched without immediate traceback; stopped by controlled timeout after startup.

### Lab Topology View

- [x] Created lab `hg-v05-topology-lab`.
- [x] Created real VM `hg-v05-topology-vm` from a local Ubuntu server ISO.
- [x] Started VM and confirmed `running` via libvirt.
- [x] Suspended/resumed VM and confirmed `paused` topology state.
- [x] Force-powered VM off and confirmed `shut off`.
- [x] Rendered `LabTopologyWidget` with network node on the left and VM nodes on the right.
- [x] Confirmed colors: running green, shutoff gray, paused amber, not-created slate.
- [x] Clicked VM node via Qt test driver and confirmed the widget emitted selection for `hg-v05-topology-vm`.
- [x] No traceback.

### Planned VM Editor

- [x] Created lab template `hg-v05-asr-template`.
- [x] Added planned VMs `hg-v05-ad-server` and `hg-v05-client`.
- [x] Opened planned VM edit dialog and edited name, RAM, vCPUs, disk, role, `template_id`, and notes.
- [x] Duplicate planned VM name was blocked.
- [x] Valid changes were saved and reflected in the table.

### ISO Reuse

- [x] Opened the instantiation wizard for `hg-v05-asr-template`.
- [x] Confirmed missing ISO status label lists required VMs.
- [x] Applied the same local Ubuntu server ISO once via "Apply same ISO to all VMs...".
- [x] Confirmed all required ISO rows were filled and status label cleared.

### Instantiate Lab Template

- [x] Instantiated `hg-v05-asr-lab` from `hg-v05-asr-template`.
- [x] Created real VMs `hg-v05-ad-server-renamed` and `hg-v05-client`.
- [x] Confirmed `templates_used = ["hg-v05-asr-template"]`.
- [x] Confirmed backend activity log entries in `~/.local/state/hypergery/logs/hypergery.log`.
- [x] Started `hg-v05-ad-server-renamed`.
- [x] Opened console with `virt-viewer` flow.
- [x] ACPI shutdown did not complete within the smoke timeout; force-off succeeded and VM returned to `shut off`.

### Cleanup Preview

- [x] Opened `CleanupPreviewDialog`.
- [x] Confirmed it lists HyperGery VMs, labs, VM templates, and lab templates.
- [x] Confirmed the dialog is read-only and does not mutate resource counts.

### CLI

- [x] `lab-topology hg-v05-topology-lab` returned valid JSON.
- [x] Found and fixed a real issue: `ram_mib` was `0` because libvirt returns memory as KiB in `dumpxml`.
- [x] `lab-topology hg-v05-topology-lab` then returned `ram_mib: 1024` for the real test VM.
- [x] `lab-instantiate hg-v05-asr-template hg-v05-cli-dry-run --dry-run` returned JSON and created no lab/VM resources. It correctly reported missing ISO errors because that exact command does not provide ISO mappings.
- [x] `template update lab hg-v05-asr-template --set notes="v0.5 smoke test"` updated the template.

### Cleanup

- [x] Deleted only VMs/labs/templates with prefix `hg-v05`.
- [x] Deleted only HyperGery-managed disks through `delete-vm --delete-disks`.
- [x] Removed test libvirt networks `hg-net-hg-v05-asr-lab` and `hg-net-hg-v05-topology-lab`.
- [x] Final `virsh --connect qemu:///system list --all` showed only the pre-existing `ubuntu` VM.
- [x] No `hg-v05-*` labs/templates/disks remained under `~/.local/share/hypergery`.

### Bug Fixed During Validation

- `HyperGeryBackend.get_vm()` now converts libvirt memory units to MiB. This fixes topology/CLI reporting for hosts where `virsh dumpxml` normalizes `<memory>` to `unit="KiB"`.

## v0.5.0 RC — Manual Smoke Checklist

Run from the Qt UI (`python -m hypergery_ubuntu` inside the venv). Requires a real Ubuntu KVM/libvirt host.

### Lab Topology

- [ ] Create or select a lab with at least one VM (e.g. `hg-v04-asr-lab` from v0.4.0 smoke)
- [ ] Click the **Topology** sub-tab in the Lab Details panel
- [ ] Network node visible on the left with network name, mode, and subnet
- [ ] VM node(s) visible on the right, colour-coded by state
- [ ] Start a VM → topology refreshes after next Refresh → node turns green
- [ ] Click a VM node → VM selected in the main list, Details tab activates

### Planned VM Editor (improved)

- [ ] Select a lab template → Click **Edit**
- [ ] Planned VMs table shows columns: Name, Role, OS, RAM MiB, vCPUs, Disk GB, Display, ISO req.
- [ ] Double-click a VM row → Edit dialog opens with fields pre-filled
- [ ] Change RAM, click OK → table updates immediately
- [ ] Add a VM with the same name as an existing one → duplicate error shown
- [ ] Remove a VM row → VM count decreases

### ISO Reuse in Wizard

- [ ] Select a lab template with ≥2 planned VMs requiring ISO
- [ ] Click **Create Lab from Template** → Page 2 (ISO Mapping)
- [ ] Click **Apply same ISO to all VMs…** → browse once → all rows filled
- [ ] Status label disappears when all required ISOs are set

### Resource Overview

- [ ] Click **Resources…** button in toolbar
- [ ] Dialog shows all VMs, labs, VM templates, lab templates
- [ ] No delete buttons — read-only
- [ ] Close button works

### CLI — template update

```bash
python -m hypergery_ubuntu.cli template update vm hg-v04-ubuntu-template --set ram_mib=8192
# expected: JSON output with ram_mib=8192
```

- [ ] JSON returned; `ram_mib` updated in the file

### CLI — lab-topology

```bash
python -m hypergery_ubuntu.cli lab-topology hg-v04-asr-lab
# expected: JSON with lab_id, subnet, vms list
```

- [ ] JSON returned; `vms` list present

### CLI — lab-instantiate dry-run

```bash
python -m hypergery_ubuntu.cli lab-instantiate hg-v04-asr-template "ASR Test" \
  --iso hg-v04-ad-server=/path/to/ubuntu.iso \
  --iso hg-v04-client=/path/to/ubuntu.iso \
  --dry-run
# expected: JSON with dry_run=true, errors=[], lab=null
```

- [ ] dry_run=true in response; no lab created

### Activity Log

- [ ] All topology-tab switches, resource overview open, template edits appear in log

### Not smoke-tested (requires extended setup)

- Topology node click on a real running VM
- Per-VM progress during lab instantiation (not yet implemented)

## v0.4.0 — Automated Tests Status

Run with system Python (PySide6 not required):

```bash
cd hypergery-ubuntu && python3 -m unittest discover -s tests
# Expected: Ran 121 tests — OK (skipped=4)
```

Run inside the venv (all tests including Qt):

```bash
cd hypergery-ubuntu && ~/.venvs/hypergery/bin/python -m unittest discover -s tests
# Expected: Ran 121 tests — OK
```

The 4 skipped tests are Qt widget tests that require PySide6. They pass cleanly in the venv.

New in v0.4.0: 20 additional tests covering `instantiate_lab_template` (dry_run, ISO validation, rollback, iso_required=False), `update_vm/lab_template`, planned VM validation (duplicate names, empty names), and `_resolve_planned_vm` precedence.

## v0.4.0 — Manual Smoke Validated (2026-06-03)

Run from the Qt UI (`python -m hypergery_ubuntu` inside the venv). Validated on a real Ubuntu KVM/libvirt host.

### Lab Template Instantiation

- [x] Create VM template `hg-v04-ubuntu-template` (RAM=4096, vCPUs=2, Disk=40)
- [x] Create lab template `hg-v04-asr-template` (Network=isolated)
- [x] Edit `hg-v04-asr-template` → Add planned VM `hg-v04-ad-server` (role=server, iso_required=true)
- [x] Edit `hg-v04-asr-template` → Add planned VM `hg-v04-client` (role=client, iso_required=true)
- [x] Lab template detail panel shows VMs count = 2
- [x] Click **Create Lab from Template**
  - [x] Page 1: Enter name — preview shows lab_id and subnet
  - [x] Page 2: Browse ISO for both VMs; Next disabled without ISOs
  - [x] Page 3: Review shows both VMs with ISOs and resources
  - [x] Click **Create Lab** — activity log shows progress
- [x] Instances tab shows lab with both VMs listed
- [x] Lab details panel shows `templates_used = hg-v04-asr-template`
- [x] Start `hg-v04-ad-server` → Open Console → installer appears
- [x] Shutdown / Force Off

### Edit VM Template

- [x] Select VM template → Click **Edit** → Change RAM, add note → Save
- [x] Detail panel updates with new values

### Edit Lab Template + Planned VMs

- [x] Select `hg-v04-asr-template` → Click **Edit** → Add/remove planned VMs → Save
- [x] Detail panel reflects updated VM count

### Lab Duplicate with VM Cloning

- [x] Select lab with VMs → Click **Duplicate Lab** → Clone VMs checkbox is enabled
- [ ] Clone VMs with disk cloning (not completed in this smoke — requires all VMs shut off simultaneously; defer to extended test)

### Cleanup

- [x] Delete lab and VMs; delete both templates
- [x] Activity log records all operations; no tracebacks

### Not smoke-tested (requires extended setup)

- CLI `template update` / `template instantiate` (not yet implemented)
- Rollback from partial VM creation failure with a real ISO
- Duplicate Lab with Clone VMs end-to-end (disk clone path)

## v0.3.0 — Manual Smoke Validated (2026-06-03)

Run from the Qt UI (`python -m hypergery_ubuntu` inside the venv).

### Lab Manager

- [x] Create lab `hg-v03-asr` with network=isolated
- [x] Create lab `hg-v03-par` with network=nat
- [x] Confirm subnets differ in Lab Details panel
- [x] Rename `hg-v03-par` display name (lab_id unchanged)
- [x] Export `hg-v03-asr` to `/tmp/hg-v03-asr.json`
- [x] Import `/tmp/hg-v03-asr.json` with new id `hg-v03-asr-copy`
- [x] Verify `hg-v03-asr-copy` appears in the lab list with a different subnet
- [x] Delete all temporary labs

### Templates Manager

- [x] Create VM template `hg-v03-ubuntu-template` (OS=linux, RAM=4096, vCPUs=2, Disk=40, Net=nat, Display=spice)
- [x] Verify detail panel shows all fields including Notes
- [x] Create Lab template `hg-v03-asr-template` (Network=isolated)
- [x] Verify planned VMs count = 0 (no VMs defined in this template)
- [x] Export `hg-v03-ubuntu-template` to `/tmp/hg-v03-ubuntu-template.json`
- [x] Delete `hg-v03-ubuntu-template`, then import it back from `/tmp/`
- [x] Attempt import again with template present — error shown, no overwrite
- [x] Select `hg-v03-ubuntu-template` — **Create VM from Template** button activates
- [x] Click **Create VM from Template** — wizard opens with RAM/vCPUs/Disk/Net/Display pre-filled
- [x] ISO/name validation works (wizard disables Finish without valid ISO)
- [x] Select `hg-v03-asr-template` — **Create Lab from Template** button activates
- [x] Click **Create Lab from Template** — dialog shows network=isolated, empty planned VMs list
- [x] Enter name `ASR Instance 01` — preview shows lab_id, bridge, subnet
- [x] Create the lab — appears in Instances tab with `templates_used = hg-v03-asr-template`
- [x] Delete `ASR Instance 01`, `hg-v03-ubuntu-template`, `hg-v03-asr-template`

### Activity Log

- [x] All above operations appear in the Activity Log panel
- [x] Copy log to clipboard works

### Not smoke-tested (requires real ISO or KVM host)

- Create VM from Template end-to-end with a real ISO
- Verify `templates_used` in the lab JSON after VM creation
- Console, snapshots, clone on a real VM

## v0.3.0 Backend — Already Validated by Tests

- Lab ID validation and normalization.
- Lab create/list/show/rename/delete/export/import.
- Legacy lab manifest migration to schema version 2.
- Portable lab export without private disk/ISO paths.
- Lab bridge generation with Linux interface length limits.
- Lab subnet allocation avoiding `192.168.122.0/24` and collisions.
- VM template create/list/show/delete/export/import.
- Lab template create/list/show/delete/export/import.
- Template ID preview/normalization.
- Wizard defaults mapping (os_type, ram_mib, vcpus, disk_gb, network_mode, display).
- Import collision rejection (no silent overwrite).
- Delete non-existent template raises clear error.
- CLI coverage for `lab` and `template` commands.

## v0.3.0 Qt Lab Manager — Validated by Unit Tests

- Lab preview helper generates `lab_id`, network ID, bridge, and subnet before creation.
- Preview validation rejects duplicate lab IDs.
- VM filter helper supports `All VMs` and `Selected Lab`.
- VM count combines live libvirt summaries and manifest entries.

## Not yet implemented (v0.4 target)

- Auto-create planned VMs from lab template.
- Edit templates in place.
- Clone VM disks during lab duplicate.
- Delete Lab with VMs included.

## v0.2.0 PySide6 UI Validation Status

v0.2.0 was manually validated from the PySide6/Qt UI on a real Ubuntu KVM/libvirt host.

Validated:

- PySide6/Qt UI starts from the venv/NAS setup.
- Host preflight reaches libvirt when the user has effective `libvirt` group membership.
- New VM wizard creates `hg-v02-qt-test` from a real ISO.
- Start works and the VM reaches `running`.
- Console opens through `virt-viewer` and displays the installer.
- Power-off path works through ACPI Shutdown or Force Off, depending on guest responsiveness.
- Snapshots create/list/revert/delete work from the UI.
- Clone to `hg-v02-qt-clone` works.
- Safe delete of test and clone works.
- No `hg-v02-qt-test` or `hg-v02-qt-clone` VMs/disks remain after validation.
- VM state loading works with localized `virsh` output such as `ejecutando`.

## v0.2.0 Manual UI Checklist

Use real names:

```text
hg-v02-qt-test
hg-v02-qt-clone
```

Run:

```bash
git switch develop
git pull origin develop
source ~/.venvs/hypergery/bin/activate
./scripts/preflight.sh
./scripts/dev-run.sh
```

If the current login session has not inherited the `libvirt` group yet, either log out and back in or run:

```bash
sg libvirt -c 'cd /path/to/miversiondevirtualbox && source ~/.venvs/hypergery/bin/activate && ./scripts/dev-run.sh'
```

Checklist:

- [x] Create VM `hg-v02-qt-test` from a real Ubuntu/Debian ISO.
- [x] Confirm the VM appears in the list with correct state, lab, CPU, and RAM.
- [x] Start `hg-v02-qt-test`.
- [x] Open Console.
- [x] Create snapshot `before-install`.
- [x] List snapshots and confirm `before-install` appears.
- [x] Revert snapshot `before-install`.
- [x] Delete snapshot `before-install`.
- [x] ACPI shutdown or Force Off, depending on guest responsiveness.
- [x] Clone stopped VM to `hg-v02-qt-clone`.
- [x] Start clone and confirm it is independent.
- [x] Stop clone.
- [x] Delete clone with disk deletion.
- [x] Delete original with disk deletion.

## v0.1.0 Validation

HyperGery v0.1.0 was validated on a real Ubuntu KVM/libvirt host.

The validation covered:

- Real preflight against `/dev/kvm`, libvirt, QEMU tools, and viewer tools.
- Real VM creation from an Ubuntu ISO.
- Real qcow2 disk creation.
- Real libvirt network creation for `hg-net-default-lab`.
- Real SPICE console opened with `virt-viewer`.
- Real snapshots: create, list, revert, delete.
- Real clone of a stopped VM with an independent qcow2 disk.
- Safe delete of managed test VMs and disks.

Repeat CLI acceptance:

```bash
./scripts/preflight.sh
./scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso --name hg-acceptance-ubuntu-test
```

## Running tests

### System Python (no PySide6)

```bash
python3 -m unittest discover -s hypergery-ubuntu/tests
```

Expected: all non-Qt tests pass; `test_qt_ui` and `test_qt_lab_helpers` classes that require PySide6 are **skipped** (not errors). Overall result: `OK (skipped=N)`.

### Venv with PySide6

```bash
~/.venvs/hypergery/bin/python -m unittest discover -s tests
```

Expected: all tests pass including Qt UI tests.

## Templates Manager smoke test (v0.3.0)

Run this after starting the Qt UI (`python -m hypergery_ubuntu` inside the venv).

1. Open the **Templates** tab in the left panel.

2. **Create VM template**
   - Click **New VM Template**.
   - Enter Name: `HG v03 Ubuntu Template`.
   - Verify Template ID preview shows `hg-v03-ubuntu-template`.
   - Set OS=linux, RAM=4096, vCPUs=2, Disk=40, Network=nat, Display=spice.
   - Click **Create** — template appears in the VM Templates table.

3. **Create Lab template**
   - Click **New Lab Template**.
   - Enter Name: `HG v03 ASR Template`.
   - Verify Template ID preview shows `hg-v03-asr-template`.
   - Set Network=isolated.
   - Click **Create** — template appears in the Lab Templates table.

4. **Select and inspect**
   - Click on `hg-v03-ubuntu-template` — detail panel shows all fields, **Create VM from Template** button activates.
   - Click on `hg-v03-asr-template` — detail panel updates, **Create Lab from Template** button activates.

5. **Create VM from Template**
   - Select `hg-v03-ubuntu-template`.
   - Click **Create VM from Template**.
   - Wizard opens with RAM=4096, vCPUs=2, Disk=40, Network=nat, Display=spice pre-filled.
   - Enter a VM name and a valid local ISO path.
   - Complete the wizard — VM is created; activity log shows "Creating VM … from template".
   - Open the Instances tab — VM appears in the list.
   - (Optional) Open the lab manifest JSON and verify `templates_used` contains `hg-v03-ubuntu-template`.

6. **Create Lab from Template**
   - Select `hg-v03-asr-template`.
   - Click **Create Lab from Template**.
   - Dialog opens with network=isolated pre-filled, preview shows lab_id/bridge/subnet.
   - Enter a lab name (e.g. `ASR Instance 01`).
   - Click **Create Lab** — lab appears in the Labs table; activity log shows "Created lab … from template".
   - Verify `templates_used` in the lab manifest.

7. **Export VM template**
   - Select `hg-v03-ubuntu-template`.
   - Click **Export** — choose a path like `/tmp/hg-v03-ubuntu-template.json`.
   - File is created with valid JSON.

8. **Import VM template (collision)**
   - With `hg-v03-ubuntu-template` present, click **Import** and select the same file.
   - An error is shown: "VM template already exists" — no silent overwrite.

9. **Delete test artifacts**
   - Delete `hg-v03-ubuntu-template` and `hg-v03-asr-template` by typing their IDs.
   - Delete the lab created in step 6.
   - Tables are empty after deletion.

Expected: no tracebacks, activity log records each operation, UI stays responsive.
