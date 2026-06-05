# HyperGery v1 API (Android Hub ready)

Local HTTP JSON API exposing the v0.9/v1 services for future mobile/web
clients. It is **LAN/localhost only and unauthenticated** — do not expose it
beyond a trusted network (authentication is planned for v1.2 security
hardening; see NEXT_STEPS_V12_SECURITY.md).

## Running

```bash
python -m hypergery_ubuntu.cli v1 api serve            # default 127.0.0.1:8799
# Non-loopback binds require an explicit opt-in (the API is unauthenticated):
python -m hypergery_ubuntu.cli v1 api serve --host 0.0.0.0 --port 8799 --allow-remote
```

Binding to a non-loopback address without `--allow-remote` is refused, because
the API has no authentication and `/teleport/start` can suspend a live VM. Only
use `--allow-remote` on a trusted LAN.

Host/port also configurable via `~/.config/hypergery/v1-settings.json`
(`api_host`, `api_port`) or `HYPERGERY_V1_API_HOST` / `HYPERGERY_V1_API_PORT`.

## Response envelope

Every response uses the same envelope:

```json
{
  "ok": true,
  "data": { },
  "error": null,
  "timestamp": "2026-06-06T01:00:00+00:00",
  "api_version": "v1"
}
```

Errors (HTTP 400/403/503/500):

```json
{
  "ok": false,
  "data": null,
  "error": { "code": "HOST_OFFLINE", "message": "Host is offline: pc-casa" },
  "timestamp": "...",
  "api_version": "v1"
}
```

Error codes: `HOST_OFFLINE` (503), `PERMISSION_DENIED` (403),
`NAS_UNAVAILABLE`, `TELEPORT_FAILED`, `BATTERY_UNAVAILABLE`, `LAB_INVALID`,
`NETWORK_CONFLICT`, `MEMDIFF_FAILED`, `ORCHESTRATOR_FAILED`,
`HYPERGERY_ERROR` (400), `INTERNAL_ERROR` (500).

## Endpoints

### GET

| Endpoint | Data |
| --- | --- |
| `/health` | service status |
| `/hosts` | unified host registry (local + Hub + roles/capabilities/battery) |
| `/hosts/{id}` | one host + non-destructive health check |
| `/telemetry` | local sample (CPU/RAM/disk/battery/uptime/interfaces) + alerts |
| `/labs?subject=&favorites=&archived=&tag=` | labs with workspace filters |
| `/labs/{id}` | lab manifest + validation result |
| `/vms` | local + Hub VM inventory (VmInfo shape) |
| `/vms/{id}` | one VM |
| `/nas/status` | NAS health + last 20 commits |
| `/battery` | battery state (tier, thresholds) + recommended actions |
| `/orchestrator/plan?lab_id=` | explainable placement plans |
| `/logs?category=&level=&operation_id=&contains=&limit=` | structured events |
| `/network` | per-lab networks + conflict validation |
| `/guests` | users with effective permissions (no secrets) |
| `/external-nodes` | registered external nodes + health |

### POST

| Endpoint | Body | Notes |
| --- | --- | --- |
| `/orchestrator/dry-run` | `{"lab_id": "", "allow_remote": true}` | plans only, never executes |
| `/teleport/dry-run` | `{"vm_name": "", "target_host_id": ""}` | full validation, copies nothing |
| `/teleport/start` | `{"vm_name": "", "mode": "", "target_host_id": "", "staging_dir": "", "confirm": true}` | **requires `"confirm": true`**; modes per teleport engine |

## Safety

- Read endpoints are non-destructive; the only mutating endpoint is
  `/teleport/start`, which requires explicit confirmation and inherits the
  teleport engine's safety rules (source never deleted, rollback on failure).
- The API never returns credentials and stores none.
- A missing dependency (no NAS configured, no local backend) returns a clear
  `HYPERGERY_ERROR` instead of a stack trace.
