"""Backup Verifier (v1.3): un backup solo cuenta si se puede restaurar.

Restaura un paquete de backup en una VM temporal ``hgtest-verify-*``, la
arranca, comprueba que llega a ``running`` y la elimina (dominio + discos).
Nunca toca la VM original ni ninguna VM que no haya creado él mismo.
"""

from __future__ import annotations

import uuid
from typing import Any

from ..backend import HyperGeryError
from ..migration import import_vm_package, validate_vm_package
from .hglog import get_logger

VERIFY_PREFIX = "hgtest-verify-"
VERIFY_LAB_ID = "hgtest-lab-verify"


def verify_backup(
    backend: Any,
    package_dir: str,
    *,
    boot_timeout_seconds: int = 60,
    keep_vm: bool = False,
) -> dict[str, Any]:
    log = get_logger()
    steps: list[dict[str, str]] = []
    result: dict[str, Any] = {"ok": False, "package_dir": str(package_dir), "steps": steps}

    def step(name: str, status: str, detail: str = "") -> None:
        steps.append({"step": name, "status": status, "detail": detail})

    validation = validate_vm_package(package_dir)
    result["checksums_ok"] = bool(validation["ok"])
    if not validation["ok"]:
        step("validate", "fail", "; ".join(validation["errors"]))
        result["errors"] = validation["errors"]
        return result
    step("validate", "ok", "manifest y checksums correctos")

    temp_name = f"{VERIFY_PREFIX}{uuid.uuid4().hex[:10]}"
    result["verified_vm"] = temp_name
    imported = False
    try:
        import_vm_package(backend, package_dir, target_vm_name=temp_name, target_lab_id=VERIFY_LAB_ID)
        imported = True
        step("restore", "ok", f"restaurado como {temp_name}")

        backend.start_vm(temp_name)
        state = backend.wait_for_state(
            temp_name,
            {"running"},
            timeout_seconds=boot_timeout_seconds,
            interval_seconds=2.0,
        )
        booted = state.lower() == "running"
        result["booted"] = booted
        step("boot", "ok" if booted else "fail", f"estado final: {state}")
        result["ok"] = bool(result["checksums_ok"] and booted)
    except HyperGeryError as exc:
        result.setdefault("booted", False)
        step("boot" if imported else "restore", "fail", str(exc))
        result["errors"] = [str(exc)]
    finally:
        if imported and not keep_vm:
            _cleanup_verify_vm(backend, temp_name, step)
        elif imported:
            step("cleanup", "skipped", f"--keep-vm: conserva {temp_name}")

    log_fn = log.info if result["ok"] else log.warning
    log_fn("nas", f"backup verify {'OK' if result['ok'] else 'FAILED'}: {package_dir}", vm_id=temp_name)
    return result


def _cleanup_verify_vm(backend: Any, temp_name: str, step) -> None:
    if not temp_name.startswith(VERIFY_PREFIX):
        raise HyperGeryError(f"Refusing to clean a non-verify VM: {temp_name}")
    try:
        backend.virsh(["destroy", temp_name], check=False)
        backend.delete_vm(temp_name, delete_disks=True)
        step("cleanup", "ok", f"{temp_name} eliminada (dominio + discos)")
    except HyperGeryError as exc:
        step("cleanup", "fail", str(exc))
