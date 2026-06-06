# ARCHITECTURE_V1 — HyperGery v0.9/v1.0

## Diagrama (textual)

```text
            ┌────────────────────────── Qt App ───────────────────────────┐
            │ Dashboard · VMs · Labs · Remote Hosts · Migrations ·        │
            │ Commands · Control Center (v1 tabs) · Diagnostics           │
            └──────┬───────────────────────────────────────────┬─────────┘
                   │                                           │
        v0.x backend (libvirt/virsh)                 v1 services (hypergery_ubuntu/v1)
                   │                                           │
   ┌───────────────┴───────┐      ┌────────────────────────────┴──────────────────────────┐
   │ HyperGeryBackend      │      │ settings ── hglog (JSONL + operation_id) ── errors    │
   │ LabStore/TemplateStore│      │ telemetry ─ hosts(HostRegistry) ─ battery             │
   │ migration.py          │◄─────│ providers(Local/Agent/Simulated)                      │
   └───────────┬───────────┘      │ labsx(validate/filter) ─ networks ─ rbac ─ ext.nodes  │
               │                  │ nas(commit/restore) ─ memdiff ─ teleport ─ orchestr.  │
               │                  │ api (HTTP envelope)  ─ cli_v1                          │
               │                  └───────────────┬───────────────────────────────────────┘
               ▼                                  │
        Hub (NAS Docker, registry/) ◄─────────────┘    App → Hub → Agent → libvirt
        hosts · vms · commands · migrations · packages · staging cleanup
               ▲
               │ poll
        Agents (agent.py) en cada host
```

## Servicios y modelos

- **V1Settings**: knobs centrales (umbral batería/RAM/disco, offline, dry-run,
  flags experimentales, API). Archivo JSON + env `HYPERGERY_V1_*`.
- **StructuredLogger**: eventos JSONL con categorías fijas y `operation_id`
  para agrupar operaciones largas (nas-commit, teleport, orchestrator…).
- **HostInfo/HostRegistry**: vista unificada local+Hub+loopback con roles y
  capacidades; health checks no destructivos.
- **TelemetrySample/TelemetryService**: psutil + fallback /proc //sys;
  historial JSON; alertas puras.
- **VmInfo/VMProvider**: superficie uniforme de control de VMs con
  implementación real local, remota vía cola del Hub (solo allowlist) y
  simulada para tests.
- **NasService**: commits de labs con checksums y restore validado.
- **BatteryService/BatteryState**: tiers y acciones recomendadas por modo.
- **OrchestratorService/PlacementPlan**: motor puro y explicable; consume
  hosts+vms+batería; produce planes con razón, confianza, acciones y
  warnings. No ejecuta.
- **TeleportEngine**: 4 modos sobre `migration.py`; siempre conserva el
  origen; rollback con resume.
- **MemDiff**: snapshots/deltas por bloques con verificación obligatoria.
- **Network**: redes lógicas por lab + detección de conflictos.
- **RBAC**: roles/permisos/audit local (sin credenciales).
- **ExternalNode**: nodos de cómputo externos manuales → HostInfo.
- **ApiContext/ApiServer**: API JSON con envelope estable para Android Hub.

## Flujos clave

1. **Auto-Boost**: telemetry+battery+hosts → orchestrator.plan() →
   PlacementPlan[] → (humano o API dry-run) → teleport engine.
2. **Teleport funcional**: target online → suspend (si running) → export
   package (manifest+checksums) → upload Hub → command import → start →
   inventario refrescado. Fallo ⇒ resume + paquete conservado.
3. **NAS commit**: validate lab → plan → staging .partial → checksums →
   rename → verify → registro con operation_id.
4. **Battery offload**: tier offload/emergency → acciones recomendadas →
   plan del orchestrator hacia home_pc (nunca auto-ejecutado salvo acciones
   data-safe en auto_execute_safe).

## Decisiones

- v1 vive en un subpaquete: cero riesgo para v0.8 (suite intacta).
- Todo lo potencialmente costoso/destructivo nace dry-run u opt-in.
- Los servicios son puros/inyectables: el mismo código corre contra
  hardware real, Hub real o fakes (los 5 flujos de integración lo prueban).
- La API y la UI Control Center comparten los mismos servicios (sin lógica
  duplicada).

## Límites conocidos

- No hay live-RAM migration: `suspend_copy_start` mueve con pausa;
  `experimental_memdiff` solo estima deltas. Honesto por diseño.
- API/UI sin autenticación (LAN de confianza) hasta v1.2.
- Telemetría remota = heartbeats del Hub (sin push en tiempo real).
