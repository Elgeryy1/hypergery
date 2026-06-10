# GOAL_PROGRESS — noche autónoma (inicio: 2026-06-09)

> Memoria viva del agente. Si el contexto se compacta: leer esto y continuar.
> Plan maestro: `goalplan.md` (raíz del repo). Orden de milestones: §10.

## Estado global

- **Baseline verificado:** `main` @ 2148aec — `compileall` OK, `pytest -q` = **667 passed, 1 skipped** (30.8s), venv `~/.venvs/hypergery` (Python 3.14).
- **Milestone actual:** M11 — v1.6 app Android nativa.
- **Ramas:** las ramas de milestone van encadenadas (cada una parte de la anterior) para no perder la versión 1.1.0.dev0 ni este fichero: `feat/v1.1-app-identity` → `feat/v1.1-jobmanager` → …

## Milestones (orden §10 del goalplan)

| # | Milestone | Estado |
|---|-----------|--------|
| 1 | v1.1 identidad app + .deb + --version/About | HECHO |
| 2 | v1.1 JobManager + closeEvent + throttle preview (TD-3, 0008/0015) | HECHO |
| 3 | v1.1 Hub robusto (busy_timeout/WAL, TTL, upload) (0005/0006/0010) | HECHO |
| 4 | v1.1 redes coherentes + colisión octetos (0009/0012/0016) | HECHO |
| 5 | v1.1 needsRealLibvirt + higiene (0011/0017/0018, retirar Tk) | HECHO |
| 6 | v1.2 token/TLS + RBAC enforced + audit log (0001, TD-5) | HECHO |
| 7 | v1.3 Template Store + Backup Verifier + snapshots + tags | HECHO |
| 8 | v1.4 orchestrator aplicable + /telemetry + health + API companion | HECHO |
| 9 | v1.5 prep migration_engine (TD-4) + canal progreso (TD-9) | HECHO |
| 10 | v1.5 live migration en caliente + preflight + wizard | HECHO (código+tests; UAT físico en cola; wizard UI pendiente) |
| 11 | v1.6 app Android nativa | EN CURSO |
| 12 | v1.7 GPU passthrough VFIO | pendiente |
| 13 | v2.0 investigación | pendiente |

## M1 — v1.1 identidad de app (HECHO)

- Rama `feat/v1.1-app-identity` (pusheada). Commits: a10aa5d (versión única + --version), a8a0c58 (icono/About/.desktop/.deb).
- Cierra la mitad "versión duplicada" de HG-BUG-0017 (queda app_tk.py para M5). Versión bump a 1.1.0.dev0.
- `--version` en hypergery / hypergery-cli / hypergery-agent. Icono de app por código + SVG.
- `scripts/build-deb.sh` construye `dist/hypergery_1.1.0~dev0_all.deb` (verificado: dpkg-deb info/contents OK; artefacto generado en `dist/`).
- Gates: compileall OK; pytest = 677 passed, 1 skipped (10 tests nuevos en test_app_identity.py, incluye build real del .deb).
- **U1 parcial → cola UAT humano:** no hay sudo sin contraseña, instalación/desinstalación real del .deb pendiente de Gerard: `sudo apt install ./dist/hypergery_1.1.0~dev0_all.deb`, comprobar menú/icono/`hypergery --version`, `sudo apt remove hypergery`, verificar que ~/.config/hypergery y datos sobreviven.
- **ACTUALIZACIÓN 2026-06-10: U1 PASS completo.** El primer intento falló por cwd (script/dist viven en la raíz del repo) y un venv editable anterior al entry point `hypergery-agent`; arreglado en la rama `fix/v1.1-packaging-uat` (wrapper + tests de packaging). Resultado real en `docs/qa/V1_1_UAT_RESULT.md` y causa raíz en `docs/qa/V1_1_PACKAGING_UAT_FIX.md` (ambos en esa rama).

## M2 — v1.1 JobManager + closeEvent + throttle preview (HECHO)

- Rama `feat/v1.1-jobmanager` (encadenada sobre M1, pusheada).
- TD-3: nuevo `ui_qt/jobs.py` (JobManager: submit/active/completed/shutdown con espera acotada y supresión de callbacks); `BackendJob.cancel()` cooperativo en workers.py.
- HG-BUG-0008: `MainWindow.closeEvent` cierra consolas, `job_manager.shutdown(5s)` acotado, log de supervivientes.
- HG-BUG-0015: throttle de preview (1 captura en vuelo por VM, mínimo 2s entre capturas, reintento único programado al expirar el cooldown → la vista no queda obsoleta).
- `run_operation` y `_capture_preview` enrutan por JobManager (las listas self.jobs/completed_jobs/_preview_jobs desaparecen).
- Gates: compileall OK; pytest = 690 passed, 1 skipped (13 tests nuevos en test_qt_jobs.py).
- U2 (closeEvent no cuelga con jobs en curso): cubierto por test automatizado PASS.

## M3 — v1.1 Hub robusto (HECHO)

- Rama `feat/v1.1-hub-robustness` (encadenada sobre M2, pusheada).
- HG-BUG-0005: `RegistryStore.connect()` con busy_timeout 5s + synchronous NORMAL; `journal_mode=WAL` persistente en `_init_db`.
- HG-BUG-0006: columna `expires_at` + TTL en `create_command` (default 600s, clamp 10s–24h, `ttl_seconds` en payload); `_expire_pending_commands` corre en get/list/pending/set_result; comando caducado → `failed` con `result.expired=true`, jamás se entrega y su resultado no puede sobrescribirse; comandos ya `running` no caducan.
- HG-BUG-0010: límite de upload por fichero (`max_upload_bytes`, env `HYPERGERY_HUB_MAX_UPLOAD_MIB`, default 64 GiB) → 413; chequeo de espacio libre con margen 1 GiB → 507; Content-Length ausente/0/no numérico → 400.
- Gates: compileall OK; pytest = 705 passed, 1 skipped (15 tests nuevos en test_registry_robustness.py).
- UAT automatizable: U3 (concurrencia Hub, 8 escritores × 10 iteraciones sin "database is locked") PASS; U4 (TTL) PASS; U5 (límite upload 413/507/400) PASS.

## M4 — v1.1 redes coherentes (HECHO)

- Rama `feat/v1.1-networks` (encadenada sobre M3, pusheada).
- HG-BUG-0009: `network_from_lab` deriva la subred REAL (`192.168.<octeto-hash>.0/24`) cuando el manifiesto no trae `subnet`; nuevo `networks_from_labs` para construir el tab de Redes (UI, /network del API v1 y `v1 network validate` del CLI actualizados) → fin de los falsos "missing CIDR"/conflictos duplicados.
- HG-BUG-0012: `allocate_network_octet` (sondeo determinista sobre espacio de 219 octetos, registro de usados); `ensure_network` consulta los octetos de las redes hg-net-* existentes y define la nueva red en el primer octeto libre; `reconcile_existing_network` conserva IPs reasignadas válidas y solo recicla colisiones/IPs inválidas.
- HG-BUG-0016: `net-define`/`net-start` toleran la carrera benigna (otro proceso define/arranca la misma red); fallos reales siguen lanzando error con el stderr de virsh.
- Gates: compileall OK; pytest = 721 passed, 1 skipped (16 tests nuevos en test_networks_coherence.py).
- UAT automatizable: U6 (redes sin conflictos espurios + colisión resuelta) PASS por tests.

## M5 — v1.1 needsRealLibvirt + higiene (HECHO)

- Rama `feat/v1.1-real-libvirt-hygiene` (encadenada sobre M4, pusheada).
- HG-BUG-0011: marcador `needsRealLibvirt` (conftest.py + pyproject markers; skip sin virsh o sin `HYPERGERY_REAL_LIBVIRT=1`). Suite `tests/test_real_libvirt.py` §5 items 1–6: crear VM trivial hgtest- → dominfo; export → checksums sha256 verificados; import con nombre nuevo → UUID y MAC regenerados; start/ACPI/force-off por estados (VM REAL arrancada bajo KVM); import con paquete corrupto → rollback (destino limpio, origen intacto); delete_disks solo borra la VM de prueba. **Ejecutada en el host real: 6/6 PASS (11.9s); host limpio después (solo quedan las VMs/redes preexistentes).** Datos en HYPERGERY_DATA_HOME temporal; solo VMs hgtest-* y lab hgtest-lab-real.
- HG-BUG-0017 (resto): app_tk.py eliminado → ya no existe ninguna versión duplicada; test de versión única sin exclusiones.
- HG-BUG-0018: eliminados HTML/zip de diseño (~5MB) de docs/design/v0.7 (recuperables del historial git); V09/V10_REPORT, V09_V10_START_STATE, RESUMEN_EJECUTIVO_SESION, FINAL_V09_V10_HANDOVER movidos a docs/archive/. TD-7: app_tk retirado; dev-run.sh sin --legacy-tk; ARCHITECTURE.md actualizado.
- Gates: compileall OK; pytest = 721 passed, 7 skipped (6 = suite real gated + 1 preexistente); con HYPERGERY_REAL_LIBVIRT=1 → 6/6 PASS reales.

## M6 — v1.2 seguridad Hub/API (HECHO)

- Rama `feat/v1.2-hub-security` (encadenada sobre M5, pusheada).
- **HG-BUG-0001 (Hub):** `registry/auth.py` — token bearer obligatorio por defecto (env `HYPERGERY_HUB_TOKEN` > fichero `hub_token` 0600 autogenerado junto a la DB); 401 sin/con token erróneo (comparación constante con hmac); `GET /health` abierto; rate limit anti fuerza bruta (10 fallos/60s por IP → 429); cada rechazo auditado en eventos del Hub (`auth_failure`); `--no-auth` explícito (con warning) para LAN de confianza; bind por defecto sigue 127.0.0.1.
- Cliente/agente: `RegistryClient(token=...)` añade `Authorization: Bearer` en request() y en upload/download; config con campo `hub_token` (fichero config ahora 0600); `AgentConfig.registry_token` (redactado en `config show`); docker-compose pasa `HYPERGERY_HUB_TOKEN`.
- **TD-5 (API v1):** `v1/auth.py` — token de propietario (SuperAdmin, `api_token` 0600) + tokens por usuario (`api_tokens.json` 0600, `v1 guests token <user>` / `--revoke`); RBAC enforced en `v1/api.py`: 401 sin token; lecturas → can_view_labs; /guests → can_manage_guests; orchestrator/dry-run → can_use_remote_compute; teleport/* → can_teleport; require_permission audita en hglog; tests de escalada (Guest con extra_permissions prohibidos sigue 403; token revocado → 401).
- Pairing: `hypergery-cli hub pairing-info` (URL+token+pair_uri, aviso de secreto). TLS: `docs/HUB_SECURITY.md` (Caddy/nginx, VPN/SSH, nunca exponer a Internet).
- Gates: compileall OK; pytest = **742 passed, 7 skipped** (21 tests nuevos en test_security_v12.py + harnesses actualizados).
- UAT automatizable: U7 (token/RBAC/escalada) PASS por tests.

## M7 — v1.3 backups + verifier + snapshots + tags (HECHO)

- Rama `feat/v1.3-backups-templates` (encadenada sobre M6, pusheada).
- **Backup policies NAS** (`v1/backups.py`): BackupPolicy (intervalo, retención, include_iso) + store JSON; `run_policy` exporta el paquete completo (formato migración, checksums) al NAS y poda copias antiguas (solo paquetes de esa VM bajo su root); `run_due` apto para cron. CLI: `v1 backup policy-add/policy-list/policy-remove/run/run-due`.
- **Backup Verifier** (`v1/backup_verifier.py`): valida checksums → restaura en VM temporal `hgtest-verify-*` (lab hgtest-lab-verify) → arranca → comprueba `running` → destruye dominio+discos (cleanup garantizado en finally; se niega a limpiar VMs ajenas). CLI: `v1 backup verify <package> [--keep-vm]`. **U8 ejecutado contra libvirt REAL: export → verify → boot bajo KVM → cleanup, PASS.**
- **Snapshot branching seguro**: `backend.branch_snapshot(vm, origen, rama)` — revert a snapshot conocido + snapshot nuevo; falla limpio si el origen no existe o la rama ya existe.
- **Tags por VM** (`LabStore.set_vm_tags`, manifest `vm_tags`) y **Resource Budget por lab** (`set_budget` + `check_lab_budget`, manifest `budget`). CLI: `lab set-vm-tags`, `lab set-budget`.
- Template Store ya existía (templates.py); no se reinventa.
- Gates: compileall OK; pytest = **762 passed, 8 skipped** (20 tests nuevos en test_v13_backups.py + test real nº7); suite real libvirt 7/7 PASS, host limpio.
- Pendiente v1.3 (no bloqueante, anotado): tareas programadas con UI propia (por ahora `run-due` vía cron), backup policies por lab completo.

## M8 — v1.4 orquestación + telemetría + companion (HECHO)

- Rama `feat/v1.4-orchestration-telemetry` (encadenada sobre M7, pusheada).
- **Telemetría de agente:** cada heartbeat incluye una muestra `telemetry` (cpu/ram/disco/batería/uptime, vía v1/telemetry, sin romper el heartbeat si falla); el Hub la persiste (columna `telemetry_json` en hosts) y la expone en /hosts.
- **Orchestrator aplicable:** `orchestrator.apply_plan(plan, teleport_engine, confirm=True)` — `stay`=no-op, `teleport`=delegado al TeleportEngine, NUNCA sin confirm. CLI `v1 orchestrator apply <vm> --confirm` (recalcula el plan de esa VM y lo aplica). API `POST /orchestrator/apply` (requiere can_use_remote_compute + can_teleport + confirm).
- **Health dashboard:** `GET /dashboard` — hosts (con telemetría), telemetría local, alertas, VMs por estado, batería.
- **API companion (superficie v1.6):** `POST /vms/<id>/start|shutdown|snapshot` — solo acciones seguras (ACPI, no force-off/delete); RBAC por acción (can_start_vm/can_stop_vm) con lab scoping para Guests; snapshot exige `{"confirm": true}` + nombre; VMs remotas → cola de comandos del Hub (queued=true). ApiContext acepta `backend`.
- Gates: compileall OK; pytest = **777 passed, 8 skipped** (15 tests nuevos en test_v14_orchestration.py).
- UAT automatizable: U9 (orchestrator apply local, plan stay/move con confirm) PASS por tests.

## M9 — v1.5 prep: migration_engine + progreso (HECHO)

- Rama `feat/v1.5-prep-migration-engine` (encadenada sobre M8, pusheada).
- **TD-9** `v1/progress.py`: contrato único de progreso (operation_id, kind, fase, percent, mensaje, métricas acumulativas, status, version); thread-safe; long-poll real (`wait_for_change(since_version, timeout)` con Condition); historial acotado de operaciones terminadas; singleton `get_progress_channel()`. Expuesto en el API v1: `GET /progress` (lista, filtros kind/active) y `GET /progress/<id>?since=&timeout=` (long-poll ≤60s) — lo consumirán la UI y la app Android.
- **TD-4** `v1/migration_engine.py`: fases preflight→transfer→switchover→activate, cada una `run`/`rollback`/report; rollback en orden inverso de lo completado sin enmascarar el error original; **invariante de oro verificado en construcción: ninguna fase puede declarar `touches_source` antes de switchover** (origen intacto hasta confirmar destino); cancelación cooperativa entre fases (→ rollback + estado cancelled); progreso ponderado por fase + callback de progreso fino con métricas (páginas, MB/s…). v1.5 enchufa aquí las fases reales.
- Gates: compileall OK; pytest = **794 passed, 8 skipped** (17 tests nuevos en test_v15_engine.py).

## M10 — v1.5 LIVE MIGRATION en caliente (HECHO: código + tests)

- Rama `feat/v1.5-live-migration` (encadenada sobre M9, pusheada).
- `v1/live_migration.py` sobre `virsh migrate` (= `virDomainMigrateToURI3` con VIR_MIGRATE_LIVE; no hay libvirt-python en el venv y todo el backend es virsh — coherente y honesto):
  - **Flags:** `--live --persistent --abort-on-error` (+ `--auto-converge` por defecto, `--postcopy --postcopy-after-precopy` opcional, `--copy-storage-all`/`--copy-storage-inc` para block migration, `--bandwidth`). **Sin `--undefinesource`**: el origen se limpia SOLO en la fase activate tras confirmar el destino (semántica UNDEFINE_SOURCE controlada).
  - **Preflight (solo lectura):** VM running; bloqueo de `<hostdev>` PCI passthrough (aviso v1.7); aviso CD-ROM local y host-passthrough CPU; conectividad/versiones destino; mismo host rechazado; nombre duplicado en destino rechazado; RAM libre del destino vs RAM de la VM; estrategia shared/block auto (override manual); estimación de downtime.
  - **Conexión segura:** solo `qemu+ssh://`/`qemu+tls://` (qemu+tcp rechazado).
  - **Progreso (TD-9):** poll de `virsh domjobinfo` → páginas/datos procesados/restantes, velocidad MiB/s, iteraciones pre-copy, dirty rate, ETA; **downtime real medido** con `domjobinfo --completed` (métrica `downtime_ms`).
  - **Rollback (`virDomainAbortJob`):** `domjobabort` + limpieza del destino SOLO si el origen sigue vivo; un destino ya promovido (running con origen parado) jamás se destruye; **invariante "nunca activa en dos hosts" verificado en activate (aborta si ambos running)**. La fase fallida se deshace primero y luego las completadas en orden inverso (motor TD-4 endurecido).
  - CLI: `hypergery-cli v1 migrate-live --vm X --target qemu+ssh://user@host/system [--shared-storage|--block-migration] [--incremental] [--postcopy] [--bandwidth-mibps N] --confirm`.
  - Migración offline existente queda como fallback (intacta).
- Gates: compileall OK; pytest = **815 passed, 8 skipped** (21 tests nuevos en test_v15_live_migration.py con host virsh simulado: preflight×7, flags×5, fallo/rollback/invariantes×4, parsing domjobinfo, URIs).
- **NO hecho (anotado):** wizard Qt de migración con fases (la lógica + canal de progreso están listos; UI pendiente de una sesión con Gerard); test live single-host real no es posible (virsh rechaza migrar a sí mismo) → cola UAT.

## Cola de UAT humano — live migration (NUEVO)

- **U10** PC→portátil shared storage: `hypergery-cli v1 migrate-live --vm hgtest-u10 --target qemu+ssh://gery@portatil/system --shared-storage --confirm`. Esperado: VM nunca apagada, downtime medido <1s (métrica downtime_ms en el resultado/progreso), origen undefined tras confirmar.
- **U11** block migration (sin NAS): mismo comando con `--block-migration`. Esperado: discos copiados por el canal de migración, resto igual.
- **U12** cancelar a mitad: lanzar U10/U11 y durante el pre-copy llamar `migrator.cancel()`/Ctrl-C (o `virsh domjobabort <vm>`): origen running e intacto, destino limpio, estado `cancelled` en /progress.

## M11 — v1.6 app Android nativa (HECHO: código + CI)

- Rama `feat/v1.6-android-app` (encadenada sobre M10, pusheada).
- Proyecto `android/` (Kotlin + Jetpack Compose, minSdk 26, Material3, sin wrapper binario por la política de no-binarios):
  - **Pairing seguro**: URL + token (de `hub pairing-info` / `v1 guests token`), validado con llamada autenticada real (/dashboard) antes de guardar; token en SharedPreferences privadas; mensajes claros para 401/403; soporta el `pair_uri` hypergery://pair.
  - **Dashboard**: hosts+telemetría, VMs por estado, alertas, batería y operaciones en curso con **long-poll real del canal TD-9** (/progress/<id>?since=&timeout=) — una live migration se ve avanzar.
  - **Inventario + acciones seguras**: arrancar / apagado ACPI / snapshot, todas con AlertDialog de confirmación; snapshot además exige nombre y confirm:true. Nada destructivo (verificado por test estático: la app no contiene force-off/undefine/delete).
  - ApiClient OkHttp con Bearer en todas las llamadas; permisos del manifest = solo INTERNET.
- CI: `.github/workflows/android.yml` (JDK17 + Gradle 8.9): `gradle test` (unit tests JVM de parsers) + `assembleDebug` + APK como artefacto.
- Suite python: `tests/test_android_static.py` (estructura, permisos mínimos, solo acciones seguras, confirmaciones, contrato de long-poll) → 5 PASS.
- **Honestidad:** sin Android SDK en este host el APK no se ha compilado localmente; lo compila el CI en el primer push. U13 (móvil real por VPN) → cola UAT.

## Cola de UAT humano — Android (NUEVO)

- **U13**: ver android/README.md — `v1 api serve` + `v1 guests token gerard` + parear el móvil por WireGuard/Tailscale; comprobar dashboard, inventario, start/ACPI/snapshot con confirmación, y el progreso en vivo de una operación.
- Bajar el APK del artefacto del workflow `android` en GitHub Actions (primer push de la rama ya lo construye).

## M12 — v1.7 GPU passthrough VFIO (HECHO: código + tests)

- Rama `feat/v1.7-gpu-passthrough` (encadenada sobre M11, pusheada).
- `v1/gpu_passthrough.py`:
  - **Detección (solo lectura):** `list_pci_gpus` (clase 0x03, vendor/driver/boot_vga/grupo IOMMU y sus dispositivos) e `iommu_status` (grupos + flags del cmdline).
  - **Preflight:** IOMMU activo; grupo IOMMU limpio (solo funciones del mismo slot, p. ej. GPU+audio HDMI); vfio-pci disponible; **PARADA DURA implementada y verificada: la GPU del escritorio (boot_vga/driver de display) se RECHAZA si no hay segunda GPU** (en este host con una sola iGPU i915 el preflight la bloquea — comprobado contra el /sys real); avisos NVIDIA (ocultar hipervisor), OVMF/UEFI y "no live-migrable".
  - **Cambios de host solo PROPUESTOS** (`propose-host-changes`: GRUB intel/amd_iommu=on + iommu=pt, módulos initramfs, applied=false, requires_reboot=true) — el agente jamás los aplica.
  - **VfioBinder:** bind a vfio-pci vía sysfs (driver_override→unbind→drivers_probe) con **rollback al driver original si el probe falla**; unbind de vuelta al host; confirm obligatorio.
  - **Domain XML:** `<hostdev>` PCI managed; si la GPU es NVIDIA (10de) añade `<kvm><hidden state=on>` + `hyperv vendor_id` (anti Code 43); detección de UEFI/OVMF con aviso si la VM usa BIOS legacy. `attach_gpu_to_vm` exige VM apagada + confirm + preflight ok.
  - La incompatibilidad con live migration ya la bloquea el preflight de v1.5 (M10) al ver `<hostdev>`.
- CLI: `v1 gpu list | iommu | propose-host-changes | preflight <addr> | bind <addr> --confirm | unbind <addr> [--driver] | attach --vm X --gpu <addr> --confirm`.
- Gates: compileall OK; pytest = **837 passed, 9 skipped** (17 tests con sysfs falso + test real §5.8). Suite real libvirt **8/8 PASS** (incluye detección IOMMU/GPU real y la garantía hard-stop sobre la iGPU del escritorio).
- **Cola UAT — U14:** requiere la 2ª GPU física: `v1 gpu preflight <addr>` → `v1 gpu bind <addr> --confirm` (root) → `v1 gpu attach --vm hgtest-... --gpu <addr> --confirm` → arrancar y `lspci` dentro del guest → apagar → `v1 gpu unbind <addr> --driver <orig>` y comprobar que el host recupera la GPU. La migración de esa VM debe bloquearse (preflight v1.5).

## M13 — v2.0 investigación (HECHO)

- Rama `feat/v2.0-research`. `docs/research/V2_0_RESEARCH.md`: HG-MEMDIFF propio → DESCARTADO con honestidad (usar dirty bitmaps/checkpoints de libvirt, prototipo 1-2 noches); dedup → delegar en backing files + filesystem; packet visualizer → MVP con contadores sysfs; vGPU → no prometer; SR-IOV i915 → solo presencial; Looking Glass → viable tras U14; plugins → posponer, el API v1 es la vía de integración.

# ═══════════════ RESUMEN DE MAÑANA (para Gerard) ═══════════════

## Lo que se hizo esta noche (13/13 milestones)

**v1.1 completa** (M1-M5): app instalable (.deb construido en `dist/hypergery_1.1.0~dev0_all.deb`), versión única + `--version`, JobManager + closeEvent + throttle de preview, Hub robusto (WAL/busy_timeout, TTL de comandos, límites de upload), redes coherentes (fin de los falsos conflictos; colisión de octetos resuelta), suite `needsRealLibvirt` **ejecutada contra el hipervisor real (8/8)**, app_tk retirada, repo deslastrado (~5MB).

**v1.2** (M6): Hub y API v1 con token bearer OBLIGATORIO (ficheros 0600, rate-limit anti fuerza bruta, auditoría de rechazos), RBAC enforced con tests de escalada, pairing (`hub pairing-info`), tokens por usuario (`v1 guests token`), docs de TLS/VPN.

**v1.3** (M7): políticas de backup al NAS con retención + **Backup Verifier ejecutado de verdad contra KVM** (restaura → arranca → limpia), snapshot branching seguro, tags por VM, presupuestos por lab.

**v1.4** (M8): telemetría en cada heartbeat (persistida en el Hub), orchestrator aplicable con confirmación, `GET /dashboard`, **API companion** (start/ACPI/snapshot con RBAC + lab scoping; nada destructivo).

**v1.5** (M9-M10): máquina de estados de migración (origen intocable hasta switchover, rollback inverso, cancelación) + canal de progreso con long-poll + **LIVE MIGRATION REAL** sobre `virsh migrate` (pre-copy, auto-converge, postcopy opcional, block migration, downtime medido, abort con origen intacto, nunca activa en dos hosts). 21 tests con host simulado.

**v1.6** (M11): app Android nativa (Kotlin+Compose) en `android/`: pairing seguro, dashboard con progreso en vivo (long-poll), acciones seguras con confirmación. CI listo en `android/ci/android.yml`.

**v1.7** (M12): GPU passthrough VFIO: detección, preflight con PARADA DURA (verificada contra tu iGPU real: se niega), bind con rollback, hostdev XML + anti-Code-43 NVIDIA, cambios de host solo propuestos.

**v2.0** (M13): investigación honesta en `docs/research/V2_0_RESEARCH.md`.

## Métricas

- pytest: **667 → 837 passed** (+170 tests nuevos), 9 skipped (8 = gated needsRealLibvirt+real-only, 1 preexistente). Cero regresiones en todas las ejecuciones.
- Suite real libvirt: **8/8 PASS** en gerard-MS-7E26 (VMs hgtest- creadas/arrancadas/migradas-offline/verificadas/borradas; host limpio al acabar — comprobado).
- 12 ramas pusheadas, encadenadas en orden: `feat/v1.1-app-identity` → … → `feat/v2.0-research`. **Sin tocar main, sin merges, sin tags** (regla respetada).
- Bugs cerrados: HG-BUG-0001, 0005, 0006, 0008, 0009, 0010, 0011, 0012, 0015, 0016, 0017, 0018, 0021*(parcial: el agente ya no traga el fallo de auth, registry_token visible)*. Deuda: TD-3, TD-4, TD-5, TD-7, TD-9 cerradas.

## Cola de UAT para ti (nada de esto bloquea; orden sugerido)

1. ~~**U1** instalar `dist/hypergery_1.1.0~dev0_all.deb` (sudo) y comprobar menú/icono/--version; desinstalar y ver que los datos sobreviven.~~ **PASS 2026-06-10** (`docs/qa/V1_1_UAT_RESULT.md`, rama `fix/v1.1-packaging-uat`).
2. **Activar el CI Android**: `git mv android/ci/android.yml .github/workflows/android.yml` (mi token git no tiene scope workflow) → el APK sale como artefacto.
3. **U10-U12** live migration PC↔portátil (comandos exactos en la sección M10).
4. **U13** app Android por WireGuard/Tailscale (pasos en android/README.md).
5. **U14** GPU passthrough con la 2ª GPU (pasos en la sección M12).
6. Revisar/mergear las 12 ramas en orden (cada una parte de la anterior, así que mergear `feat/v2.0-research` trae todo; o PRs individuales si prefieres revisar por milestone).

## Fallos abiertos / riesgos conocidos

- El wizard Qt de live migration no está (la lógica, CLI y progreso sí); decisión de UX para una sesión contigo.
- El APK no se ha compilado localmente (sin Android SDK en este host): lo valida el CI al activarlo.
- `agent.py` HG-BUG-0021 (tragar excepciones genéricas) solo se ha mitigado donde tocaba esta noche; barrido completo pendiente.
- HG-BUG-0013/0014/0019/0020/0022/0023 siguen abiertos (ninguno era de los milestones de esta noche).

## Siguiente paso recomendado

Mergear v1.1 (M1-M5) a develop tras pasar U1, y atacar el wizard de migración + HG-BUG-0022 (Control Center JSON crudo) en la próxima sesión; después U10-U12 con los dos equipos.

# ═══════════════════════════════════════════════════════════════

## M1 (notas de auditoría originales)

**Hallazgos de auditoría previa:**
- Versión triplicada (HG-BUG-0017): `pyproject.toml` (1.0.1), `hypergery_ubuntu/__init__.py` (`__version__`), `ui_qt/styles.py` (`APP_DISPLAY_VERSION`). Además `app_tk.py` tiene una cuarta ("0.6.0", muerto).
- Ya existe `scripts/install-desktop-launcher.sh` (launcher de usuario, no .deb).
- About dialog ya existe (`main_window.py:show_about`), usa APP_DISPLAY_VERSION.
- Sin icono de app (iconos por código en `ui_qt/icons.py`, sin assets).
- Entry points: `hypergery` (app.py→ui_qt.main), `hypergery-cli` (cli.py), `hypergery-agent` (agent.py). Ninguno acepta `--version`.

**Plan M1:**
1. Versión única: `__init__.py` canónica; pyproject `dynamic=["version"]`; styles importa.
2. `--version` en app/cli/agent (app: antes de importar Qt).
3. Icono de app por código (window icon) + SVG para .desktop/.deb.
4. `packaging/`: `hypergery.desktop`, `hypergery.svg`, `scripts/build-deb.sh` (dpkg-deb, paquete `all`, wrappers /usr/bin, sin tocar datos de usuario al desinstalar).
5. Tests: identidad de versión única, --version x3, .desktop válido, build .deb real si dpkg-deb disponible.
6. U1: build+inspección automatizada; instalación real requiere sudo → probar `sudo -n`, si no, cola UAT.

## Cola de UAT humano (para Gerard)

- (pendiente de rellenar; U10–U14 caerán aquí en sus milestones)

## Bloqueos

- (ninguno)

## Próximo paso

- Implementar plan M1 (arriba).
