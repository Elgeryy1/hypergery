from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

# HG-BUG-0030 (fase 1): la lógica de servicios vive en api_context.py;
# este re-export mantiene intacta la API pública (`from .api import ApiContext`).
from .api_context import ApiContext
from .errors import HostOfflineError, HyperGeryError, PermissionDeniedError, error_code
from .hglog import get_logger, now_iso
from .labsx import filter_labs, validate_lab
from .networks import networks_from_labs, validate_networks
from ..registry.auth import AuthRateLimiter
from .auth import ApiTokenStore, load_or_create_api_token, resolve_user
from .rbac import User, require_permission
from .telemetry import evaluate_alerts
from .external_nodes import health_check as node_health_check

API_VERSION = "v1"

# HG-BUG-0029: máximo de long-polls de progreso bloqueando hilos a la vez.
MAX_CONCURRENT_LONG_POLLS = 32


def envelope(data: Any = None, *, error: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "data": data if error is None else None,
        "error": error,
        "timestamp": now_iso(),
        "api_version": API_VERSION,
    }


class ApiServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        context: ApiContext,
        *,
        auth_token: str | None = None,
        token_store: ApiTokenStore | None = None,
    ) -> None:
        super().__init__(server_address, ApiRequestHandler)
        self.context = context
        # TD-5: token obligatorio por defecto. auth_token="" lo desactiva
        # explícitamente (solo loopback/desarrollo; queda registrado).
        self.auth_token = load_or_create_api_token() if auth_token is None else auth_token
        self.token_store = token_store or ApiTokenStore()
        # HG-BUG-0027: el mismo anti fuerza bruta del Hub también aquí (el
        # API companion lo consumirá un móvil expuesto en la VPN).
        self.auth_limiter = AuthRateLimiter()
        # HG-BUG-0029: techo de long-polls concurrentes para no agotar los
        # hilos del ThreadingHTTPServer; el resto recibe 503 y reintenta.
        self.long_poll_slots = threading.BoundedSemaphore(MAX_CONCURRENT_LONG_POLLS)
        if not self.auth_token:
            get_logger().warning("api", "v1 API auth is DISABLED (explicit empty token).")


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

    def _authenticate(self) -> User | None:
        """TD-5: Bearer token obligatorio (excepto GET /health).

        Devuelve el usuario RBAC autenticado, o None si ya se envió el 401.
        """
        if not self.server.auth_token:
            from .auth import OWNER_USER

            return OWNER_USER
        client_ip = self.client_address[0] if self.client_address else "?"
        if self.server.auth_limiter.is_blocked(client_ip):
            self._send(
                429,
                envelope(error={"code": "rate_limited", "message": "Too many failed authentication attempts. Try again later."}),
            )
            return None
        header = (self.headers.get("Authorization") or "").strip()
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        user = resolve_user(
            token,
            owner_token=self.server.auth_token,
            token_store=self.server.token_store,
            user_store=self.server.context.user_store,
        )
        if user is not None:
            self.server.auth_limiter.record_success(client_ip)
            return user
        self.server.auth_limiter.record_failure(client_ip)
        get_logger().warning(
            "api",
            f"auth failure: {self.command} {urlparse(self.path).path} from {client_ip}",
            details={"ip": client_ip},
        )
        self._send(
            401,
            envelope(error={"code": "auth_required", "message": "Authentication required: Authorization: Bearer <token>."}),
        )
        return None

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
            user = self._authenticate()
            if user is None:
                return
            # RBAC (TD-5): lecturas generales → can_view_labs; la gestión de
            # usuarios → can_manage_guests. require_permission audita siempre.
            require_permission(user, "can_manage_guests" if path == ["guests"] else "can_view_labs")
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
            if path == ["dashboard"]:
                self._ok({"dashboard": context.dashboard()})
                return
            if path == ["progress"]:
                from .progress import get_progress_channel

                self._ok(
                    {
                        "operations": get_progress_channel().list(
                            kind=first("kind"),
                            active_only=first("active") in {"1", "true"},
                        )
                    }
                )
                return
            if len(path) == 2 and path[0] == "progress":
                # TD-9 long-poll: ?since=<version>&timeout=<s> bloquea hasta
                # que haya progreso nuevo (la app Android y la UI lo comparten).
                from .progress import get_progress_channel

                try:
                    since = int(first("since") or -1)
                except ValueError:
                    since = -1
                try:
                    timeout = min(60.0, max(0.0, float(first("timeout") or 25.0)))
                except ValueError:
                    timeout = 25.0
                # HG-BUG-0029: limitar long-polls concurrentes (no bloquear si
                # no hay hueco → 503 para que el cliente reintente).
                if not self.server.long_poll_slots.acquire(blocking=False):
                    self._send(
                        503,
                        envelope(error={"code": "busy", "message": "Too many concurrent progress subscriptions; retry shortly."}),
                    )
                    return
                try:
                    operation = get_progress_channel().wait_for_change(path[1], since_version=since, timeout=timeout)
                except KeyError as exc:
                    raise HyperGeryError(str(exc)) from exc
                finally:
                    self.server.long_poll_slots.release()
                self._ok({"operation": operation})
                return
            if path == ["external-nodes"]:
                nodes = context.node_store.list_nodes()
                self._ok({"nodes": [{**node.to_dict(), "health": node_health_check(node)} for node in nodes]})
                return
            raise HyperGeryError(f"Unknown endpoint: GET {parsed.path}")
        except Exception as exc:  # noqa: BLE001 - everything becomes an API error
            self._fail(exc)

    POST_PERMISSIONS = {
        ("orchestrator", "dry-run"): "can_use_remote_compute",
        ("teleport", "dry-run"): "can_teleport",
        ("teleport", "start"): "can_teleport",
    }

    # v1.4 API companion: acciones seguras por VM y su permiso RBAC.
    VM_ACTION_PERMISSIONS = {
        "start": "can_start_vm",
        "shutdown": "can_stop_vm",
        "snapshot": "can_stop_vm",
    }

    def do_POST(self) -> None:  # noqa: N802
        context = self.server.context
        path = [part for part in urlparse(self.path).path.split("/") if part]
        user = self._authenticate()
        if user is None:
            return
        try:
            if len(path) == 3 and path[0] == "vms" and path[2] in self.VM_ACTION_PERMISSIONS:
                vm_id, action = path[1], path[2]
                vm = context.find_vm(vm_id)
                # Lab scoping: un Guest solo actúa sobre VMs de sus labs.
                require_permission(user, self.VM_ACTION_PERMISSIONS[action], lab_id=vm.lab_id or None)
                body = self._read_body()
                snapshot_name = str(body.get("snapshot_name") or "")
                if action == "snapshot":
                    if not body.get("confirm"):
                        raise HyperGeryError('vms/<id>/snapshot requires {"confirm": true}.')
                    if not snapshot_name:
                        raise HyperGeryError("vms/<id>/snapshot requires snapshot_name.")
                self._ok(context.vm_action(vm_id, action, snapshot_name=snapshot_name))
                return
            if path == ["orchestrator", "apply"]:
                require_permission(user, "can_use_remote_compute")
                require_permission(user, "can_teleport")
                body = self._read_body()
                plan = body.get("plan")
                if not isinstance(plan, dict):
                    raise HyperGeryError('orchestrator/apply requires {"plan": {...}, "confirm": true}.')
                from .orchestrator import apply_plan

                self._ok(
                    apply_plan(
                        plan,
                        teleport_engine=context.teleport_engine,
                        confirm=bool(body.get("confirm")),
                    )
                )
                return
            require_permission(user, self.POST_PERMISSIONS.get(tuple(path), "can_change_settings"))
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

    v1.2: bearer token obligatorio (token de propietario o tokens por
    usuario RBAC). Aun así el transporte es HTTP plano: para salir del
    loopback hace falta opt-in explícito, y para salir de la LAN un reverse
    proxy TLS o VPN (docs/HUB_SECURITY.md).
    """
    context = context or ApiContext()
    bind_host = host or context.settings.api_host
    bind_port = port or context.settings.api_port
    if bind_host not in LOOPBACK_HOSTS and not allow_remote:
        raise HyperGeryError(
            f"Refusing to bind the v1 API to a non-loopback address ({bind_host}) without explicit opt-in. "
            "It exposes host/VM inventory and /teleport/start to the network over plain HTTP. "
            "Pass allow_remote=True (CLI: --allow-remote) only on a trusted LAN, ideally behind TLS."
        )
    server = ApiServer((bind_host, bind_port), context)
    if bind_host not in LOOPBACK_HOSTS:
        get_logger().warning(
            "api",
            f"v1 API bound to NON-LOOPBACK {bind_host}:{bind_port} over plain HTTP — use a TLS reverse proxy or VPN.",
        )
    get_logger().info("api", f"v1 API listening on http://{bind_host}:{bind_port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
