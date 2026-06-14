# V1_MANUAL_SMOKE_RESULT — smoke real con dos hosts físicos (2026-06-06)

Ejecución del checklist de `V1_MANUAL_SMOKE.md` sobre hardware real.
Rama `develop` @ `84cba53` (== `origin/develop`). Sin features nuevas, sin
cambios de runtime, sin merge a main, sin tag.

## Entorno

| Componente | Detalle |
| --- | --- |
| Host 1 (sobremesa, "PC de casa") | `gerard-MS-7E26`, AMD Ryzen 7 7700X, 30 GiB RAM, rol `home_pc` — el smoke se ejecutó desde aquí |
| Host 2 (portátil) | `gery-Lenovo-ideapad-330S-14IKB`, 192.168.1.73, i5-8250U, 19 GiB RAM, batería real |
| NAS / Hub | QNAP "ALPO" 192.168.1.150, Hub Docker v0.8 en `:8765` |
| Hub URL efectiva | `http://192.168.1.150:8765` (default v0.7+; confirmada con `/health` y `/hosts`) |
| NAS data | share `Gerard/hypergery`; accedida vía montaje fstab `/home/gerard/NAS_Gerard/hypergery` con `HYPERGERY_NAS_STAGING_PATH` (el bind no-persistente `/mnt/hypergery-nas` no estaba montado; sudo interactivo no disponible en la sesión) |

## Resultados

| # | Prueba | Resultado | Evidencia |
| --- | --- | --- | --- |
| 1 | Push de develop | PASS (ya hecho) | `develop` == `origin/develop` @ `84cba53`, 0 ahead/0 behind |
| 2 | Hub online | PASS | `GET /health` → `{"ok": true}` |
| 3 | Agent sobremesa online | PASS | heartbeat continuo, `status: online` en `/hosts` |
| 4 | Agent Lenovo online | PASS | arrancado por SSH (`setsid nohup … cli agent run`); online en <15 s |
| 5 | `v1 health` | PASS | hosts online, batería degrada a `unavailable` en sobremesa (sin batería — correcto) |
| 6 | `v1 hosts` (registro unificado) | PASS | 2 hosts, roles `home_pc`/`unknown`, RAM real |
| 7 | `v1 telemetry` | PASS | CPU 35.5%, disco real, `alerts: []` |
| 8 | `v1 battery` (hardware real) | PASS | en el Lenovo: 55%, `not_charging`, tier `normal`, 0 acciones |
| 9 | `v1 labs validate` | PASS | detectó conflicto REAL preexistente: labs `hg-v03-par` e `importar` comparten `192.168.197.0/24` (dato de usuario, no bug — el validador funciona) |
| 10 | `v1 network validate` | PASS | mismos conflictos CIDR/DHCP/gateway detectados coherentemente |
| 11 | NAS commit dry-run | PASS | plan con `lab_manifest.json`, 1454 bytes, `dry_run: true` |
| 12 | NAS commit `--confirm` REAL | PASS | `commit-2026-06-06T105937Z0000-83442881` escrito en `labs-commits/default-lab/` del NAS, `verified: true` |
| 13 | NAS restore `--confirm` REAL | PASS | restaurado a `/tmp/hg-smoke-restore`, hash validado, `verified: true`, nada vivo tocado |
| 14 | `v1 orchestrator plan` | PASS | 6 planes explicables (weight/battery_tier/fallback/confidence); nunca ejecuta |
| 15 | API v1 (`api serve` + curl) | PASS | `/health`, `/hosts` (2 hosts reales), `/battery`, `/orchestrator/plan` (6 planes); envelope estable; endpoint desconocido → error JSON; `/teleport/start` sin `confirm` → rechazado |
| 16 | `v1 guests list` (RBAC) | PASS | `{"users": []}` (sin usuarios definidos; sin traceback) |
| 17 | Teleport dry-run → Lenovo | PASS | preflight OK, target online comprobado, `source_will_be_deleted: false` |
| 18 | Teleport `local_loopback` REAL | PASS (con hallazgo) | 1er intento FAIL limpio: ISO adjunta en `/mnt/hypergery-nas/...` no montado → error claro, origen intacto. Reintento con `--no-iso` (flag existente): importada `hg-v06-2host-source-loopback` con UUID regenerado (`9ede2302…` → `c714b0e4…`) |
| 19 | **Teleport host→host REAL (2 máquinas físicas)** | **PASS** | `hg-v06-2host-source` (sobremesa) → `hg-smoke-v1-teleport` (Lenovo) vía Hub Transfer, `suspend_copy_start`, `--no-iso`. Migración `hg-v06-2host-source-144e561c1ed4` → `done` en ~80 s. VM **ejecutando** en el Lenovo, UUID regenerado (`2efc6883…`), MAC nueva (`52:54:3b:a7:5b:f8`), origen intacto |
| 20 | Hub staging limpiado tras import | PASS | `GET /packages` → 0 paquetes |
| 21 | `save_restore` — mecanismo + rollback seguro | PASS | con VM encendida real: congeló, detectó fichero de estado root-owned ilegible, **reanudó la VM localmente** (verificado `running`) y devolvió error accionable. Nada perdido |
| 22 | `save_restore` — envío cross-host | BLOCKED (limitación documentada) | en `qemu:///system` el saved-state es root-owned; necesita qemu:///session, storage compartido o ACL (ya documentado en `docs/API_V1.md` y `TEST_RESULTS_V1.md`). No es regresión |
| 23 | Detección host offline | PASS | agente Lenovo parado → `offline` en `v1 hosts`; rearrancado → `online` en <15 s |
| 24 | UI Control Center (manual, GUI) | SKIP | requiere sesión gráfica interactiva; cubierto por los tests Qt offscreen de la suite (verde) |
| 25 | Limpieza post-smoke | PASS | loopback VM + `hg-smoke-v1-teleport` + staging temporal borrados. VMs originales intactas: sobremesa (`hg-v06-2host-source`, `hg-v06-e2e-source`, `ubuntu`), Lenovo (`ubuntu-hub-e2e`, `ubuntu-migrated`, `ubuntu-test-v07`) |

**Totales: 23 PASS · 0 FAIL · 1 BLOCKED (limitación conocida de entorno) · 1 SKIP (GUI manual)**

## Comandos principales usados

```bash
# Agentes
ssh gery@192.168.1.73 'setsid nohup ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli agent run >/tmp/hypergery-agent.log 2>&1 &'
curl http://192.168.1.150:8765/health && curl http://192.168.1.150:8765/hosts

# v1 CLI
PY=~/.venvs/hypergery/bin/python
$PY -m hypergery_ubuntu.cli v1 health
$PY -m hypergery_ubuntu.cli v1 hosts
$PY -m hypergery_ubuntu.cli v1 telemetry
$PY -m hypergery_ubuntu.cli v1 battery            # en el Lenovo por SSH
$PY -m hypergery_ubuntu.cli v1 labs validate
$PY -m hypergery_ubuntu.cli v1 network validate
$PY -m hypergery_ubuntu.cli v1 orchestrator plan
$PY -m hypergery_ubuntu.cli v1 guests list

# NAS real (montaje fstab + override de ruta)
export HYPERGERY_NAS_STAGING_PATH=/home/gerard/NAS_Gerard/hypergery
$PY -m hypergery_ubuntu.cli v1 nas status
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --confirm
$PY -m hypergery_ubuntu.cli v1 nas restore --lab default-lab \
  --commit-id commit-2026-06-06T105937Z0000-83442881 \
  --destination /tmp/hg-smoke-restore --confirm

# API
$PY -m hypergery_ubuntu.cli v1 api serve &   # + curls a /health /hosts /battery /orchestrator/plan
# Teleport
$PY -m hypergery_ubuntu.cli v1 teleport dry-run --vm hg-v06-2host-source --target gery-Lenovo-ideapad-330S-14IKB
$PY -m hypergery_ubuntu.cli v1 teleport loopback --vm hg-v06-2host-source --staging-dir /tmp/hg-smoke-teleport --no-iso
# host→host: TeleportEngine.teleport_vm(mode="suspend_copy_start", target_host_id=…, include_iso=False)
$PY -m hypergery_ubuntu.cli v1 teleport save-restore --vm hg-v06-e2e-source --target gery-Lenovo-ideapad-330S-14IKB
```

## Errores / hallazgos (sin maquillar)

1. **ISO ausente bloquea teleport** (esperado): la VM de prueba referencia una
   ISO bajo `/mnt/hypergery-nas/` (bind no montado). Error claro, origen
   intacto, y `--no-iso` lo resuelve. Causa: el bind mount `/mnt/hypergery-nas`
   es no-persistente. **Fix mínimo propuesto** (operativo, no de código):
   añadir el bind a fstab o usar systemd mount unit.
2. **`save_restore` cross-host bloqueado en `qemu:///system`** (limitación ya
   documentada antes del smoke): saved-state root-owned. La recuperación segura
   (resume local) funcionó en real. Fix posible (v1.x): ACL/cap de lectura o
   modo de export vía libvirt managed-save API con permisos delegados.
3. **Conflicto de subred real entre labs `hg-v03-par` e `importar`**: dato
   preexistente del usuario que el validador detecta correctamente. Acción
   sugerida: reasignar subred de uno de los dos labs desde la UI/CLI.
4. **Rol del Lenovo = `unknown`** en el host registry (cosmético; los roles se
   asignan por configuración). Candidato a doc/UX de v1.1.

Ningún fallo de código nuevo: cero cambios de runtime durante el smoke.

## Decisión final

> **APTO PARA v1.0-rc1.**

El flujo crítico (Hub + 2 agentes físicos + NAS real + API + orchestrator +
teleport host→host con dos máquinas físicas + rollback seguro de
`save_restore`) está validado en real sin fallos críticos. Los dos puntos
abiertos (`save_restore` cross-host por permisos de libvirt y el bind mount
no persistente) son de entorno/operativa y están documentados — no bloquean
una release candidate.

Pendiente de decisión explícita del usuario (no ejecutado, según las reglas):
merge a `main`, creación del tag `v1.0-rc1` y release notes.
