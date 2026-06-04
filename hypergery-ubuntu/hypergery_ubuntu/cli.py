from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from .backend import HyperGeryBackend, HyperGeryError
from .labs import LabStore
from .templates import TemplateStore


def default_hub_url() -> str:
    return os.environ.get("HYPERGERY_HUB_URL") or os.environ.get("HYPERGERY_REGISTRY_URL") or "http://127.0.0.1:8765"


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


def print_json(data: object) -> int:
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


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


def hub_action(args: argparse.Namespace) -> int:
    from .registry import RegistryClient, RegistryStore, serve_registry

    if args.hub_command == "serve":
        serve_registry(
            args.host,
            args.port,
            db_path=args.db_path,
            offline_timeout_seconds=args.offline_timeout,
        )
        return 0
    if args.hub_command == "init-db":
        store = RegistryStore(args.db_path)
        return print_json({"ok": True, "db_path": str(store.db_path)})
    client = RegistryClient(args.hub_url)
    if args.hub_command == "health":
        return print_json(client.health())
    if args.hub_command == "vms":
        return print_json({"vms": client.list_vms(args.host_id or None)})
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
            )
        )
    return 2


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
    registry_health = registry_sub.add_parser("health")
    registry_health.add_argument("--registry-url", default=default_hub_url())
    hub_parser = sub.add_parser("hub", help="Run or query the HyperGery Hub control plane.")
    hub_sub = hub_parser.add_subparsers(dest="hub_command", required=True)
    hub_serve = hub_sub.add_parser("serve")
    hub_serve.add_argument("--host", default=os.environ.get("HYPERGERY_HUB_HOST", "127.0.0.1"))
    hub_serve.add_argument("--port", type=int, default=int(os.environ.get("HYPERGERY_HUB_PORT", "8765")))
    hub_serve.add_argument("--db-path", default=os.environ.get("HYPERGERY_HUB_DB", os.environ.get("HYPERGERY_REGISTRY_DB", "")))
    hub_serve.add_argument("--offline-timeout", type=int, default=int(os.environ.get("HYPERGERY_HUB_OFFLINE_TIMEOUT", os.environ.get("HYPERGERY_REGISTRY_OFFLINE_TIMEOUT", "90"))))
    hub_health = hub_sub.add_parser("health")
    hub_health.add_argument("--hub-url", default=default_hub_url())
    hub_init = hub_sub.add_parser("init-db")
    hub_init.add_argument("--db-path", default=os.environ.get("HYPERGERY_HUB_DB", os.environ.get("HYPERGERY_REGISTRY_DB", "")))
    hub_vms = hub_sub.add_parser("vms")
    hub_vms.add_argument("host_id", nargs="?")
    hub_vms.add_argument("--hub-url", default=default_hub_url())
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
    migrate_remote.add_argument("--nas-path", required=True)
    migrate_remote.add_argument("--source-host-id", required=True)
    migrate_remote.add_argument("--target-host-id", required=True)
    migrate_remote.add_argument("--target-vm-name", default="")
    migrate_remote.add_argument("--target-lab-id", default="")
    migrate_remote.add_argument("--allow-paused", action="store_true")
    migrate_remote.add_argument("--no-iso", action="store_true")
    migrate_remote.add_argument("--no-snapshots", action="store_true")
    migrate_remote.add_argument("--start-after-import", action="store_true")
    migrate_remote.add_argument("--hub-url", "--registry-url", dest="registry_url", default=default_hub_url())
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
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
