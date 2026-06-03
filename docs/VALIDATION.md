# HyperGery Validation

## v0.3.0 Labs & Templates Backend Foundation

Validated in the v0.3.0 development branch:

- Lab ID validation and normalization.
- Lab create/list/show/rename/delete/export/import.
- Legacy lab manifest migration to schema version 2.
- Portable lab export without private disk/ISO paths.
- Lab bridge generation with Linux interface length limits.
- Lab subnet allocation avoiding `192.168.122.0/24` and collisions.
- VM template create/list/show/delete.
- Lab template create/list/show/delete/export/import.
- CLI coverage for minimal `lab` and `template` commands.

## v0.3.0 Qt Lab Manager First Pass

Implemented and covered by lightweight tests where possible:

- Lab preview helper generates `lab_id`, network ID, bridge, and subnet before creation.
- Preview validation rejects duplicate lab IDs.
- VM filter helper supports `All VMs` and `Selected Lab`.
- VM count combines live libvirt summaries and manifest entries.
- Qt main window now loads real labs from `LabStore`, shows details, and exposes create/rename/delete/duplicate/export/import actions.
- `New VM in Lab` opens the VM wizard with the selected `lab_id` prefilled.

Manual validation recommended before cutting v0.3.0:

- Create `hg-v03-asr`.
- Create `hg-v03-par`.
- Confirm subnets differ.
- Rename one lab.
- Export one lab.
- Import the exported JSON with another lab ID.
- Delete the temporary labs.

Not yet implemented in that pass (now done):

- Full Templates UI with Create VM / Create Lab from Template flows.
- Lab VM cloning from the Duplicate Lab dialog.
- Delete Lab with VM deletion.

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
