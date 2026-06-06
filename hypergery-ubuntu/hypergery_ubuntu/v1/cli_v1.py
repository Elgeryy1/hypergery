from __future__ import annotations

import argparse
import json
from typing import Any

from .battery import BatteryService
from .errors import HyperGeryError
from .hosts import HostRegistry
from .labsx import validate_lab
from .nas import NasService
from .networks import network_from_lab, validate_networks
from .orchestrator import OrchestratorService
from .rbac import UserStore
from .settings import V1Settings
from .telemetry import TelemetryService, evaluate_alerts

__all__ = ["add_v1_parser", "v1_action"]


def _print_json(data: Any) -> int:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))
    return 0


def _hub_client() -> Any | None:
    from ..registry import RegistryClient

    try:
        return RegistryClient()
    except Exception:
        return None


def _lab_store() -> Any:
    from ..backend import xdg_data_home
    from ..labs import LabStore

    return LabStore(xdg_data_home())


def _local_backend() -> Any | None:
    try:
        from ..backend import HyperGeryBackend

        return HyperGeryBackend()
    except Exception:
        return None


def add_v1_parser(sub: argparse._SubParsersAction) -> None:
    v1 = sub.add_parser("v1", help="v0.9/v1 services: telemetry, orchestrator, battery, NAS commit, teleport, API.")
    v1_sub = v1.add_subparsers(dest="v1_command", required=True)

    v1_sub.add_parser("health", help="Local + Hub + NAS health summary.")
    v1_sub.add_parser("hosts", help="Unified host registry (local + Hub).")
    v1_sub.add_parser("telemetry", help="Local telemetry sample and alerts.")
    v1_sub.add_parser("battery", help="Battery state, tier, and recommended actions.")

    labs = v1_sub.add_parser("labs", help="v0.9 labs workspace helpers.")
    labs_sub = labs.add_subparsers(dest="labs_command", required=True)
    labs_validate = labs_sub.add_parser("validate", help="Validate one lab (or all labs).")
    labs_validate.add_argument("lab_id", nargs="?")

    nas = v1_sub.add_parser("nas", help="NAS health, commits, and restore.")
    nas_sub = nas.add_subparsers(dest="nas_command", required=True)
    nas_sub.add_parser("status", help="NAS health and last commits.")
    nas_commit = nas_sub.add_parser("commit", help="Commit a lab to the NAS (dry-run unless --confirm).")
    nas_commit.add_argument("--lab", required=True)
    nas_commit.add_argument("--include-disks", action="store_true")
    nas_commit.add_argument("--dry-run", action="store_true", help="Preview only (default without --confirm).")
    nas_commit.add_argument("--confirm", action="store_true", help="Actually write the commit to the NAS.")
    nas_restore = nas_sub.add_parser("restore", help="Restore a commit package (dry-run unless --confirm).")
    nas_restore.add_argument("--lab", required=True)
    nas_restore.add_argument("--commit-id", required=True)
    nas_restore.add_argument("--destination", required=True)
    nas_restore.add_argument("--confirm", action="store_true")

    orchestrator = v1_sub.add_parser("orchestrator", help="Auto-Boost placement plans.")
    orch_sub = orchestrator.add_subparsers(dest="orchestrator_command", required=True)
    orch_plan = orch_sub.add_parser("plan", help="Generate an explainable placement plan (never executes).")
    orch_plan.add_argument("--lab", default="")
    orch_plan.add_argument("--local-only", action="store_true")

    teleport = v1_sub.add_parser("teleport", help="Teleport engine (dry-run / loopback).")
    teleport_sub = teleport.add_subparsers(dest="teleport_command", required=True)
    teleport_dry = teleport_sub.add_parser("dry-run", help="Validate a teleport without copying anything.")
    teleport_dry.add_argument("--vm", required=True)
    teleport_dry.add_argument("--target", default="")
    teleport_dry.add_argument("--no-iso", action="store_true", help="Do not require/transfer the attached ISO.")
    teleport_loop = teleport_sub.add_parser("loopback", help="Local loopback teleport (export+import on this host).")
    teleport_loop.add_argument("--vm", required=True)
    teleport_loop.add_argument("--staging-dir", required=True)
    teleport_loop.add_argument("--target-vm-name", default="")
    teleport_loop.add_argument("--no-iso", action="store_true", help="Do not require/transfer the attached ISO.")
    teleport_state = teleport_sub.add_parser(
        "save-restore",
        help="State-preserving teleport: freeze a RUNNING VM and continue it on the target (not a reboot).",
    )
    teleport_state.add_argument("--vm", required=True)
    teleport_state.add_argument("--target", required=True)
    teleport_state.add_argument("--staging-dir", default="")

    network = v1_sub.add_parser("network", help="Lab network validation.")
    network_sub = network.add_subparsers(dest="network_command", required=True)
    network_sub.add_parser("validate", help="Validate all lab networks for conflicts.")

    guests = v1_sub.add_parser("guests", help="Local RBAC users.")
    guests_sub = guests.add_subparsers(dest="guests_command", required=True)
    guests_sub.add_parser("list", help="List users with effective permissions.")

    api = v1_sub.add_parser("api", help="Android-ready local API.")
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_serve = api_sub.add_parser("serve", help="Serve the v1 API (blocking).")
    api_serve.add_argument("--host", default="")
    api_serve.add_argument("--port", type=int, default=0)
    api_serve.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow binding to a non-loopback address (unauthenticated API; trusted LAN only).",
    )


def v1_action(args: argparse.Namespace) -> int:
    settings = V1Settings.load()
    telemetry = TelemetryService(settings=settings)
    if args.v1_command == "health":
        registry = HostRegistry(settings=settings, telemetry=telemetry, hub_client=_hub_client())
        hosts = registry.list_hosts()
        nas = NasService(settings=settings)
        return _print_json(
            {
                "hosts": [{"id": host.id, "status": host.status, "role": host.role} for host in hosts],
                "nas": nas.health(),
                "battery": BatteryService(settings=settings).read().to_dict(),
            }
        )
    if args.v1_command == "hosts":
        registry = HostRegistry(settings=settings, telemetry=telemetry, hub_client=_hub_client())
        return _print_json({"hosts": [host.to_dict() for host in registry.list_hosts()]})
    if args.v1_command == "telemetry":
        sample = telemetry.sample_local()
        telemetry.record(sample)
        return _print_json({"sample": sample.to_dict(), "alerts": evaluate_alerts(local_sample=sample, settings=settings)})
    if args.v1_command == "battery":
        service = BatteryService(settings=settings)
        state = service.read()
        return _print_json({"battery": state.to_dict(), "actions": service.recommended_actions(state)})
    if args.v1_command == "labs" and args.labs_command == "validate":
        store = _lab_store()
        labs = store.list_labs()
        if args.lab_id:
            lab = store.get_lab(args.lab_id)
            result = validate_lab(lab, existing_labs=labs)
            _print_json({"lab_id": args.lab_id, **result})
            return 0 if result["ok"] else 1
        results = {str(lab.get("lab_id")): validate_lab(lab, existing_labs=labs) for lab in labs}
        _print_json(results)
        return 0 if all(result["ok"] for result in results.values()) else 1
    if args.v1_command == "nas":
        store = _lab_store()
        nas = NasService(settings=settings, lab_store=store)
        if args.nas_command == "status":
            return _print_json({"health": nas.health(), "commits": nas.list_commits()[-20:]})
        if args.nas_command == "commit":
            # An explicit --dry-run always wins over --confirm: the safer
            # flag must never be silently overridden.
            dry_run = args.dry_run or not args.confirm
            result = nas.commit_lab(
                args.lab,
                include_disks=args.include_disks,
                dry_run=dry_run,
                existing_labs=store.list_labs(),
            )
            _print_json(result)
            return 0
        if args.nas_command == "restore":
            result = nas.restore_commit(args.lab, args.commit_id, args.destination, dry_run=not args.confirm)
            return _print_json(result)
    if args.v1_command == "orchestrator" and args.orchestrator_command == "plan":
        registry = HostRegistry(settings=settings, telemetry=telemetry, hub_client=_hub_client())
        hosts = registry.list_hosts()
        vms = []
        backend = _local_backend()
        if backend is not None:
            try:
                from .providers import LocalProvider

                vms = LocalProvider(backend).list_vms()
            except Exception:
                vms = []
        plans = OrchestratorService(settings=settings).plan(
            hosts=hosts,
            vms=vms,
            battery=BatteryService(settings=settings).read(),
            local_host_id=hosts[0].id if hosts else None,
            allow_remote=not args.local_only,
            lab_id=args.lab or None,
        )
        return _print_json({"plans": [plan.to_dict() for plan in plans]})
    if args.v1_command == "teleport":
        backend = _local_backend()
        if backend is None:
            raise HyperGeryError("Teleport needs a local libvirt backend.")
        from .teleport import TeleportEngine

        engine = TeleportEngine(backend, settings=settings, hub_client=_hub_client())
        if args.teleport_command == "dry-run":
            return _print_json(
                engine.teleport_vm(args.vm, mode="dry_run", target_host_id=args.target, include_iso=not args.no_iso)
            )
        if args.teleport_command == "loopback":
            return _print_json(
                engine.teleport_vm(
                    args.vm,
                    mode="local_loopback",
                    staging_dir=args.staging_dir,
                    target_vm_name=args.target_vm_name,
                    include_iso=not args.no_iso,
                )
            )
        if args.teleport_command == "save-restore":
            return _print_json(
                engine.teleport_vm(
                    args.vm,
                    mode="save_restore",
                    target_host_id=args.target,
                    staging_dir=args.staging_dir or None,
                )
            )
    if args.v1_command == "network" and args.network_command == "validate":
        store = _lab_store()
        networks = [network_from_lab(lab) for lab in store.list_labs()]
        result = validate_networks(networks)
        _print_json({"networks": [network.to_dict() for network in networks], **result})
        return 0 if result["ok"] else 1
    if args.v1_command == "guests" and args.guests_command == "list":
        users = UserStore().list_users()
        return _print_json(
            {"users": [{**user.to_dict(), "effective_permissions": sorted(user.permissions())} for user in users]}
        )
    if args.v1_command == "api" and args.api_command == "serve":
        from .api import ApiContext, serve_api
        from .providers import LocalProvider

        backend = _local_backend()
        local_vms = None
        if backend is not None:
            provider = LocalProvider(backend)

            def local_vms() -> list:
                try:
                    return provider.list_vms()
                except Exception:
                    return []

        hub = _hub_client()
        from .teleport import TeleportEngine

        context = ApiContext(
            settings=settings,
            lab_store=_lab_store(),
            nas=NasService(settings=settings, lab_store=_lab_store()),
            hub_client=hub,
            local_vms=local_vms,
            teleport_engine=TeleportEngine(backend, settings=settings, hub_client=hub) if backend is not None else None,
        )
        serve_api(context, host=args.host or None, port=args.port or None, allow_remote=args.allow_remote)
        return 0
    return 2
