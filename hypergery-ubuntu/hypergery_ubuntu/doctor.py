from __future__ import annotations

import os
import grp
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .backend import LIBVIRT_URI
from .config import effective_config
from .registry import RegistryClient


@dataclass
class DoctorItem:
    status: str
    name: str
    detail: str
    critical: bool = False


def _which(name: str, *, critical: bool = True) -> DoctorItem:
    path = shutil.which(name)
    return DoctorItem("OK", name, path or "") if path else DoctorItem("FAIL" if critical else "WARN", name, "not found", critical)


def _run(args: list[str], *, timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def collect_doctor_items() -> list[DoctorItem]:
    values = effective_config()
    hub_url = values["hub_url"].value
    host_id = values["host_id"].value
    nas_path = Path(values["nas_staging_path"].value).expanduser()
    items: list[DoctorItem] = [
        DoctorItem("OK", "python", sys.version.split()[0]),
        DoctorItem("OK", "hub url", f"{hub_url} ({values['hub_url'].source})"),
        DoctorItem("OK", "host id", f"{host_id} ({values['host_id'].source})"),
    ]

    kvm = Path("/dev/kvm")
    if kvm.exists() and os.access(kvm, os.R_OK | os.W_OK):
        items.append(DoctorItem("OK", "/dev/kvm", "exists and accessible"))
    elif kvm.exists():
        items.append(DoctorItem("FAIL", "/dev/kvm", "exists but is not accessible", True))
    else:
        items.append(DoctorItem("FAIL", "/dev/kvm", "missing", True))

    group_ids = set(os.getgroups())
    try:
        group_ids.add(os.getgid())
    except OSError:
        pass
    groups = {grp.getgrgid(gid).gr_name for gid in group_ids}
    missing_groups = sorted({"kvm", "libvirt"} - groups)
    if missing_groups:
        items.append(DoctorItem("WARN", "user groups", "missing " + ", ".join(missing_groups)))
    else:
        items.append(DoctorItem("OK", "user groups", "kvm/libvirt present"))

    items.extend([_which("qemu-img"), _which("virsh"), _which("virt-viewer", critical=False)])
    if shutil.which("virsh"):
        try:
            result = _run(["virsh", "--connect", LIBVIRT_URI, "list", "--all"])
            if result.returncode == 0:
                items.append(DoctorItem("OK", "libvirt", f"connected to {LIBVIRT_URI}"))
            else:
                detail = (result.stderr or result.stdout).strip() or "virsh failed"
                items.append(DoctorItem("FAIL", "libvirt", detail, True))
        except (OSError, subprocess.TimeoutExpired) as exc:
            items.append(DoctorItem("FAIL", "libvirt", str(exc), True))

    if nas_path.is_dir():
        status = "OK" if os.access(nas_path, os.W_OK) else "FAIL"
        items.append(DoctorItem(status, "nas staging path", f"{nas_path} writable={os.access(nas_path, os.W_OK)}", status == "FAIL"))
    else:
        items.append(DoctorItem("FAIL", "nas staging path", f"missing: {nas_path}", True))

    docker_dir = Path(__file__).resolve().parents[2] / "docker"
    if docker_dir.is_dir():
        items.append(DoctorItem("OK", "docker folder", str(docker_dir)))
    else:
        items.append(DoctorItem("WARN", "docker folder", f"not found from {Path.cwd()}"))
    if shutil.which("docker"):
        try:
            result = _run(["docker", "compose", "version"], timeout=5)
            if result.returncode == 0:
                items.append(DoctorItem("OK", "docker compose", result.stdout.strip() or "available"))
            else:
                items.append(DoctorItem("WARN", "docker compose", (result.stderr or result.stdout).strip() or "not available"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            items.append(DoctorItem("WARN", "docker compose", str(exc)))
    else:
        items.append(DoctorItem("WARN", "docker compose", "docker not found"))

    try:
        client = RegistryClient(hub_url, timeout=3)
        health = client.health()
        items.append(DoctorItem("OK", "hub reachable", str(health)))
        vms = client.list_vms()
        items.append(DoctorItem("OK", "hub vm inventory", f"{len(vms)} VM record(s)"))
    except Exception as exc:
        items.append(DoctorItem("FAIL", "hub reachable", str(exc), True))

    return items


def doctor_exit_code(items: list[DoctorItem]) -> int:
    return 1 if any(item.status == "FAIL" and item.critical for item in items) else 0


def format_doctor_items(items: list[DoctorItem]) -> str:
    return "\n".join(f"{item.status:4} {item.name}: {item.detail}" for item in items)
