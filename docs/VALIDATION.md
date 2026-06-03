# HyperGery Validation

## v0.2.0 PySide6 UI Validation Status

v0.2.0 has been prepared on `develop`, but full release validation is not marked complete until the complete real UI flow below passes on a real Ubuntu KVM/libvirt host.

Validated so far:

- PySide6/Qt UI starts from the venv/NAS setup.
- Host preflight reaches libvirt when the user has effective `libvirt` group membership.
- New VM wizard creates a real libvirt domain from a real ISO.
- The create flow was verified with `qemu-img`, `virsh define`, state `shut off`, and cleanup.
- VM state loading works with localized `virsh` output such as `ejecutando`.

Still required before tagging v0.2.0:

- Start `hg-v02-qt-test`.
- Open console with `virt-viewer` or `remote-viewer`.
- ACPI shutdown or Force Off.
- Snapshot create/list/revert/delete.
- Clone stopped VM to `hg-v02-qt-clone`.
- Safe delete `hg-v02-qt-test` and `hg-v02-qt-clone`.

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

- [ ] Create VM `hg-v02-qt-test` from a real Ubuntu/Debian ISO.
- [ ] Confirm the VM appears in the list with correct state, lab, CPU, and RAM.
- [ ] Start `hg-v02-qt-test`.
- [ ] Open Console.
- [ ] Create snapshot `before-install`.
- [ ] List snapshots and confirm `before-install` appears.
- [ ] Revert snapshot `before-install`.
- [ ] Delete snapshot `before-install`.
- [ ] ACPI shutdown; use Force Off only if the installer ignores ACPI.
- [ ] Clone stopped VM to `hg-v02-qt-clone`.
- [ ] Start clone and confirm it is independent.
- [ ] Stop clone.
- [ ] Delete clone with disk deletion.
- [ ] Delete original with disk deletion.

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
