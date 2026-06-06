from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .errors import HyperGeryError
from .hglog import get_logger, now_iso, xdg_state_home
from .hosts import HostInfo

NODE_TYPES = ("isard", "cloud", "remote_pc", "loopback", "unknown")


@dataclass
class ExternalNode:
    id: str
    name: str = ""
    type: str = "unknown"
    address: str = ""
    status: str = "unknown"
    capabilities: list[str] = field(default_factory=list)
    cpu: str = ""
    ram_mib: int = 0
    notes: str = ""
    added_at: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise HyperGeryError("External node id cannot be empty.")
        if not self.name:
            self.name = self.id
        if self.type not in NODE_TYPES:
            self.type = "unknown"
        if not self.added_at:
            self.added_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_host_info(self) -> HostInfo:
        """Adapt to HostInfo so the orchestrator can consider external nodes."""
        role = "isard" if self.type == "isard" else "unknown"
        capabilities = list(self.capabilities) or ["can_run_vms", "experimental"]
        if "experimental" not in capabilities:
            capabilities.append("experimental")
        return HostInfo(
            id=self.id,
            name=self.name,
            role=role,
            address=self.address,
            status=self.status,
            ram_free_mib=self.ram_mib,
            ram_total_mib=self.ram_mib,
            capabilities=capabilities,
            tags=["external", self.type],
        )


def default_nodes_path() -> Path:
    return xdg_state_home() / "hypergery" / "external-nodes.json"


class ExternalNodeStore:
    """Manually registered external compute nodes (Isard-style boosters)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_nodes_path()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperGeryError(f"Cannot read external nodes file {self.path}: {exc}") from exc

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        # Atomic write so a concurrent reader never sees a partial file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def add_node(self, node: ExternalNode) -> ExternalNode:
        data = self._read()
        if node.id in data:
            raise HyperGeryError(f"External node already exists: {node.id}")
        data[node.id] = node.to_dict()
        self._write(data)
        get_logger().info("hosts", f"external node added: {node.id} ({node.type})")
        return node

    def get_node(self, node_id: str) -> ExternalNode:
        data = self._read()
        if node_id not in data:
            raise HyperGeryError(f"External node does not exist: {node_id}")
        return ExternalNode(**data[node_id])

    def list_nodes(self) -> list[ExternalNode]:
        return [ExternalNode(**record) for record in sorted(self._read().values(), key=lambda item: item["id"])]

    def remove_node(self, node_id: str) -> None:
        data = self._read()
        if node_id not in data:
            raise HyperGeryError(f"External node does not exist: {node_id}")
        del data[node_id]
        self._write(data)

    def update_status(self, node_id: str, status: str) -> ExternalNode:
        data = self._read()
        if node_id not in data:
            raise HyperGeryError(f"External node does not exist: {node_id}")
        data[node_id]["status"] = status
        self._write(data)
        return ExternalNode(**data[node_id])


def health_check(node: ExternalNode, *, timeout_seconds: int = 5) -> dict[str, Any]:
    """Non-invasive node health: loopback is always online; nodes with an
    HTTP address are probed at /health; anything else stays unknown."""
    result: dict[str, Any] = {
        "node_id": node.id,
        "type": node.type,
        "reachable": False,
        "status": "unknown",
        "latency_ms": None,
        "checked_at": now_iso(),
    }
    if node.type == "loopback":
        result.update({"reachable": True, "status": "online"})
        return result
    if node.address.startswith("http://") or node.address.startswith("https://"):
        url = node.address.rstrip("/") + "/health"
        started = time.perf_counter()
        try:
            with urlopen(Request(url, method="GET"), timeout=timeout_seconds) as response:
                response.read()
            result.update(
                {"reachable": True, "status": "online", "latency_ms": int((time.perf_counter() - started) * 1000)}
            )
        except Exception as exc:
            result.update({"reachable": False, "status": "offline", "error": str(exc)})
        return result
    result["error"] = "No probe available for this node (no HTTP address)."
    return result


def detect_local_environment() -> dict[str, Any]:
    """Non-invasive heuristics about the local machine (for external-node
    style reporting): virtualization, KVM availability, hostname."""
    virtualization = "unknown"
    detector = shutil.which("systemd-detect-virt")
    if detector:
        try:
            probe = subprocess.run([detector], capture_output=True, text=True, timeout=5)
            virtualization = probe.stdout.strip() or ("none" if probe.returncode != 0 else "unknown")
        except (OSError, subprocess.SubprocessError):
            virtualization = "unknown"
    kvm = Path("/dev/kvm")
    return {
        "hostname": socket.gethostname(),
        "virtualization": virtualization,
        "kvm_available": kvm.exists() and os.access(kvm, os.R_OK | os.W_OK),
        "platform": os.uname().sysname.lower() if hasattr(os, "uname") else "unknown",
        "detected_at": now_iso(),
    }
