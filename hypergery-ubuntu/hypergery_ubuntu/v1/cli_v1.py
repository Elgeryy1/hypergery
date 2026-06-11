from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .battery import BatteryService
from .errors import HyperGeryError
from .hosts import HostRegistry
from .labsx import validate_lab
from .nas import NasService
from .networks import networks_from_labs, validate_networks
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
    orch_apply = orch_sub.add_parser("apply", help="Recompute the plan for ONE VM and apply it (requires --confirm).")
    orch_apply.add_argument("vm_id")
    orch_apply.add_argument("--local-only", action="store_true")
    orch_apply.add_argument("--confirm", action="store_true")

    migrate_journal = v1_sub.add_parser(
        "migrate-journal",
        help="Inspect/clear in-flight live migrations (HG-BUG-0028 safety journal).",
    )
    journal_sub = migrate_journal.add_subparsers(dest="journal_command", required=True)
    journal_sub.add_parser("list", help="List VMs with an unconfirmed migration that cannot be started.")
    journal_clear = journal_sub.add_parser(
        "clear",
        help="Clear a VM's migration journal entry (ONLY after confirming it is not running on the target).",
    )
    journal_clear.add_argument("vm_name")
    migrate_live = v1_sub.add_parser(
        "migrate-live",
        help="LIVE migration (RAM+CPU, VM running) to another host via qemu+ssh:// or qemu+tls://.",
    )
    migrate_live.add_argument("--vm", required=True)
    migrate_live.add_argument("--target", required=True, help="Target libvirt URI (qemu+ssh://user@host/system).")
    storage = migrate_live.add_mutually_exclusive_group()
    storage.add_argument("--shared-storage", action="store_true", help="Disks are on shared storage (no copy).")
    storage.add_argument("--block-migration", action="store_true", help="Copy disks over the migration channel.")
    migrate_live.add_argument("--incremental", action="store_true", help="--copy-storage-inc (shared base image).")
    migrate_live.add_argument("--postcopy", action="store_true")
    migrate_live.add_argument("--no-auto-converge", action="store_true")
    migrate_live.add_argument("--bandwidth-mibps", type=int, default=0)
    migrate_live.add_argument("--timeout", type=int, default=1800)
    migrate_live.add_argument("--keep-source-definition", action="store_true", help="Do not undefine the source after confirming the target.")
    migrate_live.add_argument("--confirm", action="store_true", help="Required: this MOVES a running VM.")
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

    gpu = v1_sub.add_parser("gpu", help="GPU passthrough (VFIO/PCI): detect, preflight, bind, attach.")
    gpu_sub = gpu.add_subparsers(dest="gpu_command", required=True)
    gpu_sub.add_parser("list", help="List GPUs with driver, boot_vga and IOMMU group (read-only).")
    gpu_sub.add_parser("iommu", help="IOMMU status (read-only).")
    gpu_sub.add_parser("propose-host-changes", help="Print the GRUB/initramfs changes needed for VFIO. Never applies them.")
    gpu_pre = gpu_sub.add_parser("preflight", help="Check whether a GPU can be passed through (read-only).")
    gpu_pre.add_argument("address", help="PCI address, e.g. 0000:01:00.0")
    gpu_bind = gpu_sub.add_parser(
        "bind", help="Bind a GPU and its whole IOMMU group to vfio-pci (detaches them from the host; needs root)."
    )
    gpu_bind.add_argument("address")
    gpu_bind.add_argument("--confirm", action="store_true")
    gpu_unbind = gpu_sub.add_parser("unbind", help="Return a vfio-pci device (and its IOMMU group) to the host.")
    gpu_unbind.add_argument("address")
    gpu_unbind.add_argument(
        "--driver", default="", help="Original driver to rebind (single device; default: whole group via drivers_probe)."
    )
    gpu_attach = gpu_sub.add_parser("attach", help="Add the GPU <hostdev> to a SHUT OFF VM (requires --confirm).")
    gpu_attach.add_argument("--vm", required=True)
    gpu_attach.add_argument("--gpu", required=True, help="PCI address")
    gpu_attach.add_argument("--confirm", action="store_true")
    backup = v1_sub.add_parser("backup", help="NAS backup policies and backup verification.")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True)
    backup_add = backup_sub.add_parser("policy-add", help="Create a backup policy for a VM.")
    backup_add.add_argument("vm_name")
    backup_add.add_argument("--target-dir", required=True, help="NAS directory that will hold the packages.")
    backup_add.add_argument("--interval-hours", type=float, default=24.0)
    backup_add.add_argument("--retention", type=int, default=3)
    backup_add.add_argument("--include-iso", action="store_true")
    backup_sub.add_parser("policy-list", help="List backup policies.")
    backup_remove = backup_sub.add_parser("policy-remove")
    backup_remove.add_argument("policy_id")
    backup_run = backup_sub.add_parser("run", help="Run one policy now.")
    backup_run.add_argument("policy_id")
    backup_sub.add_parser("run-due", help="Run every policy whose interval has elapsed (cron-friendly).")
    backup_verify = backup_sub.add_parser("verify", help="Restore a backup package into a temporary hgtest- VM and check it boots.")
    backup_verify.add_argument("package_dir")
    backup_verify.add_argument("--boot-timeout", type=int, default=60)
    backup_verify.add_argument("--keep-vm", action="store_true")
    guests = v1_sub.add_parser("guests", help="Local RBAC users.")
    guests_sub = guests.add_subparsers(dest="guests_command", required=True)
    guests_sub.add_parser("list", help="List users with effective permissions.")
    guests_token = guests_sub.add_parser("token", help="Issue (or revoke) an API bearer token for a user. Prints the SECRET token once.")
    guests_token.add_argument("user_id")
    guests_token.add_argument("--revoke", action="store_true", help="Revoke the user's tokens instead of issuing one.")

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
    if args.v1_command == "orchestrator" and args.orchestrator_command == "apply":
        from .orchestrator import apply_plan
        from .teleport import TeleportEngine

        registry = HostRegistry(settings=settings, telemetry=telemetry, hub_client=_hub_client())
        hosts = registry.list_hosts()
        backend = _local_backend()
        vms = []
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
        )
        plan = next((p for p in plans if p.vm_id == args.vm_id), None)
        if plan is None:
            raise HyperGeryError(f"No plan found for VM: {args.vm_id}")
        engine = TeleportEngine(backend, settings=settings, hub_client=_hub_client()) if backend is not None else None
        return _print_json(apply_plan(plan, teleport_engine=engine, confirm=args.confirm))
    if args.v1_command == "migrate-journal":
        from ..migration_journal import MigrationJournal

        journal = MigrationJournal()
        if args.journal_command == "list":
            return _print_json({"in_flight": journal.list()})
        if args.journal_command == "clear":
            cleared = journal.clear(args.vm_name)
            return _print_json({"vm_name": args.vm_name, "cleared": cleared})
        return 2
    if args.v1_command == "migrate-live":
        if not args.confirm:
            raise HyperGeryError("migrate-live requires --confirm (it moves a RUNNING VM between hosts).")
        backend = _local_backend()
        if backend is None:
            raise HyperGeryError("Live migration needs a local libvirt backend (virsh).")
        from .live_migration import LiveMigrationPlan, LiveMigrator
        from .progress import get_progress_channel

        shared = True if args.shared_storage else (False if args.block_migration else None)
        plan = LiveMigrationPlan(
            vm_name=args.vm,
            target_uri=args.target,
            shared_storage=shared,
            incremental_storage=args.incremental,
            auto_converge=not args.no_auto_converge,
            postcopy=args.postcopy,
            bandwidth_mibps=args.bandwidth_mibps,
            timeout_seconds=args.timeout,
            undefine_source_on_success=not args.keep_source_definition,
        )
        migrator = LiveMigrator(backend, plan, channel=get_progress_channel())
        result = migrator.run()
        _print_json(result)
        return 0 if result["ok"] else 1
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
        networks = networks_from_labs(store.list_labs())
        result = validate_networks(networks)
        _print_json({"networks": [network.to_dict() for network in networks], **result})
        return 0 if result["ok"] else 1
    if args.v1_command == "gpu":
        from . import gpu_passthrough as gpu_mod

        if args.gpu_command == "list":
            return _print_json({"gpus": gpu_mod.list_pci_gpus()})
        if args.gpu_command == "iommu":
            return _print_json(gpu_mod.iommu_status())
        if args.gpu_command == "propose-host-changes":
            return _print_json(gpu_mod.propose_host_changes())
        if args.gpu_command == "preflight":
            result = gpu_mod.preflight_gpu_passthrough(args.address)
            _print_json(result)
            return 0 if result["ok"] else 1
        if args.gpu_command == "bind":
            return _print_json(gpu_mod.VfioBinder().bind_group_to_vfio(args.address, confirm=args.confirm))
        if args.gpu_command == "unbind":
            if args.driver:
                return _print_json(gpu_mod.VfioBinder().unbind_from_vfio(args.address, args.driver))
            return _print_json(gpu_mod.VfioBinder().unbind_group_from_vfio(args.address))
        if args.gpu_command == "attach":
            backend = _local_backend()
            if backend is None:
                raise HyperGeryError("GPU attach needs a local libvirt backend.")
            return _print_json(gpu_mod.attach_gpu_to_vm(backend, args.vm, args.gpu, confirm=args.confirm))
        return 2
    if args.v1_command == "backup":
        from ..backend import HyperGeryBackend
        from .backups import BackupPolicyStore, new_policy, run_due, run_policy

        store = BackupPolicyStore()
        if args.backup_command == "policy-add":
            policy = store.add(
                new_policy(
                    args.vm_name,
                    args.target_dir,
                    interval_hours=args.interval_hours,
                    retention=args.retention,
                    include_iso=args.include_iso,
                )
            )
            _print_json(policy.to_dict())
            return 0
        if args.backup_command == "policy-list":
            _print_json({"policies": [policy.to_dict() for policy in store.list()]})
            return 0
        if args.backup_command == "policy-remove":
            _print_json({"policy_id": args.policy_id, "removed": store.remove(args.policy_id)})
            return 0
        if args.backup_command == "run":
            result = run_policy(HyperGeryBackend(), store.get(args.policy_id), store)
            _print_json(result)
            return 0 if result["ok"] else 1
        if args.backup_command == "run-due":
            results = run_due(HyperGeryBackend(), store)
            _print_json({"results": results})
            return 0 if all(r["ok"] for r in results) else 1
        if args.backup_command == "verify":
            from .backup_verifier import verify_backup

            result = verify_backup(
                HyperGeryBackend(),
                args.package_dir,
                boot_timeout_seconds=args.boot_timeout,
                keep_vm=args.keep_vm,
            )
            _print_json(result)
            return 0 if result["ok"] else 1
        return 2
    if args.v1_command == "guests" and args.guests_command == "token":
        from .auth import ApiTokenStore

        store = ApiTokenStore()
        if args.revoke:
            removed = store.revoke(args.user_id)
            _print_json({"user_id": args.user_id, "revoked_tokens": removed})
            return 0
        UserStore().get_user(args.user_id)  # valida que el usuario existe
        token = store.issue(args.user_id)
        print("ADVERTENCIA: el token es un secreto; se muestra una sola vez.", file=sys.stderr)
        _print_json({"user_id": args.user_id, "token": token})
        return 0
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
