# HyperGery Validation

## v0.3.0 RC — Automated Tests Status

Run with system Python (PySide6 not required):

```bash
python3 -m unittest discover -s hypergery-ubuntu/tests
# Expected: Ran 101 tests — OK (skipped=4)
```

Run inside the venv (all tests including Qt):

```bash
/home/gerard/.venvs/hypergery/bin/python -m unittest discover -s hypergery-ubuntu/tests
# Expected: Ran 101 tests — OK
```

The 4 skipped tests are the Qt widget tests that require PySide6 in the runtime environment. They pass cleanly in the venv.

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
/home/gerard/.venvs/hypergery/bin/python -m unittest discover -s tests
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
