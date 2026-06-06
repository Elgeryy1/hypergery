from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..migration import (
    export_vm_package,
    import_vm_package,
    migration_preflight,
    start_remote_migration,
    validate_vm_package,
)
from .errors import HostOfflineError, TeleportError
from .hglog import get_logger, new_operation_id, now_iso
from .memdiff import produce_delta, snapshot_state
from .settings import TELEPORT_MODES, V1Settings

__all__ = ["TELEPORT_MODES", "TeleportEngine"]


class TeleportEngine:
    """Move VM workloads between hosts, safely and observably.

    Modes:
    - ``dry_run``: validate everything, copy nothing.
    - ``local_loopback``: export → import on the same host under a new name
      (full pipeline validation without a remote machine).
    - ``suspend_copy_start``: the functional real move — suspend/stop if
      needed, package, transfer via Hub/NAS, queue the remote import, start.
    - ``experimental_memdiff``: dry-run plus a block-delta estimate against a
      previous state snapshot (requires the experimental flag).

    Failure semantics: the source VM and its disks are never deleted; if the
    engine paused the VM it resumes it; failures return/raise with recovery
    instructions instead of half-applied state.
    """

    def __init__(
        self,
        backend: Any,
        *,
        settings: V1Settings | None = None,
        hub_client: Any | None = None,
        source_host_id: str = "",
    ) -> None:
        self.backend = backend
        self.settings = settings or V1Settings()
        self.hub_client = hub_client
        if not source_host_id:
            from ..config import effective_value

            source_host_id = effective_value("host_id")
        self.source_host_id = source_host_id

    # ------------------------------------------------------------------ #

    def _write_teleport_manifest(self, package_dir: Path, payload: dict[str, Any]) -> None:
        try:
            (package_dir / "teleport_manifest.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError:
            get_logger().warning("teleport", f"Cannot write teleport manifest in {package_dir}")

    def _target_online(self, target_host_id: str) -> dict[str, Any]:
        if self.hub_client is None:
            raise TeleportError("This teleport mode needs a Hub client to reach the target host.")
        try:
            record = self.hub_client.get_host(target_host_id)
        except Exception as exc:
            raise HostOfflineError(f"Target host is not reachable through the Hub: {target_host_id}: {exc}") from exc
        if str(record.get("status") or "offline") != "online":
            raise HostOfflineError(f"Target host is offline: {target_host_id}")
        return record

    # ------------------------------------------------------------------ #

    def teleport_vm(
        self,
        vm_name: str,
        *,
        mode: str | None = None,
        target_host_id: str = "",
        target_vm_name: str = "",
        staging_dir: str | Path | None = None,
        memdiff_base_state: str | Path | None = None,
        start_after_import: bool = True,
        include_iso: bool = True,
        include_snapshots: bool = True,
    ) -> dict[str, Any]:
        mode = mode or self.settings.teleport_default_mode
        if mode not in TELEPORT_MODES:
            raise TeleportError(f"Unsupported teleport mode: {mode}. Allowed: {', '.join(TELEPORT_MODES)}")
        if mode == "experimental_memdiff" and not self.settings.experimental_memdiff:
            raise TeleportError("experimental_memdiff mode requires the experimental_memdiff settings flag.")
        operation_id = new_operation_id("teleport")
        log = get_logger()
        log.info(
            "teleport",
            f"teleport {mode} requested for {vm_name}",
            vm_id=vm_name,
            host=self.source_host_id,
            operation_id=operation_id,
            details={"target_host_id": target_host_id, "include_iso": include_iso},
        )
        try:
            if mode in {"dry_run", "experimental_memdiff"}:
                return self._dry_run(vm_name, mode, target_host_id, operation_id, memdiff_base_state, include_iso)
            if mode == "local_loopback":
                return self._local_loopback(vm_name, target_vm_name, staging_dir, operation_id, include_iso, include_snapshots)
            if mode == "save_restore":
                return self._save_restore(vm_name, target_host_id, staging_dir, operation_id)
            return self._suspend_copy_start(
                vm_name, target_host_id, target_vm_name, staging_dir, operation_id, start_after_import,
                include_iso, include_snapshots,
            )
        except (TeleportError, HostOfflineError):
            raise
        except Exception as exc:
            log.error("teleport", f"teleport {mode} failed for {vm_name}: {exc}", vm_id=vm_name, operation_id=operation_id)
            raise TeleportError(
                f"Teleport failed: {exc}. The source VM and its disks were not deleted; "
                "check the structured log for this operation_id and retry once the cause is fixed."
            ) from exc

    # Modes ------------------------------------------------------------ #

    def _dry_run(
        self,
        vm_name: str,
        mode: str,
        target_host_id: str,
        operation_id: str,
        memdiff_base_state: str | Path | None,
        include_iso: bool = True,
    ) -> dict[str, Any]:
        preflight = migration_preflight(
            self.backend, vm_name, target_vm_name=f"{vm_name}-teleport", allow_paused=True, include_iso=include_iso
        )
        target_check: dict[str, Any] = {"checked": False}
        if target_host_id and self.hub_client is not None:
            try:
                record = self._target_online(target_host_id)
                target_check = {
                    "checked": True,
                    "online": True,
                    "ram_free_mib": int(record.get("ram_free_mib") or 0),
                    "disk_free_mib": int(record.get("disk_free_mib") or 0),
                }
            except HostOfflineError as exc:
                target_check = {"checked": True, "online": False, "error": str(exc)}
        result: dict[str, Any] = {
            "operation_id": operation_id,
            "mode": mode,
            "vm_name": vm_name,
            "source_host_id": self.source_host_id,
            "target_host_id": target_host_id,
            "dry_run": True,
            "ok": bool(preflight.get("ok")) and target_check.get("online", True),
            "preflight": preflight,
            "target_check": target_check,
            "created_at": now_iso(),
        }
        if mode == "experimental_memdiff":
            estimate: dict[str, Any] = {"available": False, "reason": "no base state provided"}
            disk_path = ""
            try:
                disk_path = str(self.backend.get_vm(vm_name).disk_path or "")
            except Exception:
                pass
            if memdiff_base_state and disk_path and Path(disk_path).is_file():
                base = snapshot_state(memdiff_base_state)
                delta = produce_delta(base, disk_path)
                estimate = {"available": True, **delta.savings_estimate()}
            result["memdiff"] = {"experimental": True, "estimate": estimate}
        return result

    def _local_loopback(
        self,
        vm_name: str,
        target_vm_name: str,
        staging_dir: str | Path | None,
        operation_id: str,
        include_iso: bool = True,
        include_snapshots: bool = True,
    ) -> dict[str, Any]:
        if staging_dir is None:
            raise TeleportError("local_loopback needs a staging_dir for the package.")
        target_vm_name = target_vm_name or f"{vm_name}-loopback"
        staging = Path(staging_dir).expanduser()
        export = export_vm_package(
            self.backend, vm_name, staging, target_vm_name=target_vm_name, allow_paused=True,
            include_iso=include_iso, include_snapshots=include_snapshots,
        )
        package_dir = Path(export["package_dir"])
        self._write_teleport_manifest(
            package_dir,
            {
                "operation_id": operation_id,
                "mode": "local_loopback",
                "vm_name": vm_name,
                "target_vm_name": target_vm_name,
                "source_host_id": self.source_host_id,
                "target_host_id": self.source_host_id,
                "created_at": now_iso(),
            },
        )
        validation = validate_vm_package(package_dir)
        if not validation["ok"]:
            raise TeleportError(f"Loopback package failed validation: {'; '.join(validation['errors'])}")
        try:
            imported = import_vm_package(self.backend, package_dir, target_vm_name=target_vm_name)
        except Exception as exc:
            raise TeleportError(
                f"Loopback import failed: {exc}. Source VM untouched; staged package kept at {package_dir} for inspection."
            ) from exc
        get_logger().info(
            "teleport",
            f"local_loopback done: {vm_name} → {target_vm_name}",
            vm_id=vm_name,
            operation_id=operation_id,
        )
        return {
            "operation_id": operation_id,
            "mode": "local_loopback",
            "vm_name": vm_name,
            "target_vm_name": imported.get("target_vm_name", target_vm_name),
            "package_dir": str(package_dir),
            "dry_run": False,
            "ok": True,
            "imported": imported,
        }

    def _save_restore(
        self,
        vm_name: str,
        target_host_id: str,
        staging_dir: str | Path | None,
        operation_id: str,
    ) -> dict[str, Any]:
        """State-preserving teleport: freeze the running VM, dump its RAM+CPU
        state, ship disk+state through the Hub, and have the target agent
        restore it so it CONTINUES where it left off (not a reboot). The source
        ends shut off (its state now lives on the target); nothing is deleted.
        """
        from ..migration import hub_transfer_staging_dir
        from .state_migration import export_vm_state_package

        if self.hub_client is None:
            raise TeleportError("save_restore needs a Hub client to reach the target host.")
        self._target_online(target_host_id)
        from .state_migration import MEMSTATE_FILENAME

        out_dir = Path(staging_dir).expanduser() if staging_dir else hub_transfer_staging_dir(self.backend) / "state-outgoing"
        out_dir.mkdir(parents=True, exist_ok=True)
        # This freezes the VM and captures its full state into the package.
        export = export_vm_state_package(self.backend, vm_name, out_dir)
        package_dir = export["package_dir"]
        memstate = Path(package_dir) / MEMSTATE_FILENAME
        migration_id = f"state-{vm_name}-{operation_id.split('-')[-1]}"

        def resume_source_locally(reason: str) -> str:
            """Bring the just-frozen source VM back to running from its saved
            state so a shipping failure never leaves it stopped."""
            try:
                self.backend.restore_vm(memstate)
                get_logger().warning(
                    "teleport",
                    f"save_restore shipping failed for {vm_name}; resumed it locally from saved state",
                    vm_id=vm_name,
                    operation_id=operation_id,
                    details={"reason": reason},
                )
                return "resumed locally (continues where it was)"
            except Exception as resume_exc:
                get_logger().error(
                    "teleport",
                    f"save_restore shipping failed AND local resume failed for {vm_name}",
                    vm_id=vm_name,
                    operation_id=operation_id,
                    details={"resume_error": str(resume_exc)},
                )
                return (
                    f"left shut off with its state preserved in {package_dir} "
                    f"(automatic resume failed: {resume_exc}; restore it with: virsh restore {memstate})"
                )

        # Reading the saved state to upload it requires the invoking user to
        # be able to read the libvirt state file. On qemu:///system the file is
        # root-owned, so detect that early and resume the VM instead of failing
        # mid-upload.
        try:
            with memstate.open("rb"):
                pass
        except OSError as exc:
            recovery = resume_source_locally("state file not readable for transfer")
            raise TeleportError(
                f"save_restore cannot ship {vm_name}: its libvirt saved-state file is not readable by "
                f"this user ({exc}). Cross-host state migration needs read access to the state file "
                "(run libvirt as the session user, or use suspend_copy_start). Source VM " + recovery + "."
            ) from exc

        try:
            self.hub_client.upload_package(migration_id, package_dir)
            command = self.hub_client.create_command(
                target_host_id, "restore_vm_state_package", {"migration_id": migration_id}
            )
        except Exception as exc:
            recovery = resume_source_locally(str(exc))
            raise TeleportError(
                f"save_restore failed while shipping {vm_name}: {exc}. Source VM " + recovery + "."
            ) from exc
        get_logger().info(
            "teleport",
            f"save_restore queued: {vm_name} -> {target_host_id} (state preserved)",
            vm_id=vm_name,
            host=self.source_host_id,
            operation_id=operation_id,
            details={"migration_id": migration_id, "command_id": command.get("command_id", "")},
        )
        return {
            "operation_id": operation_id,
            "mode": "save_restore",
            "vm_name": vm_name,
            "target_host_id": target_host_id,
            "migration_id": migration_id,
            "command_id": str(command.get("command_id") or ""),
            "state_preserved": True,
            "dry_run": False,
            "ok": True,
            "note": (
                "Running state captured and shipped; the target agent will RESTORE the VM so it "
                "continues from where it was (not a reboot). The source VM is shut off with its "
                "state already transferred; do not start it on the source after the target restores."
            ),
        }

    def _suspend_copy_start(
        self,
        vm_name: str,
        target_host_id: str,
        target_vm_name: str,
        staging_dir: str | Path | None,
        operation_id: str,
        start_after_import: bool,
        include_iso: bool = True,
        include_snapshots: bool = True,
    ) -> dict[str, Any]:
        if not target_host_id:
            raise TeleportError("suspend_copy_start needs a target_host_id.")
        self._target_online(target_host_id)
        paused_here = False
        state = ""
        try:
            state = str(self.backend.vm_state(vm_name)).lower()
        except Exception:
            state = "unknown"
        if state == "running":
            result = self.backend.virsh(["suspend", vm_name], check=False)
            if result.returncode != 0:
                raise TeleportError(
                    f"Cannot suspend {vm_name} before teleport: {result.stderr.strip() or result.stdout.strip()}"
                )
            paused_here = True
            get_logger().info("teleport", f"suspended {vm_name} for teleport", vm_id=vm_name, operation_id=operation_id)
        try:
            # transfer="hub" computes its own staging dir on the source host;
            # start_remote_migration ignores nas_path in hub mode, so any
            # staging_dir passed here is intentionally unused for this mode.
            outcome = start_remote_migration(
                self.backend,
                self.hub_client,
                vm_name,
                staging_dir or "",
                source_host_id=self.source_host_id,
                target_host_id=target_host_id,
                target_vm_name=target_vm_name or f"{vm_name}-teleport",
                allow_paused=True,
                include_iso=include_iso,
                include_snapshots=include_snapshots,
                start_after_import=start_after_import,
                transfer="hub",
            )
        except Exception as exc:
            recovery = state
            if paused_here:
                resume = self.backend.virsh(["resume", vm_name], check=False)
                if resume.returncode == 0:
                    recovery = "resumed"
                    get_logger().warning(
                        "teleport", f"teleport failed; resumed {vm_name}", vm_id=vm_name, operation_id=operation_id
                    )
                else:
                    recovery = "still paused (automatic resume failed — resume it manually)"
                    get_logger().error(
                        "teleport",
                        f"teleport failed AND resume failed for {vm_name}; VM is still paused",
                        vm_id=vm_name,
                        operation_id=operation_id,
                        details={"resume_error": resume.stderr.strip() or resume.stdout.strip()},
                    )
            raise TeleportError(
                f"suspend_copy_start failed: {exc}. Source VM left {recovery}; nothing was deleted."
            ) from exc
        get_logger().info(
            "teleport",
            f"suspend_copy_start queued: {vm_name} → {target_host_id}",
            vm_id=vm_name,
            host=self.source_host_id,
            operation_id=operation_id,
            details={"migration_id": outcome.get("migration_id", ""), "command_id": outcome.get("command_id", "")},
        )
        return {
            "operation_id": operation_id,
            "mode": "suspend_copy_start",
            "vm_name": vm_name,
            "target_host_id": target_host_id,
            "suspended_source": paused_here,
            "dry_run": False,
            "ok": True,
            "migration": outcome,
            "note": (
                "Remote import queued through the Hub; poll the migration/command for completion. "
                "The source VM stays paused until you decide to stop or resume it after verifying the target."
            ),
        }
