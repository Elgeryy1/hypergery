# GOAL_PROGRESS — noche autónoma (inicio: 2026-06-09)

> Memoria viva del agente. Si el contexto se compacta: leer esto y continuar.
> Plan maestro: `goalplan.md` (raíz del repo). Orden de milestones: §10.

## Estado global

- **Baseline verificado:** `main` @ 2148aec — `compileall` OK, `pytest -q` = **667 passed, 1 skipped** (30.8s), venv `~/.venvs/hypergery` (Python 3.14).
- **Milestone actual:** M6 — v1.2 seguridad Hub (token/TLS/RBAC/audit).
- **Ramas:** las ramas de milestone van encadenadas (cada una parte de la anterior) para no perder la versión 1.1.0.dev0 ni este fichero: `feat/v1.1-app-identity` → `feat/v1.1-jobmanager` → …

## Milestones (orden §10 del goalplan)

| # | Milestone | Estado |
|---|-----------|--------|
| 1 | v1.1 identidad app + .deb + --version/About | HECHO |
| 2 | v1.1 JobManager + closeEvent + throttle preview (TD-3, 0008/0015) | HECHO |
| 3 | v1.1 Hub robusto (busy_timeout/WAL, TTL, upload) (0005/0006/0010) | HECHO |
| 4 | v1.1 redes coherentes + colisión octetos (0009/0012/0016) | HECHO |
| 5 | v1.1 needsRealLibvirt + higiene (0011/0017/0018, retirar Tk) | HECHO |
| 6 | v1.2 token/TLS + RBAC enforced + audit log (0001, TD-5) | EN CURSO |
| 7 | v1.3 Template Store + Backup Verifier + snapshots + tags | pendiente |
| 8 | v1.4 orchestrator aplicable + /telemetry + health + API companion | pendiente |
| 9 | v1.5 prep migration_engine (TD-4) + canal progreso (TD-9) | pendiente |
| 10 | v1.5 live migration en caliente + preflight + wizard | pendiente |
| 11 | v1.6 app Android nativa | pendiente |
| 12 | v1.7 GPU passthrough VFIO | pendiente |
| 13 | v2.0 investigación | pendiente |

## M1 — v1.1 identidad de app (HECHO)

- Rama `feat/v1.1-app-identity` (pusheada). Commits: a10aa5d (versión única + --version), a8a0c58 (icono/About/.desktop/.deb).
- Cierra la mitad "versión duplicada" de HG-BUG-0017 (queda app_tk.py para M5). Versión bump a 1.1.0.dev0.
- `--version` en hypergery / hypergery-cli / hypergery-agent. Icono de app por código + SVG.
- `scripts/build-deb.sh` construye `dist/hypergery_1.1.0~dev0_all.deb` (verificado: dpkg-deb info/contents OK; artefacto generado en `dist/`).
- Gates: compileall OK; pytest = 677 passed, 1 skipped (10 tests nuevos en test_app_identity.py, incluye build real del .deb).
- **U1 parcial → cola UAT humano:** no hay sudo sin contraseña, instalación/desinstalación real del .deb pendiente de Gerard: `sudo apt install ./dist/hypergery_1.1.0~dev0_all.deb`, comprobar menú/icono/`hypergery --version`, `sudo apt remove hypergery`, verificar que ~/.config/hypergery y datos sobreviven.

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
