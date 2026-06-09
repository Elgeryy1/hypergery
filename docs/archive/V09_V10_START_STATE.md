# V0.9 / V1.0 — Estado inicial (2026-06-06, sesión nocturna)

## Branch y commits

- Branch: `develop` (== `origin/develop`, ecddd3f)
- Últimos commits: cierre de v0.8 (Fases 1–6 implementadas, Hub NAS recargado
  y verificado, agent del portátil actualizado, docs alineadas).
- `main` en v0.7.0 — intocable esta sesión.

## Tests iniciales

- `QT_QPA_PLATFORM=offscreen ~/.venvs/hypergery/bin/python -m pytest` →
  **315 passed** (53s). pytest 9.0.3 y psutil instalados esta noche en el venv
  (no estaban; la suite es unittest y pytest la recoge sin cambios).

## Stack detectado

- Python 3.14 (venv `~/.venvs/hypergery`, editable sobre el repo) + libvirt
  (`virsh`/`qemu-img`) como backend real.
- UI: PySide6/Qt (`hypergery_ubuntu/ui_qt/`, QSS design tokens v0.7).
- Control plane: `hypergery_ubuntu/registry/` (Hub HTTP JSON en NAS Docker,
  SQLite local al contenedor; staging en NAS).
- Agent: `hypergery_ubuntu/agent.py` (poll del Hub, allowlist doble).
- Labs/Templates: manifests JSON (`labs.py`, `templates.py`).
- Migración: `migration.py` (paquetes con manifest+checksums, NAS o Hub
  Transfer) — base directa para Teleport v1.
- CLI: `cli.py` argparse (`hub`, `agent`, `host`, `migrate`, `lab`, …).
- Config: `config.py` (`HyperGeryConfig` JSON + env overrides + defaults).
- Tests: `hypergery-ubuntu/tests/` unittest (Qt offscreen incluidos).

## Recursos del entorno

- Batería real: `/sys/class/power_supply/BAT0` (57%, Not charging) → el
  BatteryService podrá probarse en hardware real.
- Hub NAS v0.8 online (`http://192.168.1.150:8765`); Lenovo agent online;
  PC de casa offline (loopback/simulated para lo que lo requiera).
- Sin credenciales nuevas necesarias; gh autenticado para push a develop.

## Riesgos

1. Alcance enorme (20 fases) → priorización del §26 del goal; cada módulo
   queda como mínimo con modelo+servicio+UI mínima+tests+docs.
2. No romper los 315 tests existentes → pytest tras cada bloque.
3. Operaciones reales (libvirt/NAS): todo lo nuevo nace con dry-run por
   defecto y providers simulados para tests.
4. PC de casa offline → teleport real `suspend_copy_start` solo validable en
   local_loopback; smoke manual documentado.

## Plan resumido

Nuevo subpaquete `hypergery_ubuntu/v1/` con servicios conectados a lo
existente (no arquitectura colgada): `errors` (jerarquía sobre
`HyperGeryError`), `hglog` (logs estructurados JSONL + operation_id),
`telemetry` (psutil + fallback /proc//sys), `hosts` (registry unificado
config+Hub+loopback), `labsx` (subject/tags/validate), `providers`
(Local/Agent/Simulated), `nas` (commit/restore con checksums, dry-run),
`orchestrator` (reglas explicables → PlacementPlan), `battery` (sysfs real),
`teleport` (dry_run/local_loopback/suspend_copy_start sobre migration.py),
`memdiff` (deltas por bloques), `networks` (validación CIDR), `rbac`
(roles/permisos/audit), `external_nodes`, `api` (HTTP JSON envelope).
UI: página "Control Center" con tabs por módulo + CLI `v1 …`. Testing masivo
con flujos de integración 1–5 y docs finales (reports, smoke, handover).
