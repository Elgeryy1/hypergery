from __future__ import annotations

import argparse
import sys

from .backend import HyperGeryBackend, HyperGeryError


def print_preflight(backend: HyperGeryBackend) -> int:
    worst = 0
    for item in backend.preflight():
        print(f"{item.status:7} {item.name}: {item.detail}")
        if item.fix:
            print(f"        fix: {item.fix}")
        if item.status == "Warning":
            worst = max(worst, 1)
        if item.status == "Error":
            worst = max(worst, 2)
    return worst


def validate_vm(backend: HyperGeryBackend, name: str) -> int:
    vm = backend.get_vm(name)
    print(f"name={vm.name}")
    print(f"state={vm.state}")
    print(f"lab_id={vm.lab_id}")
    print(f"ram_mib={vm.ram_mib}")
    print(f"vcpus={vm.vcpus}")
    print(f"disk_path={vm.disk_path}")
    print(f"disk_virtual={vm.disk_virtual}")
    print(f"disk_actual={vm.disk_actual}")
    print(f"iso_path={vm.iso_path}")
    print(f"network={vm.network}")
    print(f"graphics={vm.graphics}")
    print("snapshots=" + ",".join(backend.list_snapshots(name)))
    return 0


def list_vms(backend: HyperGeryBackend) -> int:
    for vm in backend.list_vms():
        print(f"{vm.name}\t{vm.state}\t{vm.lab_id}\t{vm.disk_path}")
    return 0


def create_vm(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    vm = backend.create_vm(
        name=args.name,
        iso_path=args.iso,
        os_type=args.os_type,
        ram_mib=args.ram_mib,
        vcpus=args.vcpus,
        disk_gb=args.disk_gb,
        disk_dir=args.disk_dir,
        network_mode=args.network,
        display_mode=args.display,
        lab_id=args.lab_id,
    )
    print(f"created={vm.name}")
    print(f"state={vm.state}")
    print(f"disk_path={vm.disk_path}")
    print(f"network={vm.network}")
    print(f"graphics={vm.graphics}")
    return 0


def simple_vm_action(backend: HyperGeryBackend, command: str, name: str) -> int:
    actions = {
        "start": backend.start_vm,
        "shutdown": backend.shutdown_vm,
        "force-off": backend.force_off_vm,
        "open-console": backend.open_console,
    }
    actions[command](name)
    print(f"{command}={name}")
    return 0


def snapshot_action(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    if args.snapshot_command == "list":
        for snapshot in backend.list_snapshots(args.name):
            print(snapshot)
        return 0
    if args.snapshot_command == "create":
        backend.create_snapshot(args.name, args.snapshot_name, args.description or "")
    elif args.snapshot_command == "revert":
        backend.revert_snapshot(args.name, args.snapshot_name)
    elif args.snapshot_command == "delete":
        backend.delete_snapshot(args.name, args.snapshot_name)
    print(f"snapshot-{args.snapshot_command}={args.name}:{args.snapshot_name}")
    return 0


def delete_vm(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    backend.delete_vm(args.name, delete_disks=args.delete_disks)
    print(f"deleted={args.name}")
    print(f"delete_disks={args.delete_disks}")
    return 0


def wait_state(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    state = backend.wait_for_state(
        args.name,
        set(args.state),
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
    )
    print(f"state={state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hypergery-cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="Run non-GUI host dependency checks.")
    sub.add_parser("list-vms", help="List real libvirt VMs managed by HyperGery.")
    vm_parser = sub.add_parser("validate-vm", help="Print real libvirt state for a HyperGery VM.")
    vm_parser.add_argument("name")
    wait_parser = sub.add_parser("wait-state", help="Wait until a real libvirt VM reaches one of the requested states.")
    wait_parser.add_argument("name")
    wait_parser.add_argument("state", nargs="+")
    wait_parser.add_argument("--timeout", type=int, default=120)
    wait_parser.add_argument("--interval", type=float, default=2.0)
    create_parser = sub.add_parser("create-vm", help="Create a real HyperGery VM from an ISO.")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--iso", required=True)
    create_parser.add_argument("--os-type", choices=["Linux", "Windows", "Other"], default="Linux")
    create_parser.add_argument("--ram-mib", type=int, default=4096)
    create_parser.add_argument("--vcpus", type=int, default=2)
    create_parser.add_argument("--disk-gb", type=int, default=40)
    create_parser.add_argument("--disk-dir")
    create_parser.add_argument("--network", choices=["nat", "isolated"], default="nat")
    create_parser.add_argument("--display", choices=["spice", "vnc"], default="spice")
    create_parser.add_argument("--lab-id", default="default-lab")
    for command, help_text in (
        ("start", "Start a real libvirt VM."),
        ("shutdown", "Request ACPI shutdown for a real libvirt VM."),
        ("force-off", "Force power off a real libvirt VM."),
        ("open-console", "Open a real VM console with virt-viewer or remote-viewer."),
    ):
        action_parser = sub.add_parser(command, help=help_text)
        action_parser.add_argument("name")
    delete_parser = sub.add_parser("delete-vm", help="Undefine a VM, optionally deleting its HyperGery-managed disk.")
    delete_parser.add_argument("name")
    delete_parser.add_argument("--delete-disks", action="store_true")
    snapshot_parser = sub.add_parser("snapshot", help="Manage real libvirt snapshots.")
    snapshot_sub = snapshot_parser.add_subparsers(dest="snapshot_command", required=True)
    snapshot_list = snapshot_sub.add_parser("list")
    snapshot_list.add_argument("name")
    snapshot_create = snapshot_sub.add_parser("create")
    snapshot_create.add_argument("name")
    snapshot_create.add_argument("snapshot_name")
    snapshot_create.add_argument("--description", default="")
    for snapshot_command in ("revert", "delete"):
        parser_for_command = snapshot_sub.add_parser(snapshot_command)
        parser_for_command.add_argument("name")
        parser_for_command.add_argument("snapshot_name")
    args = parser.parse_args(argv)

    try:
        backend = HyperGeryBackend()
        if args.command == "preflight":
            return print_preflight(backend)
        if args.command == "list-vms":
            return list_vms(backend)
        if args.command == "validate-vm":
            return validate_vm(backend, args.name)
        if args.command == "wait-state":
            return wait_state(backend, args)
        if args.command == "create-vm":
            return create_vm(backend, args)
        if args.command in {"start", "shutdown", "force-off", "open-console"}:
            return simple_vm_action(backend, args.command, args.name)
        if args.command == "delete-vm":
            return delete_vm(backend, args)
        if args.command == "snapshot":
            return snapshot_action(backend, args)
    except HyperGeryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
