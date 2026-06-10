# V09_REPORT — HyperGery v0.9 (Core Stabilization + Hosts/Telemetry/Labs/VMs/NAS)

## Qué cambió en v0.9

Sobre la base v0.8 (cerrada, 315 tests), v0.9 añade la capa de servicios
`hypergery_ubuntu/v1/` con foco en robustez:

1. **Core** (`errors.py`, `hglog.py`, `settings.py`)
   - Jerarquía de errores con códigos estables (HOST_OFFLINE, NAS_UNAVAILABLE,
     TELEPORT_FAILED, BATTERY_UNAVAILABLE, LAB_INVALID, NETWORK_CONFLICT,
     PERMISSION_DENIED, …) sobre `HyperGeryError` — sin stacktraces feos en
     UI, detalle técnico en logs.
   - Logging estructurado JSONL con campos timestamp/level/category/module/
     host/lab_id/vm_id/operation_id/message/details, ring buffer, filtros,
     export y `new_operation_id()` para operaciones largas.
   - `V1Settings`: configuración central tipada (umbrales de batería y RAM,
     modo offline, dry-run por defecto, timeouts, log level, flags
     experimentales, host/puerto de la API) con persistencia JSON, overrides
     `HYPERGERY_V1_*` y validación estricta.

2. **Hosts & Agents** (`hosts.py`)
   - Modelo `HostInfo` (roles laptop/home_pc/nas/isard/guest/unknown,
     capacidades allowlist, batería, tags) y `HostRegistry` que une la
     muestra local viva con los hosts del Hub (duplicado local omitido,
     fallos del Hub degradan a solo-local, `offline_mode` evita la red),
     host loopback para pruebas y `health_check` no destructivo (HTTP
     `/health` con latencia si hay `agent_url`).

3. **Telemetry** (`telemetry.py`)
   - Muestreo local con psutil y fallback /proc//sys (CPU, RAM, disco,
     batería sysfs, uptime, interfaces), historial JSON por host limitado a N
     muestras, muestras remotas desde el Hub con detección de staleness, y
     `evaluate_alerts()` (ram_low, disk_low, battery eco/low/emergency/
     critical —silenciado cargando—, host_offline, nas_offline).

4. **Labs workspace** (`labs.py` + `labsx.py`)
   - Manifest v0.9: subject (ASR/PAR/ISO/SAD/DB/WEB/CUSTOM), owner, tags,
     favorite, archived, last_started_at — con migración segura.
   - `validate_lab()` (ids, nombres VM únicos/válidos, roles, subject,
     subnet y solapes contra otros labs, almacenamiento opcional) y
     `filter_labs()`.

5. **VM control** (`providers.py`)
   - Interfaz `VMProvider` y tres providers: `LocalProvider` (libvirt, con
     pause/resume vía virsh suspend/resume), `AgentProvider` (cola del Hub —
     las acciones no allowlisted lanzan error en vez de fingir) y
     `SimulatedProvider` (transiciones realistas + snapshots para tests).

6. **NAS** (`nas.py`)
   - `NasService`: health con sonda de escritura, `commit_lab` (valida el
     lab, empaqueta manifest+VMs+discos opcionales con sha256, staging
     `.partial` + rename atómico, verificación post-copia, dry-run por
     defecto), `list_commits`, `verify_commit`, `restore_commit` (validado
     por hash, jamás sobrescribe, jamás toca VMs vivas).

## Commits principales

`docs(v09): record v09 v10 start state` · `feat(v09): add v1 core errors,
structured logging, and settings` · `feat(v09): add advanced host registry
and unified telemetry with alerts` · `feat(v09): expand labs workspace and
add vm provider abstraction` · `feat(v09): implement nas commit and restore
workflow`

## Tests

64 tests nuevos específicos de v0.9 (core 13, hosts/telemetry 20,
labs/providers 21, NAS 10); suite total verde (ver TEST_RESULTS_V1.md).

## Cómo usar

```bash
python -m hypergery_ubuntu.cli v1 health
python -m hypergery_ubuntu.cli v1 telemetry
python -m hypergery_ubuntu.cli v1 labs validate
python -m hypergery_ubuntu.cli v1 nas status
python -m hypergery_ubuntu.cli v1 nas commit --lab <lab> --dry-run
```

## Limitaciones

- La telemetría remota deriva de los heartbeats del Hub (sin agente HTTP
  dedicado todavía; `agent_url` queda preparado).
- El historial de telemetría es JSON local (suficiente para N muestras; no
  hay base de datos de series temporales).
- `pause/resume` remotos no existen (no están en la allowlist Hub/Agent, a
  propósito).
- El commit NAS empaqueta metadatos por defecto; discos solo con
  `--include-disks` (pueden ser grandes).
