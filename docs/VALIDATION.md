# HyperGery Validation

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
