from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .backend import HyperGeryBackend, HyperGeryError
from .config import HyperGeryConfig
from .labs import LabStore
from .templates import TemplateStore
from .ui_qt.formatting import format_size


def default_hub_url() -> str:
    from .config import effective_value

    return effective_value("hub_url")


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
        profile=getattr(args, "profile", ""),
        migratable_cpu=getattr(args, "migratable_cpu", False),
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


def print_json(data: object) -> int:
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def wait_for_command(client: object, command_id: str, *, timeout_seconds: float, interval_seconds: float) -> dict:
    deadline = time.monotonic() + timeout_seconds
    command = client.command(command_id)
    while command.get("status") not in {"done", "failed"} and time.monotonic() < deadline:
        time.sleep(interval_seconds)
        command = client.command(command_id)
    return command


def doctor_action() -> int:
    from .doctor import collect_doctor_items, doctor_exit_code, format_doctor_items

    items = collect_doctor_items()
    print(format_doctor_items(items))
    return doctor_exit_code(items)


def lab_action(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    store = LabStore(backend.data_dir)
    if args.lab_command == "list":
        for lab in store.list_labs():
            print(f"{lab['lab_id']}\t{lab['name']}\t{lab.get('network_mode', 'nat')}\t{len(lab.get('vms', []))}")
        return 0
    if args.lab_command == "create":
        lab = store.create_lab(args.name, args.description, args.network_mode, lab_id=args.lab_id)
        return print_json(lab)
    if args.lab_command == "show":
        return print_json(store.get_lab(args.lab_id))
    if args.lab_command == "rename":
        return print_json(store.rename_lab(args.lab_id, args.new_name))
    if args.lab_command == "delete":
        store.delete_lab(args.lab_id, delete_vms=args.delete_vms)
        print(f"deleted_lab={args.lab_id}")
        print(f"delete_vms={args.delete_vms}")
        return 0
    if args.lab_command == "set-vm-tags":
        return print_json(store.set_vm_tags(args.lab_id, args.vm_name, args.tags))
    if args.lab_command == "set-budget":
        return print_json(
            store.set_budget(
                args.lab_id,
                max_ram_mib=args.max_ram_mib,
                max_vcpus=args.max_vcpus,
                max_vms=args.max_vms,
            )
        )
    if args.lab_command == "export":
        output = store.export_lab(args.lab_id, args.output)
        print(f"exported_lab={args.lab_id}")
        print(f"path={output}")
        return 0
    if args.lab_command == "import":
        lab = store.import_lab(args.input, new_lab_id=args.new_lab_id)
        return print_json(lab)
    return 2


def template_action(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    store = TemplateStore(backend.data_dir, backend=backend, lab_store=LabStore(backend.data_dir))
    if args.template_command == "list":
        templates = store.list_vm_templates() if args.kind == "vm" else store.list_lab_templates()
        for template in templates:
            print(f"{template['template_id']}\t{template['name']}")
        return 0
    if args.template_command == "show":
        template = store.get_vm_template(args.template_id) if args.kind == "vm" else store.get_lab_template(args.template_id)
        return print_json(template)
    if args.template_command == "delete":
        if args.kind == "vm":
            store.delete_vm_template(args.template_id)
        else:
            store.delete_lab_template(args.template_id)
        print(f"deleted_template={args.kind}:{args.template_id}")
        return 0
    if args.template_command == "update":
        kwargs: dict = {}
        for pair in (args.set or []):
            if "=" not in pair:
                print(f"ERROR: --set must be key=value, got: {pair}", file=sys.stderr)
                return 2
            k, _, v = pair.partition("=")
            kwargs[k.strip()] = v.strip()
        if args.kind == "vm":
            updated = store.update_vm_template(args.template_id, **kwargs)
        else:
            updated = store.update_lab_template(args.template_id, **kwargs)
        return print_json(updated)
    return 2


def lab_topology_action(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    from .ui_qt.lab_helpers import build_lab_topology
    store = LabStore(backend.data_dir)
    lab = store.get_lab(args.lab_id)
    vms = backend.list_vms()
    topology = build_lab_topology(lab, vms)
    return print_json(topology)


def lab_instantiate_action(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    store = TemplateStore(backend.data_dir, backend=backend, lab_store=LabStore(backend.data_dir))
    vm_iso_map: dict[str, str] = {}
    for pair in (args.iso or []):
        if "=" not in pair:
            print(f"ERROR: --iso must be vm_name=path, got: {pair}", file=sys.stderr)
            return 2
        name, _, path = pair.partition("=")
        vm_iso_map[name.strip()] = path.strip()
    result = store.instantiate_lab_template(
        args.template_id,
        args.lab_name,
        vm_iso_map,
        dry_run=args.dry_run,
        new_lab_description=args.description or "",
    )
    return print_json(result)


def registry_action(args: argparse.Namespace) -> int:
    if args.registry_command == "serve":
        from .registry import serve_registry

        serve_registry(
            args.host,
            args.port,
            db_path=args.db_path,
            offline_timeout_seconds=args.offline_timeout,
            auth_token="" if args.no_auth else (args.token or None),
        )
        return 0
    if args.registry_command == "health":
        url = args.registry_url.rstrip("/") + "/health"
        try:
            with urlopen(Request(url, method="GET"), timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Registry health check failed for {url}: {exc}") from exc
        return print_json(data)
    return 2


def print_staged_packages(listing: dict) -> int:
    packages = listing.get("packages") or []
    print(f"staging_dir: {listing.get('staging_dir', '')}")
    print(f"packages: {listing.get('count', 0)}  orphans: {listing.get('orphan_count', 0)}  total: {format_size(listing.get('total_size_bytes', 0))}")
    if not packages:
        print("No staged packages found.")
        return 0
    print(f"{'MIGRATION ID':36} {'SIZE':>10} {'FILES':>5} {'AGE(H)':>7} {'STATUS':14} ORPHAN")
    for package in packages:
        print(
            f"{package.get('migration_id', ''):36} "
            f"{format_size(package.get('size_bytes', 0)):>10} "
            f"{package.get('file_count', 0):>5} "
            f"{package.get('age_hours', 0):>7} "
            f"{(package.get('migration_status') or '-'):14} "
            f"{'yes' if package.get('orphan') else 'no'}"
        )
    return 0


def print_cleanup_result(result: dict) -> int:
    mode = "DRY RUN (nothing deleted)" if result.get("dry_run") else "CLEANUP EXECUTED"
    print(f"mode: {mode}")
    print(f"staging_dir: {result.get('staging_dir', '')}")
    print(f"older_than_hours: {result.get('older_than_hours', '')}")
    candidates = result.get("candidates") or []
    print(f"candidates: {len(candidates)}  total: {format_size(result.get('total_size_bytes', 0))}")
    for candidate in candidates:
        print(f"  - {candidate.get('migration_id', '')} ({format_size(candidate.get('size_bytes', 0))}): {candidate.get('reason', '')}")
    skipped = result.get("skipped") or []
    print(f"skipped: {len(skipped)}")
    for item in skipped:
        print(f"  - {item.get('migration_id', '')}: {item.get('reason', '')}")
    if not result.get("dry_run"):
        print(f"deleted: {result.get('deleted_count', 0)}  freed: {format_size(result.get('deleted_size_bytes', 0))}")
    errors = result.get("errors") or []
    for error in errors:
        print(f"ERROR: {error.get('migration_id', '')}: {error.get('error', '')}", file=sys.stderr)
    print("Only temporary Hub staging packages are deleted. VMs and imported disks are never touched.")
    return 1 if errors else 0


def hub_action(args: argparse.Namespace) -> int:
    from .registry import RegistryClient, RegistryStore, serve_registry

    if args.hub_command == "serve":
        serve_registry(
            args.host,
            args.port,
            db_path=args.db_path,
            offline_timeout_seconds=args.offline_timeout,
            staging_dir=args.staging_dir or None,
            auth_token="" if args.no_auth else (args.token or None),
        )
        return 0
    if args.hub_command == "pairing-info":
        from .registry.auth import load_or_create_hub_token

        store = RegistryStore(args.db_path or None)
        token = load_or_create_hub_token(store.db_path)
        print("ADVERTENCIA: el token es un secreto. Compártelo solo por un canal seguro (TLS/VPN).", file=sys.stderr)
        return print_json({"hub_url": args.hub_url, "token": token, "pair_uri": f"hypergery://pair?url={args.hub_url}&token={token}"})
    if args.hub_command == "init-db":
        store = RegistryStore(args.db_path)
        return print_json({"ok": True, "db_path": str(store.db_path)})
    client = RegistryClient(args.hub_url)
    if args.hub_command == "health":
        return print_json(client.health())
    if args.hub_command == "vms":
        return print_json({"vms": client.list_vms(args.host_id or None)})
    if args.hub_command == "packages":
        return print_staged_packages(client.list_staged_packages())
    if args.hub_command == "cleanup-staging":
        # Safety: without --confirm this is always a dry run, even if the
        # user also passed --dry-run or nothing at all.
        dry_run = not args.confirm
        result = client.cleanup_staging(
            older_than_hours=args.older_than_hours,
            dry_run=dry_run,
            include_failed=args.include_failed,
            include_orphans=not args.no_orphans,
        )
        return print_cleanup_result(result)
    return 2


def agent_action(args: argparse.Namespace) -> int:
    from .agent import AgentConfig, HyperGeryAgent, main as agent_main

    if args.agent_command == "config" and args.config_command == "show":
        return agent_main(["config", "show", *(["--config", args.config] if args.config else [])])
    config = AgentConfig.load(args.config or None)
    agent = HyperGeryAgent(config)
    if args.agent_command == "once":
        return print_json(agent.run_once())
    if args.agent_command == "run":
        agent.run_forever()
        return 0
    return 2


def host_action(args: argparse.Namespace) -> int:
    from .registry import RegistryClient

    client = RegistryClient(args.hub_url)
    if args.host_command == "list":
        return print_json({"hosts": client.list_hosts()})
    if args.host_command == "show":
        return print_json(client.get_host(args.host_id))
    if args.host_command == "test":
        command = client.create_command(args.host_id, "ping", {})
        if args.wait and args.timeout > 0:
            command = wait_for_command(
                client,
                command["command_id"],
                timeout_seconds=args.timeout,
                interval_seconds=args.interval,
            )
        return print_json(command)
    return 2


def migrate_action(backend: HyperGeryBackend, args: argparse.Namespace) -> int:
    from .migration import (
        export_vm_package,
        poll_remote_migration_status,
        import_vm_package,
        list_migration_packages,
        migration_preflight,
        start_remote_migration,
        validate_vm_package,
    )

    if args.migrate_command == "preflight":
        return print_json(
            migration_preflight(
                backend,
                args.vm_name,
                target_host=args.target_host or "",
                target_vm_name=args.target_vm_name or "",
                nas_path=args.nas_path or "",
                allow_paused=args.allow_paused,
                include_iso=not args.no_iso,
                include_snapshots=not args.no_snapshots,
            )
        )
    if args.migrate_command == "package":
        return print_json(
            export_vm_package(
                backend,
                args.vm_name,
                args.output_dir,
                target_vm_name=args.target_vm_name or "",
                allow_paused=args.allow_paused,
                include_iso=not args.no_iso,
                include_snapshots=not args.no_snapshots,
            )
        )
    if args.migrate_command == "validate-package":
        return print_json(validate_vm_package(args.package_dir))
    if args.migrate_command == "import":
        return print_json(
            import_vm_package(
                backend,
                args.package_dir,
                target_vm_name=args.target_vm_name or "",
                target_lab_id=args.target_lab_id or "",
            )
        )
    if args.migrate_command == "list":
        return print_json({"packages": list_migration_packages(args.path)})
    if args.migrate_command == "status":
        if getattr(args, "migration_id", ""):
            from .registry import RegistryClient

            client = RegistryClient(args.registry_url)
            return print_json(poll_remote_migration_status(client, args.migration_id))
        if not args.package_dir:
            raise HyperGeryError("migrate status requires a package_dir or --migration-id.")
        validation = validate_vm_package(args.package_dir)
        manifest = validation.get("manifest") or {}
        return print_json(
            {
                "ok": validation["ok"],
                "migration_id": manifest.get("migration_id", ""),
                "source_vm_name": manifest.get("source_vm_name", ""),
                "target_vm_name": manifest.get("target_vm_name", ""),
                "created_at": manifest.get("created_at", ""),
                "errors": validation["errors"],
                "warnings": validation["warnings"],
            }
        )
    if args.migrate_command == "remote":
        from .registry import RegistryClient

        client = RegistryClient(args.registry_url)
        return print_json(
            start_remote_migration(
                backend,
                client,
                args.vm_name,
                args.nas_path,
                source_host_id=args.source_host_id,
                target_host_id=args.target_host_id,
                target_vm_name=args.target_vm_name or "",
                target_lab_id=args.target_lab_id or "",
                allow_paused=args.allow_paused,
                include_iso=not args.no_iso,
                include_snapshots=not args.no_snapshots,
                start_after_import=args.start_after_import,
                transfer=args.transfer,
            )
        )
    return 2


def setup_action(args) -> int:
    """`hypergery-cli setup …` (v1.5 First Run Setup). Nunca imprime tokens."""
    from . import firstrun

    if args.setup_command == "status":
        status = firstrun.setup_status()
        for key, value in status.items():
            print(f"{key}: {value}")
        return 0
    if args.setup_command == "wizard":
        from .ui_qt.main import main as qt_main

        return qt_main([sys.argv[0]], force_first_run=True)
    if args.setup_command == "generate-docker-bundle":
        written = firstrun.generate_docker_bundle(args.output)
        print(f"Bundle del Hub generado en {Path(args.output).expanduser()}:")
        for item in written:
            print(f"  {item}")
        print("Siguiente paso: lee README_SETUP.md dentro de la carpeta. (No se ha ejecutado Docker.)")
        return 0
    if args.setup_command == "test-hub":
        config = HyperGeryConfig.load()
        url = args.url or config.hub_url
        token = args.token or config.hub_token
        if not url:
            print("ERROR: no hay URL del Hub (pásala con --url o configúrala antes).", file=sys.stderr)
            return 2
        result = firstrun.test_hub_connection(url, token)
        print(f"{result['status']}: {result['message']}")
        return 0 if result["status"] == "ok" else 1
    if args.setup_command == "reset-first-run":
        path = firstrun.reset_first_run()
        print(f"first_run_completed borrado en {path}: el asistente volverá a salir al arrancar la app.")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    from . import __version__

    parser = argparse.ArgumentParser(prog="hypergery-cli")
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="Run non-GUI host dependency checks.")
    sub.add_parser("doctor", help="Run v0.6 Hub, agent, NAS, Docker, and libvirt diagnostics without changing the system.")
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
    create_parser.add_argument(
        "--profile",
        default="",
        help="VM profile: linux | linux-uefi | windows11 | windows-legacy | other (overrides --os-type).",
    )
    create_parser.add_argument(
        "--migratable-cpu",
        action="store_true",
        help="Use a portable baseline CPU so the running VM can be live-migrated between different hosts (AMD<->Intel).",
    )
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
    lab_parser = sub.add_parser("lab", help="Manage HyperGery lab manifests.")
    lab_sub = lab_parser.add_subparsers(dest="lab_command", required=True)
    lab_sub.add_parser("list")
    lab_create = lab_sub.add_parser("create")
    lab_create.add_argument("name")
    lab_create.add_argument("--lab-id")
    lab_create.add_argument("--description", default="")
    lab_create.add_argument("--network-mode", choices=["nat", "isolated"], default="nat")
    lab_show = lab_sub.add_parser("show")
    lab_show.add_argument("lab_id")
    lab_rename = lab_sub.add_parser("rename")
    lab_rename.add_argument("lab_id")
    lab_rename.add_argument("new_name")
    lab_delete = lab_sub.add_parser("delete")
    lab_delete.add_argument("lab_id")
    lab_delete.add_argument("--delete-vms", action="store_true")
    lab_tags = lab_sub.add_parser("set-vm-tags", help="Set (or clear with no tags) free-form tags on one lab VM.")
    lab_tags.add_argument("lab_id")
    lab_tags.add_argument("vm_name")
    lab_tags.add_argument("tags", nargs="*")
    lab_budget = lab_sub.add_parser("set-budget", help="Set the lab resource budget (0 = unlimited).")
    lab_budget.add_argument("lab_id")
    lab_budget.add_argument("--max-ram-mib", type=int, default=0)
    lab_budget.add_argument("--max-vcpus", type=int, default=0)
    lab_budget.add_argument("--max-vms", type=int, default=0)
    lab_export = lab_sub.add_parser("export")
    lab_export.add_argument("lab_id")
    lab_export.add_argument("output")
    lab_import = lab_sub.add_parser("import")
    lab_import.add_argument("input")
    lab_import.add_argument("--new-lab-id")
    template_parser = sub.add_parser("template", help="Manage VM and lab templates.")
    template_sub = template_parser.add_subparsers(dest="template_command", required=True)
    template_list = template_sub.add_parser("list")
    template_list.add_argument("kind", choices=["vm", "lab"])
    template_show = template_sub.add_parser("show")
    template_show.add_argument("kind", choices=["vm", "lab"])
    template_show.add_argument("template_id")
    template_delete = template_sub.add_parser("delete")
    template_delete.add_argument("kind", choices=["vm", "lab"])
    template_delete.add_argument("template_id")
    template_update = template_sub.add_parser("update", help="Update fields in an existing template.")
    template_update.add_argument("kind", choices=["vm", "lab"])
    template_update.add_argument("template_id")
    template_update.add_argument("--set", dest="set", action="append", metavar="key=value",
                                 help="Field to update. Repeat for multiple fields.")
    lab_topology_p = sub.add_parser("lab-topology", help="Print lab topology as JSON.")
    lab_topology_p.add_argument("lab_id")
    lab_instantiate_p = sub.add_parser("lab-instantiate", help="Instantiate a lab template (create real lab + VMs).")
    lab_instantiate_p.add_argument("template_id")
    lab_instantiate_p.add_argument("lab_name")
    lab_instantiate_p.add_argument("--iso", action="append", metavar="vm_name=path",
                                   help="ISO path for a planned VM. Repeat for each VM.")
    lab_instantiate_p.add_argument("--description", default="")
    lab_instantiate_p.add_argument("--dry-run", action="store_true",
                                   help="Validate and show plan without creating anything.")
    registry_parser = sub.add_parser("registry", help="Run or query the NAS control plane registry.")
    registry_sub = registry_parser.add_subparsers(dest="registry_command", required=True)
    registry_serve = registry_sub.add_parser("serve")
    registry_serve.add_argument("--host", default=os.environ.get("HYPERGERY_REGISTRY_HOST", "127.0.0.1"))
    registry_serve.add_argument("--port", type=int, default=int(os.environ.get("HYPERGERY_REGISTRY_PORT", "8765")))
    registry_serve.add_argument("--db-path", default=os.environ.get("HYPERGERY_REGISTRY_DB", ""))
    registry_serve.add_argument("--offline-timeout", type=int, default=int(os.environ.get("HYPERGERY_REGISTRY_OFFLINE_TIMEOUT", "90")))
    registry_serve.add_argument("--token", default="", help="Hub auth token. Default: HYPERGERY_HUB_TOKEN or auto-generated hub_token file next to the DB.")
    registry_serve.add_argument("--no-auth", action="store_true", help="DANGEROUS: disable Hub authentication (trusted LAN only).")
    registry_health = registry_sub.add_parser("health")
    registry_health.add_argument("--registry-url", default=default_hub_url())
    hub_parser = sub.add_parser("hub", help="Run or query the HyperGery Hub control plane.")
    hub_sub = hub_parser.add_subparsers(dest="hub_command", required=True)
    hub_serve = hub_sub.add_parser("serve")
    hub_serve.add_argument("--host", default=os.environ.get("HYPERGERY_HUB_HOST", "127.0.0.1"))
    hub_serve.add_argument("--port", type=int, default=int(os.environ.get("HYPERGERY_HUB_PORT", "8765")))
    hub_serve.add_argument("--db-path", default=os.environ.get("HYPERGERY_HUB_DB", os.environ.get("HYPERGERY_REGISTRY_DB", "")))
    hub_serve.add_argument("--offline-timeout", type=int, default=int(os.environ.get("HYPERGERY_HUB_OFFLINE_TIMEOUT", os.environ.get("HYPERGERY_REGISTRY_OFFLINE_TIMEOUT", "90"))))
    hub_serve.add_argument("--staging-dir", default=os.environ.get("HYPERGERY_HUB_STAGING", ""))
    hub_serve.add_argument("--token", default="", help="Hub auth token. Default: HYPERGERY_HUB_TOKEN or auto-generated hub_token file next to the DB.")
    hub_serve.add_argument("--no-auth", action="store_true", help="DANGEROUS: disable Hub authentication (trusted LAN only).")
    hub_health = hub_sub.add_parser("health")
    hub_health.add_argument("--hub-url", default=default_hub_url())
    hub_pairing = hub_sub.add_parser("pairing-info", help="Print the Hub URL and token for pairing another host or the mobile app. The token is a SECRET.")
    hub_pairing.add_argument("--hub-url", default=default_hub_url())
    hub_pairing.add_argument("--db-path", default=os.environ.get("HYPERGERY_HUB_DB", os.environ.get("HYPERGERY_REGISTRY_DB", "")))
    hub_init = hub_sub.add_parser("init-db")
    hub_init.add_argument("--db-path", default=os.environ.get("HYPERGERY_HUB_DB", os.environ.get("HYPERGERY_REGISTRY_DB", "")))
    hub_vms = hub_sub.add_parser("vms")
    hub_vms.add_argument("host_id", nargs="?")
    hub_vms.add_argument("--hub-url", default=default_hub_url())
    hub_packages = hub_sub.add_parser("packages", help="List Hub staging packages with size, age, and migration status.")
    hub_packages.add_argument("--hub-url", default=default_hub_url())
    hub_cleanup = hub_sub.add_parser(
        "cleanup-staging",
        help="Preview or delete leftover Hub staging packages. Dry-run unless --confirm is given.",
    )
    hub_cleanup.add_argument("--older-than-hours", type=float, default=24.0)
    hub_cleanup.add_argument("--dry-run", action="store_true", help="Preview only (default behavior without --confirm).")
    hub_cleanup.add_argument("--confirm", action="store_true", help="Actually delete the cleanup candidates.")
    hub_cleanup.add_argument("--include-failed", action="store_true", help="Also clean packages of failed/rolled back migrations.")
    hub_cleanup.add_argument("--no-orphans", action="store_true", help="Do not clean packages without a Hub migration record.")
    hub_cleanup.add_argument("--hub-url", default=default_hub_url())
    agent_parser = sub.add_parser("agent", help="Run the HyperGery host agent.")
    agent_sub = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_run = agent_sub.add_parser("run")
    agent_run.add_argument("--config", default="")
    agent_once = agent_sub.add_parser("once")
    agent_once.add_argument("--config", default="")
    agent_config = agent_sub.add_parser("config")
    agent_config_sub = agent_config.add_subparsers(dest="config_command", required=True)
    agent_config_show = agent_config_sub.add_parser("show")
    agent_config_show.add_argument("--config", default="")
    host_parser = sub.add_parser("host", help="Query registry hosts and queue safe host commands.")
    host_sub = host_parser.add_subparsers(dest="host_command", required=True)
    host_list = host_sub.add_parser("list")
    host_list.add_argument("--hub-url", "--registry-url", dest="hub_url", default=default_hub_url())
    host_show = host_sub.add_parser("show")
    host_show.add_argument("host_id")
    host_show.add_argument("--hub-url", "--registry-url", dest="hub_url", default=default_hub_url())
    host_test = host_sub.add_parser("test")
    host_test.add_argument("host_id")
    host_test.add_argument("--hub-url", "--registry-url", dest="hub_url", default=default_hub_url())
    host_test.add_argument(
        "--wait",
        action="store_true",
        help="Wait for the agent to answer the ping; without it the command is queued and returned immediately.",
    )
    host_test.add_argument("--timeout", type=float, default=30.0, help="Max seconds to wait (only with --wait).")
    host_test.add_argument("--interval", type=float, default=1.0)
    migrate_parser = sub.add_parser("migrate", help="Create, validate, import, and inspect safe VM migration packages.")
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_command", required=True)
    migrate_preflight = migrate_sub.add_parser("preflight", help="Check whether a VM can be packaged safely.")
    migrate_preflight.add_argument("vm_name")
    migrate_preflight.add_argument("--target-host", default="")
    migrate_preflight.add_argument("--target-vm-name", default="")
    migrate_preflight.add_argument("--nas-path", default="")
    migrate_preflight.add_argument("--allow-paused", action="store_true")
    migrate_preflight.add_argument("--no-iso", action="store_true")
    migrate_preflight.add_argument("--no-snapshots", action="store_true")
    migrate_package = migrate_sub.add_parser("package", help="Export a shutoff VM into a NAS migration package.")
    migrate_package.add_argument("vm_name")
    migrate_package.add_argument("output_dir")
    migrate_package.add_argument("--target-vm-name", default="")
    migrate_package.add_argument("--allow-paused", action="store_true")
    migrate_package.add_argument("--no-iso", action="store_true")
    migrate_package.add_argument("--no-snapshots", action="store_true")
    migrate_validate = migrate_sub.add_parser("validate-package", help="Verify a migration package manifest and checksums.")
    migrate_validate.add_argument("package_dir")
    migrate_import = migrate_sub.add_parser("import", help="Import a validated migration package on this host.")
    migrate_import.add_argument("package_dir")
    migrate_import.add_argument("--target-vm-name", default="")
    migrate_import.add_argument("--target-lab-id", default="")
    migrate_list = migrate_sub.add_parser("list", help="List migration packages under a path.")
    migrate_list.add_argument("--path", default=".")
    migrate_status = migrate_sub.add_parser("status", help="Show package status and validation summary.")
    migrate_status.add_argument("package_dir", nargs="?")
    migrate_status.add_argument("--migration-id", default="")
    migrate_status.add_argument("--hub-url", "--registry-url", dest="registry_url", default=default_hub_url())
    migrate_remote = migrate_sub.add_parser("remote", help="Package a VM and queue target import through the registry.")
    migrate_remote.add_argument("vm_name")
    migrate_remote.add_argument("--transfer", choices=("nas", "hub"), default="nas", help="nas: shared NAS path visible on both hosts; hub: upload through the Hub, no shared mount needed.")
    migrate_remote.add_argument("--nas-path", default="", help="Required for --transfer nas.")
    migrate_remote.add_argument("--source-host-id", required=True)
    migrate_remote.add_argument("--target-host-id", required=True)
    migrate_remote.add_argument("--target-vm-name", default="")
    migrate_remote.add_argument("--target-lab-id", default="")
    migrate_remote.add_argument("--allow-paused", action="store_true")
    migrate_remote.add_argument("--no-iso", action="store_true")
    migrate_remote.add_argument("--no-snapshots", action="store_true")
    migrate_remote.add_argument("--start-after-import", action="store_true")
    migrate_remote.add_argument("--hub-url", "--registry-url", dest="registry_url", default=default_hub_url())
    setup_parser = sub.add_parser("setup", help="First Run Setup: estado, bundle Docker del Hub, prueba de conexión.")
    setup_sub = setup_parser.add_subparsers(dest="setup_command", required=True)
    setup_sub.add_parser("status", help="Show first-run status and chosen profile (never prints the token).")
    setup_sub.add_parser("wizard", help="Launch the graphical First Run wizard (requires a display).")
    setup_bundle = setup_sub.add_parser("generate-docker-bundle", help="Write the self-contained Hub Docker folder (compose, Dockerfile, source, docs). Runs nothing.")
    setup_bundle.add_argument("--output", default="dist/hypergery-hub-docker", help="Destination folder (default: dist/hypergery-hub-docker).")
    setup_test = setup_sub.add_parser("test-hub", help="Test Hub connectivity and token (states: ok / auth_error / unreachable).")
    setup_test.add_argument("--url", default="", help="Hub URL (default: configured hub_url).")
    setup_test.add_argument("--token", default="", help="Hub token (default: configured hub_token).")
    setup_sub.add_parser("reset-first-run", help="Clear first_run_completed so the wizard shows again on next launch.")
    from .v1.cli_v1 import add_v1_parser

    add_v1_parser(sub)
    args = parser.parse_args(argv)

    try:
        if args.command == "registry":
            if getattr(args, "db_path", "") == "":
                args.db_path = None
            return registry_action(args)
        if args.command == "hub":
            if getattr(args, "db_path", "") == "":
                args.db_path = None
            return hub_action(args)
        if args.command == "agent":
            return agent_action(args)
        if args.command == "host":
            return host_action(args)
        if args.command == "v1":
            from .v1.cli_v1 import v1_action

            return v1_action(args)
        if args.command == "doctor":
            return doctor_action()
        if args.command == "setup":
            return setup_action(args)
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
        if args.command == "lab":
            return lab_action(backend, args)
        if args.command == "template":
            return template_action(backend, args)
        if args.command == "lab-topology":
            return lab_topology_action(backend, args)
        if args.command == "lab-instantiate":
            return lab_instantiate_action(backend, args)
        if args.command == "migrate":
            return migrate_action(backend, args)
    except HyperGeryError as exc:
        # HG-BUG-0023: humanizar el stderr de virsh también fuera de la UI Qt.
        from .ui_qt.humanize import humanize_error_message

        print(f"ERROR: {humanize_error_message(str(exc))}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
