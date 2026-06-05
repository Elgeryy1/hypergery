from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .errors import HyperGeryError, NasUnavailableError
from .hglog import get_logger, new_operation_id, now_iso
from .labsx import require_valid_lab
from .settings import V1Settings
from .telemetry import read_disk_mib

COMMITS_DIRNAME = "labs-commits"
CHECKSUMS_FILENAME = "checksums.sha256"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class NasService:
    """Lab commit/restore on the NAS with checksums and dry-run by default.

    Layout under the NAS root:

        labs-commits/<lab_id>/<commit_id>/
            manifest.json          commit metadata
            lab_manifest.json      full lab manifest at commit time
            vms/<vm>.json          per-VM metadata (if provided)
            disks/...              disk copies (only with include_disks=True)
            checksums.sha256       sha256 of every packaged file

    Restores never touch live VMs: packages are restored to a destination
    directory chosen by the caller, after checksum validation.
    """

    def __init__(
        self,
        nas_root: str | Path | None = None,
        *,
        settings: V1Settings | None = None,
        lab_store: Any | None = None,
    ) -> None:
        self.settings = settings or V1Settings()
        if nas_root is None:
            from ..config import effective_value

            nas_root = effective_value("nas_staging_path")
        self.nas_root = Path(nas_root).expanduser()
        self.commits_root = self.nas_root / COMMITS_DIRNAME
        self.lab_store = lab_store

    # Health ------------------------------------------------------------------ #

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "nas_root": str(self.nas_root),
            "exists": self.nas_root.is_dir(),
            "readable": False,
            "writable": False,
            "free_mib": 0,
            "last_commit": None,
            "checked_at": now_iso(),
            "ok": False,
        }
        if not result["exists"]:
            return result
        result["readable"] = os.access(self.nas_root, os.R_OK)
        probe = self.nas_root / f".hypergery-health-{uuid.uuid4().hex[:8]}"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            result["writable"] = True
        except OSError:
            result["writable"] = False
        finally:
            if probe.exists():  # pragma: no cover - best effort cleanup
                try:
                    probe.unlink()
                except OSError:
                    pass
        _total, free = read_disk_mib(self.nas_root)
        result["free_mib"] = free
        commits = self.list_commits()
        result["last_commit"] = commits[-1] if commits else None
        result["ok"] = result["readable"] and result["writable"]
        return result

    def _require_available(self) -> None:
        health = self.health()
        if not health["ok"]:
            raise NasUnavailableError(
                f"NAS path not available or not writable: {self.nas_root}. "
                "Check the mount and HYPERGERY_NAS_STAGING_PATH."
            )

    # Commit -------------------------------------------------------------------#

    def _package_plan(
        self,
        lab: dict[str, Any],
        *,
        vms_info: list[dict[str, Any]] | None,
        include_disks: bool,
    ) -> list[tuple[str, str | Path]]:
        """[(relative_path, content-or-source-path)] for the package."""
        plan: list[tuple[str, str | Path]] = [
            ("lab_manifest.json", json.dumps(lab, indent=2, sort_keys=True) + "\n"),
        ]
        for vm in vms_info or []:
            name = str(vm.get("name") or vm.get("id") or "vm")
            plan.append((f"vms/{name}.json", json.dumps(vm, indent=2, sort_keys=True) + "\n"))
        if include_disks:
            for vm in vms_info or []:
                disk = str(vm.get("disk_path") or "")
                if disk and Path(disk).is_file():
                    plan.append((f"disks/{Path(disk).name}", Path(disk)))
        return plan

    def commit_lab(
        self,
        lab_id: str,
        *,
        lab: dict[str, Any] | None = None,
        vms_info: list[dict[str, Any]] | None = None,
        include_disks: bool = False,
        dry_run: bool | None = None,
        existing_labs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Package a lab onto the NAS. Dry-run by default (settings)."""
        if dry_run is None:
            dry_run = self.settings.dry_run_default
        log = get_logger()
        operation_id = new_operation_id("nas-commit")
        if lab is None:
            if self.lab_store is None:
                raise HyperGeryError("commit_lab needs a lab manifest or a lab_store.")
            lab = self.lab_store.get_lab(lab_id)
        require_valid_lab(lab, existing_labs=existing_labs or [])
        plan = self._package_plan(lab, vms_info=vms_info, include_disks=include_disks)
        total_bytes = 0
        files: list[dict[str, Any]] = []
        for rel_path, content in plan:
            size = Path(content).stat().st_size if isinstance(content, Path) else len(str(content).encode("utf-8"))
            total_bytes += size
            files.append({"path": rel_path, "size_bytes": size})
        commit_id = f"commit-{now_iso().replace(':', '').replace('+', 'Z')}-{uuid.uuid4().hex[:8]}"
        result: dict[str, Any] = {
            "operation_id": operation_id,
            "lab_id": lab_id,
            "commit_id": commit_id,
            "dry_run": dry_run,
            "include_disks": include_disks,
            "files": files,
            "total_size_bytes": total_bytes,
            "created_at": now_iso(),
            "ok": True,
        }
        log.info("nas", f"NAS commit {'dry-run' if dry_run else 'started'} for {lab_id}",
                 lab_id=lab_id, operation_id=operation_id, details={"files": len(files)})
        if dry_run:
            return result

        self._require_available()
        target = self.commits_root / lab_id / commit_id
        staging = target.with_name(target.name + ".partial")
        try:
            staging.mkdir(parents=True, exist_ok=False)
            checksums: list[str] = []
            for rel_path, content in plan:
                destination = staging / rel_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, Path):
                    shutil.copyfile(content, destination)
                else:
                    destination.write_text(str(content), encoding="utf-8")
                checksums.append(f"{_sha256(destination)}  {rel_path}")
            manifest = {
                "commit_id": commit_id,
                "lab_id": lab_id,
                "operation_id": operation_id,
                "created_at": result["created_at"],
                "include_disks": include_disks,
                "files": files,
                "total_size_bytes": total_bytes,
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (staging / CHECKSUMS_FILENAME).write_text("\n".join(checksums) + "\n", encoding="utf-8")
            staging.rename(target)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            log.error("nas", f"NAS commit failed for {lab_id}: {exc}", lab_id=lab_id, operation_id=operation_id)
            raise NasUnavailableError(f"NAS commit failed: {exc}") from exc
        verification = self.verify_commit(lab_id, commit_id)
        result["verified"] = verification["ok"]
        if not verification["ok"]:
            log.error("nas", f"NAS commit verification failed for {lab_id}/{commit_id}",
                      lab_id=lab_id, operation_id=operation_id, details=verification)
            raise HyperGeryError(f"NAS commit verification failed: {verification['errors']}")
        log.info("nas", f"NAS commit done for {lab_id}: {commit_id}", lab_id=lab_id, operation_id=operation_id)
        return result

    # Inspection ---------------------------------------------------------------#

    def list_commits(self, lab_id: str | None = None) -> list[dict[str, Any]]:
        commits: list[dict[str, Any]] = []
        if not self.commits_root.is_dir():
            return commits
        lab_dirs = [self.commits_root / lab_id] if lab_id else sorted(self.commits_root.iterdir())
        for lab_dir in lab_dirs:
            if not lab_dir.is_dir():
                continue
            for commit_dir in sorted(lab_dir.iterdir()):
                manifest = commit_dir / "manifest.json"
                if not manifest.is_file():
                    continue
                try:
                    commits.append(json.loads(manifest.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        return sorted(commits, key=lambda item: str(item.get("created_at", "")))

    def verify_commit(self, lab_id: str, commit_id: str) -> dict[str, Any]:
        commit_dir = self.commits_root / lab_id / commit_id
        checksums = commit_dir / CHECKSUMS_FILENAME
        if not checksums.is_file():
            return {"ok": False, "errors": [f"Missing {CHECKSUMS_FILENAME} in {commit_dir}"]}
        errors: list[str] = []
        for line in checksums.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            expected, _, rel_path = line.partition("  ")
            target = commit_dir / rel_path
            if not target.is_file():
                errors.append(f"Missing file: {rel_path}")
            elif _sha256(target) != expected:
                errors.append(f"Checksum mismatch: {rel_path}")
        return {"ok": not errors, "errors": errors, "commit_id": commit_id, "lab_id": lab_id}

    # Restore --------------------------------------------------------------------#

    def restore_commit(
        self,
        lab_id: str,
        commit_id: str,
        destination: str | Path,
        *,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Restore a commit package to `destination` after hash validation.

        Never touches live VMs or overwrites existing files: the destination
        directory must not already contain the commit.
        """
        if dry_run is None:
            dry_run = self.settings.dry_run_default
        log = get_logger()
        operation_id = new_operation_id("nas-restore")
        commit_dir = self.commits_root / lab_id / commit_id
        if not commit_dir.is_dir():
            raise HyperGeryError(f"Commit not found on the NAS: {lab_id}/{commit_id}")
        verification = self.verify_commit(lab_id, commit_id)
        if not verification["ok"]:
            raise HyperGeryError(f"Refusing to restore corrupt commit {commit_id}: {verification['errors']}")
        target = Path(destination).expanduser() / commit_id
        files = sorted(str(item.relative_to(commit_dir)) for item in commit_dir.rglob("*") if item.is_file())
        result = {
            "operation_id": operation_id,
            "lab_id": lab_id,
            "commit_id": commit_id,
            "destination": str(target),
            "dry_run": dry_run,
            "files": files,
            "verified": True,
            "ok": True,
        }
        if dry_run:
            log.info("nas", f"NAS restore dry-run for {lab_id}/{commit_id}", lab_id=lab_id, operation_id=operation_id)
            return result
        if target.exists():
            raise HyperGeryError(f"Restore destination already exists, refusing to overwrite: {target}")
        shutil.copytree(commit_dir, target)
        log.info("nas", f"NAS restore done for {lab_id}/{commit_id} → {target}", lab_id=lab_id, operation_id=operation_id)
        return result
