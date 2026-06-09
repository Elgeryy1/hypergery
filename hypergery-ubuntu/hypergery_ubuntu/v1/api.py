from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .battery import BatteryService
from .errors import HostOfflineError, HyperGeryError, PermissionDeniedError, error_code
from .hglog import get_logger, now_iso
from .hosts import HostRegistry
from .labsx import filter_labs, validate_lab
from .nas import NasService
from .networks import networks_from_labs, validate_networks
from .orchestrator import OrchestratorService
from .providers import VmInfo
from .rbac import UserStore
from .settings import V1Settings
from .telemetry import TelemetryService, evaluate_alerts
from .external_nodes import ExternalNodeStore, health_check as node_health_check
from .teleport import TeleportEngine

API_VERSION = "v1"


class ApiContext:
    """Service container for the Android-ready API.

    Every dependency is injectable for tests; defaults build the real
    services. Heavy/optional dependencies (libvirt backend, Hub client)
    can be None — endpoints degrade with clear errors instead of crashing.
    """

    def __init__(
        self,
        *,
        settings: V1Settings | None = None,
        telemetry: TelemetryService | None = None,
        host_registry: HostRegistry | None = None,
        battery: BatteryService | None = None,
        nas: NasService | None = None,
        lab_store: Any | None = None,
        user_store: UserStore | None = None,
        node_store: ExternalNodeStore | None = None,
        orchestrator: OrchestratorService | None = None,
        teleport_engine: TeleportEngine | None = None,
        local_vms: Callable[[], list[VmInfo]] | None = None,
        hub_client: Any | None = None,
    ) -> None:
        self.settings = settings or V1Settings()
        self.telemetry = telemetry or TelemetryService(settings=self.settings)
        self.host_registry = host_registry or HostRegistry(
            settings=self.settings, telemetry=self.telemetry, hub_client=hub_client
        )
        self.battery = battery or BatteryService(settings=self.settings)
        self.nas = nas
        self.lab_store = lab_store
        self.user_store = user_store or UserStore()
        self.node_store = node_store or ExternalNodeStore()
        self.orchestrator = orchestrator or OrchestratorService(settings=self.settings)
        self.teleport_engine = teleport_engine
        self._local_vms = local_vms
        self.hub_client = hub_client

    # Data accessors ---------------------------------------------------------- #

    def labs(self) -> list[dict[str, Any]]:
        if self.lab_store is None:
            return []
        return self.lab_store.list_labs()

    def vms(self) -> list[VmInfo]:
        vms: list[VmInfo] = []
        if self._local_vms is not None:
            vms.extend(self._local_vms())
        if self.hub_client is not None and not self.settings.offline_mode:
            local_ids = {vm.id for vm in vms}
            try:
                for record in self.hub_client.list_vms():
                    name = str(record.get("vm_name") or "")
                    if not name or name in local_ids:
                        continue
                    vms.append(
                        VmInfo(
                            id=name,
                            ram_mb=int(record.get("ram_mib") or 0),
                            cpu=int(record.get("vcpus") or 0),
                            status=str(record.get("state") or "unknown").lower(),
                            host_id=str(record.get("host_id") or ""),
                            lab_id=str(record.get("lab_id") or ""),
                            network_ids=list(record.get("networks") or []),
                            last_seen=str(record.get("updated_at") or ""),
                        )
                    )
            except Exception as exc:
                get_logger().warning("api", f"Hub VM inventory unavailable: {exc}")
        return vms

    def orchestrator_plan(self, *, lab_id: str | None = None, allow_remote: bool = True) -> list[dict[str, Any]]:
        hosts = self.host_registry.list_hosts()
        battery = self.battery.read()
        plans = self.orchestrator.plan(
            hosts=hosts,
            vms=self.vms(),
            battery=battery,
            local_host_id=hosts[0].id if hosts else None,
            allow_remote=allow_remote,
            lab_id=lab_id,
        )
        return [plan.to_dict() for plan in plans]


def envelope(data: Any = None, *, error: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "data": data if error is None else None,
        "error": error,
        "timestamp": now_iso(),
        "api_version": API_VERSION,
    }


class ApiServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], context: ApiContext) -> None:
        super().__init__(server_address, ApiRequestHandler)
        self.context = context


class ApiRequestHandler(BaseHTTPRequestHandler):
    server: ApiServer

    def log_message(self, fmt: str, *args: object) -> None:
        return

    # Helpers ------------------------------------------------------------- #

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data: Any) -> None:
        self._send(200, envelope(data))

    def _fail(self, exc: BaseException) -> None:
        status = 500
        if isinstance(exc, PermissionDeniedError):
            status = 403
        elif isinstance(exc, HostOfflineError):
            status = 503
        elif isinstance(exc, HyperGeryError):
            status = 400
        get_logger().warning("api", f"request failed: {exc}", details={"code": error_code(exc)})
        self._send(status, envelope(error={"code": error_code(exc), "message": str(exc)}))

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HyperGeryError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise HyperGeryError("JSON body must be an object.")
        return data

    # Routing --------------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802
        context = self.server.context
        parsed = urlparse(self.path)
        path = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query)

        def first(key: str) -> str | None:
            values = query.get(key) or []
            return values[0] if values else None

        try:
            if path == ["health"]:
                self._ok({"service": "hypergery-v1-api", "status": "ok"})
                return
            if path == ["hosts"]:
                self._ok({"hosts": [host.to_dict() for host in context.host_registry.list_hosts()]})
                return
            if len(path) == 2 and path[0] == "hosts":
                host = context.host_registry.get_host(path[1])
                self._ok({"host": host.to_dict(), "health": context.host_registry.health_check(host)})
                return
            if path == ["telemetry"]:
                sample = context.telemetry.sample_local()
                hosts = [host.to_dict() for host in context.host_registry.list_hosts()]
                nas_path = context.nas.nas_root if context.nas is not None else None
                alerts = evaluate_alerts(
                    local_sample=sample,
                    hub_hosts=[host for host in hosts if "hub" in host.get("tags", [])],
                    nas_path=nas_path,
                    settings=context.settings,
                )
                self._ok({"local": sample.to_dict(), "alerts": alerts})
                return
            if path == ["labs"]:
                labs = filter_labs(
                    context.labs(),
                    subject=first("subject"),
                    favorites_only=first("favorites") in {"1", "true"},
                    include_archived=first("archived") in {"1", "true"},
                    tag=first("tag"),
                )
                self._ok({"labs": labs})
                return
            if len(path) == 2 and path[0] == "labs":
                labs = context.labs()
                for lab in labs:
                    if str(lab.get("lab_id")) == path[1]:
                        self._ok({"lab": lab, "validation": validate_lab(lab, existing_labs=labs)})
                        return
                raise HyperGeryError(f"Lab does not exist: {path[1]}")
            if path == ["vms"]:
                self._ok({"vms": [vm.to_dict() for vm in context.vms()]})
                return
            if len(path) == 2 and path[0] == "vms":
                for vm in context.vms():
                    if vm.id == path[1]:
                        self._ok({"vm": vm.to_dict()})
                        return
                raise HyperGeryError(f"VM not found: {path[1]}")
            if path == ["nas", "status"]:
                if context.nas is None:
                    raise HyperGeryError("NAS service is not configured.")
                self._ok({"health": context.nas.health(), "commits": context.nas.list_commits()[-20:]})
                return
            if path == ["battery"]:
                state = context.battery.read()
                self._ok({"battery": state.to_dict(), "actions": context.battery.recommended_actions(state)})
                return
            if path == ["orchestrator", "plan"]:
                self._ok({"plans": context.orchestrator_plan(lab_id=first("lab_id"))})
                return
            if path == ["logs"]:
                events = get_logger().query(
                    category=first("category"),
                    level=first("level"),
                    operation_id=first("operation_id"),
                    contains=first("contains"),
                    limit=int(first("limit") or 100),
                )
                self._ok({"events": events})
                return
            if path == ["network"]:
                networks = networks_from_labs(context.labs())
                validation = validate_networks(networks, vms=context.vms())
                self._ok({"networks": [network.to_dict() for network in networks], "validation": validation})
                return
            if path == ["guests"]:
                users = [
                    {**user.to_dict(), "effective_permissions": sorted(user.permissions())}
                    for user in context.user_store.list_users()
                ]
                self._ok({"users": users})
                return
            if path == ["external-nodes"]:
                nodes = context.node_store.list_nodes()
                self._ok({"nodes": [{**node.to_dict(), "health": node_health_check(node)} for node in nodes]})
                return
            raise HyperGeryError(f"Unknown endpoint: GET {parsed.path}")
        except Exception as exc:  # noqa: BLE001 - everything becomes an API error
            self._fail(exc)

    def do_POST(self) -> None:  # noqa: N802
        context = self.server.context
        path = [part for part in urlparse(self.path).path.split("/") if part]
        try:
            body = self._read_body()
            if path == ["orchestrator", "dry-run"]:
                plans = context.orchestrator_plan(
                    lab_id=str(body.get("lab_id") or "") or None,
                    allow_remote=bool(body.get("allow_remote", True)),
                )
                self._ok({"plans": plans, "dry_run": True})
                return
            if path == ["teleport", "dry-run"]:
                if context.teleport_engine is None:
                    raise HyperGeryError("Teleport engine is not configured (no local backend).")
                result = context.teleport_engine.teleport_vm(
                    str(body.get("vm_name") or ""),
                    mode="dry_run",
                    target_host_id=str(body.get("target_host_id") or ""),
                    include_iso=bool(body.get("include_iso", True)),
                )
                self._ok(result)
                return
            if path == ["teleport", "start"]:
                if context.teleport_engine is None:
                    raise HyperGeryError("Teleport engine is not configured (no local backend).")
                if not body.get("confirm"):
                    raise HyperGeryError(
                        "teleport/start requires {\"confirm\": true} — use teleport/dry-run to preview."
                    )
                result = context.teleport_engine.teleport_vm(
                    str(body.get("vm_name") or ""),
                    mode=str(body.get("mode") or "") or None,
                    target_host_id=str(body.get("target_host_id") or ""),
                    target_vm_name=str(body.get("target_vm_name") or ""),
                    staging_dir=str(body.get("staging_dir") or "") or None,
                    include_iso=bool(body.get("include_iso", True)),
                )
                self._ok(result)
                return
            raise HyperGeryError(f"Unknown endpoint: POST {'/' + '/'.join(path)}")
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def serve_api(
    context: ApiContext | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    allow_remote: bool = False,
) -> None:
    """Blocking API server (CLI entry point).

    The API has no authentication yet (see NEXT_STEPS_V12_SECURITY.md), and
    /teleport/start can suspend a live VM. Binding to a non-loopback address
    therefore requires an explicit opt-in so it cannot happen by passing a
    single --host flag by mistake.
    """
    context = context or ApiContext()
    bind_host = host or context.settings.api_host
    bind_port = port or context.settings.api_port
    if bind_host not in LOOPBACK_HOSTS and not allow_remote:
        raise HyperGeryError(
            f"Refusing to bind the unauthenticated v1 API to a non-loopback address ({bind_host}). "
            "It exposes host/VM inventory and /teleport/start to the network. "
            "Pass allow_remote=True (CLI: --allow-remote) only on a trusted LAN."
        )
    server = ApiServer((bind_host, bind_port), context)
    if bind_host not in LOOPBACK_HOSTS:
        get_logger().warning(
            "api", f"v1 API bound to NON-LOOPBACK {bind_host}:{bind_port} with no authentication — trusted LAN only."
        )
    get_logger().info("api", f"v1 API listening on http://{bind_host}:{bind_port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
