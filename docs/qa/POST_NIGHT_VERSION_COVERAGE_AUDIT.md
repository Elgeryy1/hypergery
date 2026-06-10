# Auditoría de cobertura de versiones — noche autónoma v1.1 → v2.0

- **Fecha:** 2026-06-10
- **Rama auditada:** `audit/post-night-bugs` (punta de la noche; contiene toda la cadena v1.1→v2.0 + arreglos de auditoría)
- **Rama hermana:** `fix/v1.1-packaging-uat` (fix U1 + resultado UAT; diverge de `feat/v1.1-real-libvirt-hygiene`)
- **Método:** solo inventario git + lectura de código/tests/docs. Sin código nuevo, sin merges, sin tags, sin VMs.

## 1. Resumen ejecutivo

Las **15 ramas esperadas existen** y cada milestone v1.1→v2.0 tiene commit, código y
tests reales (no solo documentación). Estado honesto:

- **v1.1 — PASS completo**, incluido U1 real con sudo (instalar/desinstalar .deb,
  datos y VMs conservados). Es la candidata a RC. Ojo: el fix de packaging vive en
  `fix/v1.1-packaging-uat`, **fuera** de la cadena v1.2+.
- **v1.2, v1.3, v1.4 — PASS por código + tests automáticos** (sin UAT físico pendiente declarado).
- **v1.5 (live migration), v1.6 (Android), v1.7 (GPU) — PARCIAL / UAT PENDIENTE**:
  código y tests simulados/estáticos completos, pero **congelados** hasta U10–U12,
  U13 (+CI/APK) y U14 respectivamente. **No release-ready.**
- **v2.0 — solo investigación** (`docs/research/V2_0_RESEARCH.md`). No es feature productiva.
- **Riesgo clave detectado:** los arreglos de la auditoría nocturna
  (HG-BUG-0025 ALTO en GPU, 0026/0027/0028/0029…) viven **solo** en
  `audit/post-night-bugs`. Mergear las ramas `feat/v1.x` directamente traería el
  código **sin esos fixes**.

Gates hoy en `audit/post-night-bugs`: `compileall` OK; pytest offscreen
**858 passed, 8 skipped** (23.9s). Suite `needsRealLibvirt` no re-ejecutada hoy
(toca VMs reales hgtest-*): último resultado conocido **8/8 PASS en el host real,
host limpio** (ver `docs/audit/POST_NIGHT_AUDIT.md`).

## 2. Estado por versión

| Versión | Rama | Commit | Estado | Tests | UAT | ¿Mergeable ahora? |
|---|---|---|---|---|---|---|
| v1.1 identidad/.deb | `feat/v1.1-app-identity` | `a8a0c58` | **PASS** | test_app_identity (10) | **U1 PASS** (2026-06-10) | Sí (con el fix de abajo) |
| v1.1 JobManager | `feat/v1.1-jobmanager` | `c7c5407` | **PASS** | test_qt_jobs (13) | n/a | Sí |
| v1.1 Hub robusto | `feat/v1.1-hub-robustness` | `4d4c225` | **PASS** | test_registry_robustness (15) | n/a | Sí |
| v1.1 redes | `feat/v1.1-networks` | `5c6e2e1` | **PASS** | test_networks_coherence (16) | n/a | Sí |
| v1.1 realLibvirt+higiene | `feat/v1.1-real-libvirt-hygiene` | `fd1e43b` | **PASS** | test_real_libvirt (8, gated) | 8/8 real (noche) | Sí |
| v1.1 packaging UAT fix | `fix/v1.1-packaging-uat` | `bb16864`+`431dc41` | **PASS** | test_packaging_uat (+5, en esa rama) | **U1 PASS documentado** | Sí — **imprescindible** para v1.1 |
| v1.2 seguridad Hub/API | `feat/v1.2-hub-security` | `b62e266` | **PASS** | test_security_v12 (21) | no requerido | Sí, tras v1.1 |
| v1.3 backups/templates | `feat/v1.3-backups-templates` | `a70141d` | **PASS** | test_v13_backups (20) | verifier en suite real | Sí, tras v1.2 |
| v1.4 orquestación/telemetría | `feat/v1.4-orchestration-telemetry` | `50ea269` | **PASS** | test_v14_orchestration (15) | smoke opcional | Sí, tras v1.3 |
| v1.5 prep engine | `feat/v1.5-prep-migration-engine` | `e9426a5` | **PASS** (infra) | test_v15_engine (17) | n/a | Con v1.5 live |
| v1.5 live migration | `feat/v1.5-live-migration` | `4fc8fbd` | **PARCIAL — UAT PENDIENTE** | test_v15_live_migration (21, simulados) | **U10–U12 pendientes** | **NO** |
| v1.6 Android | `feat/v1.6-android-app` | `c447b03` | **PARCIAL — UAT PENDIENTE** | test_android_static (5) + ParsersTest.kt (sin ejecutar, sin SDK) | **U13 + CI/APK pendientes** | **NO** |
| v1.7 GPU passthrough | `feat/v1.7-gpu-passthrough` | `a32fd03` | **PARCIAL — UAT PENDIENTE** | test_v17_gpu_passthrough (17) | **U14 pendiente** (2ª GPU) | **NO** |
| v2.0 research | `feat/v2.0-research` | `7827ff1` | **EXPERIMENTAL — solo docs** | n/a | n/a | Solo como documentación |
| Auditoría nocturna | `audit/post-night-bugs` | `2380052` | **PASS** (9/10 hallazgos cerrados) | test_post_night_audit{,_round2} (10+10) | n/a | Contiene los fixes; ver §9 |

## 3. Ramas esperadas vs encontradas

| Rama esperada | ¿Existe? | ¿En origin? |
|---|---|---|
| feat/v1.1-app-identity | ✅ | ✅ |
| feat/v1.1-jobmanager | ✅ | ✅ |
| feat/v1.1-hub-robustness | ✅ | ✅ |
| feat/v1.1-networks | ✅ | ✅ |
| feat/v1.1-real-libvirt-hygiene | ✅ | ✅ |
| fix/v1.1-packaging-uat | ✅ | ✅ |
| feat/v1.2-hub-security | ✅ | ✅ |
| feat/v1.3-backups-templates | ✅ | ✅ |
| feat/v1.4-orchestration-telemetry | ✅ | ✅ |
| feat/v1.5-prep-migration-engine | ✅ | ✅ |
| feat/v1.5-live-migration | ✅ | ✅ |
| feat/v1.6-android-app | ✅ | ✅ |
| feat/v1.7-gpu-passthrough | ✅ | ✅ |
| feat/v2.0-research | ✅ | ✅ |
| audit/post-night-bugs | ✅ | ✅ |

**Ninguna falta.** Topología: cadena lineal `main(v1.0.1) → app-identity → jobmanager
→ hub-robustness → networks → real-libvirt-hygiene`; de ahí divergen
`fix/v1.1-packaging-uat` y la cadena `v1.2 → v1.3 → v1.4 → v1.5-prep → v1.5-live
→ v1.6 → v1.7 → v2.0 → audit/post-night-bugs`. `main...audit/post-night-bugs`:
89 archivos, +8117/−1307.

## 4. Verificación de lo prometido, por versión (archivos clave)

### v1.1 — todo verificado en código
- Identidad: `packaging/hypergery.desktop`, `packaging/hypergery.svg`, `ui_qt/icons.py`; About en `main_window.py` (`show_about`, menú «Acerca de HyperGery»).
- `--version` x3: `app.py` (sin Qt), `cli.py`, `agent.py` (commit `a10aa5d`); entry points en `pyproject.toml`.
- .deb: `scripts/build-deb.sh` (raíz) → 3 wrappers /usr/bin + .desktop + svg + copyright. Fix de cwd y wrapper en `fix/v1.1-packaging-uat`.
- JobManager/closeEvent/throttle: `ui_qt/jobs.py`, `main_window.py`, `workers.py`.
- Hub WAL/busy_timeout/TTL/límite upload: `registry/server.py`, `registry/store.py`.
- Redes coherentes: `backend.py`, `v1/networks.py`, `v1/api.py`, `v1/cli_v1.py`.
- `needsRealLibvirt`: marker en `pyproject.toml` + `tests/conftest.py` + `tests/test_real_libvirt.py`.
- `app_tk.py` **retirado** (no existe en el árbol).
- U1 PASS documentado: `docs/qa/V1_1_PACKAGING_UAT_FIX.md` + `docs/qa/V1_1_UAT_RESULT.md` (rama fix).

### v1.2 — todo verificado en código
- Token obligatorio por defecto (`v1/api.py:204`, `auth_token=""` solo explícito con warning), `Authorization: Bearer` (`registry/client.py:46`, `registry/auth.py`).
- Config/token 0600 (`config.py:110`, `registry/auth.py:40-41`).
- RBAC enforced en `v1/api.py` (`require_permission` de `v1/rbac.py`, 401/403, `PermissionDeniedError`→403).
- Audit log + rate limit en `registry/server.py` (`AuthRateLimiter`, fallos auditados en tabla de eventos y limitados por IP).
- `hub pairing-info` en `cli.py` (token marcado como SECRET).
- Docs TLS/VPN: `docs/HUB_SECURITY.md` (reverse proxy TLS, WireGuard/Tailscale/SSH).
- Tests 401/403/escalada: `test_security_v12.py` (21 tests, 13 menciones 401/403).

### v1.3 — todo verificado en código
- `v1/backups.py` (BackupPolicy/Store, is_due, prune), `v1/backup_verifier.py` (`verify_backup` con VM temporal + cleanup).
- Snapshot branching y tags/budget: `backend.py`, `labs.py`, `cli.py`, `v1/cli_v1.py`.
- Tests: `test_v13_backups.py` (20). Verifier incluido en la suite real (8/8 de la noche).

### v1.4 — todo verificado en código
- Telemetría/heartbeat: `agent.py` + `v1/telemetry.py` (TelemetryService, evaluate_alerts); `dashboard()` en `v1/api.py:142`.
- Orchestrator `apply_plan(..., confirm=True)` obligatorio (`v1/orchestrator.py:238-251` — nunca aplica sin confirm).
- API companion con acciones SEGURAS start/shutdown(ACPI)/snapshot (`v1/api.py:114-136`); RBAC/lab scoping vía `v1/auth.py`+`rbac.py`.
- Tests: `test_v14_orchestration.py` (15).

### v1.5 — código completo, UAT físico pendiente
- TD-9 canal de progreso: `v1/progress.py`; TD-4 máquina de estados: `v1/migration_engine.py`.
- `v1/live_migration.py`: `virsh migrate` (--abort-on-error, rollback `domjobabort`), preflight (bloquea VMs con `<hostdev>` GPU), cancel, downtime real (`domjobinfo --completed`) + estimación.
- Anti double-active: journal persistente `v1/migration_journal.py` (HG-BUG-0028, arreglado en rama audit).
- CLI `migrate-live` exige `--confirm`.
- Tests simulados: `test_v15_engine.py` (17) + `test_v15_live_migration.py` (21). **Ninguna migración live real ejecutada. NO release-ready hasta U10–U12 físicos.**

### v1.6 — código completo, build/UAT pendientes
- `android/` existe: Kotlin + Compose (MainActivity, AppViewModel, PairingScreen, DashboardScreen, VmListScreen, ApiClient, SettingsStore).
- Pairing, dashboard, inventario, acciones seguras y progreso long-poll (`ApiClient.waitProgress`, timeout 25s) contra el API v1 seguro.
- CI: `android/ci/android.yml` — **pendiente de mover a `.github/workflows/`** (el token de la noche no tenía scope workflow). **APK no compilado** (sin Android SDK en el host).
- Tests: `test_android_static.py` (5) + `ParsersTest.kt` (lo ejecutará el CI). **U13 pendiente.**

### v1.7 — código completo, UAT físico pendiente
- `v1/gpu_passthrough.py`: detección PCI/IOMMU (sysfs, solo lectura), `iommu_status`, preflight (IOMMU activo, grupo limpio, vfio-pci), bind/unbind por `driver_override` con rollback, `<hostdev>` XML, **bloqueo de GPU de escritorio** (boot_vga; hard stop reforzado en HG-BUG-0025, rama audit).
- Incompatibilidad con live migration: el preflight v1.5 bloquea VMs con `<hostdev>`.
- Tests: `test_v17_gpu_passthrough.py` (17) + detección real en suite libvirt. **U14 pendiente (requiere 2ª GPU física).**

### v2.0 — solo investigación (no productivo)
`docs/research/V2_0_RESEARCH.md` cubre los 5 temas: HG-MEMDIFF (descartado con
honestidad → dirty bitmaps/checkpoints libvirt), dedup (delegar en backing files +
filesystem), packet visualizer (MVP contadores sysfs), vGPU/SR-IOV/Looking Glass
(no prometer; SR-IOV solo presencial), plugins (posponer; API v1 como vía de
integración). **No hay código v2.0. No debe presentarse como feature.**

## 5. Tests por versión

| Versión | Archivo(s) | Nº tests | Tipo |
|---|---|---|---|
| v1.1 | test_app_identity, test_qt_jobs, test_registry_robustness, test_networks_coherence, test_real_libvirt | 10+13+15+16+8 | unit/integración + 8 reales gated |
| v1.1 fix | test_packaging_uat (rama fix) | 5 | packaging U1 |
| v1.2 | test_security_v12 | 21 | auth/RBAC/401/403 |
| v1.3 | test_v13_backups | 20 | unit |
| v1.4 | test_v14_orchestration | 15 | unit |
| v1.5 | test_v15_engine + test_v15_live_migration | 17+21 | **simulados** (sin virsh real) |
| v1.6 | test_android_static (+ ParsersTest.kt) | 5 (+1 sin ejecutar) | estáticos |
| v1.7 | test_v17_gpu_passthrough | 17 | unit (sysfs fake) |
| audit | test_post_night_audit{,_round2} | 10+10 | regresión de hallazgos |

Suite global hoy (`audit/post-night-bugs`): **858 passed, 8 skipped** (los 8 skips
son tests gated needsRealLibvirt/real-only). En `fix/v1.1-packaging-uat`:
**727 passed, 6 skipped**.

## 6. Cola de UAT pendiente

| UAT | Versión | Qué es | Estado |
|---|---|---|---|
| ~~U1~~ | v1.1 | instalar/desinstalar .deb real | **PASS 2026-06-10** (`docs/qa/V1_1_UAT_RESULT.md`) |
| U10 | v1.5 | live migration PC→portátil shared storage, downtime <1s | **PENDIENTE** (2 equipos) |
| U11 | v1.5 | block migration sin NAS | **PENDIENTE** |
| U12 | v1.5 | cancelación a mitad (origen intacto, destino limpio) | **PENDIENTE** |
| U13 | v1.6 | móvil real por WireGuard/Tailscale contra API v1 | **PENDIENTE** (antes: mover CI y obtener APK) |
| U14 | v1.7 | passthrough real con 2ª GPU (bind/attach/unbind) | **PENDIENTE** (hardware) |
| — | v1.6 | `git mv android/ci/android.yml .github/workflows/` + primer APK del CI | **PENDIENTE** (scope del token) |
| — | v1.5 | wizard Qt de migración (decisión de UX) | **PENDIENTE** (no bloquea CLI) |
| — | deuda | HG-BUG-0030 (cola, BAJO), barrido completo HG-BUG-0021, HG-BUG-0022/0014 | **PENDIENTE** |

## 7. Qué puede considerarse v1.1 RC

`fix/v1.1-packaging-uat` (= cadena v1.1 completa `a8a0c58→fd1e43b` + fix packaging
`bb16864` + UAT `431dc41`). Cumple: app instalable .deb con U1 PASS real,
`--version` x3, About/icono, JobManager/closeEvent/throttle, Hub robusto, redes
coherentes, suite real 8/8 (noche), app_tk retirado, 727 tests verdes. **Esta es la
rama a mergear como v1.1.**

## 8. Qué NO debe mergearse aún

- `feat/v1.5-live-migration` (y por arrastre todo lo posterior) — hasta U10–U12.
- `feat/v1.6-android-app` — hasta CI activado + APK + U13.
- `feat/v1.7-gpu-passthrough` — hasta U14.
- `feat/v2.0-research` — mergeable solo como documentación, nunca anunciar como feature.
- **Ninguna rama `feat/v1.5+` debe mergearse sin traer los fixes de `audit/post-night-bugs`** (ver §9).

## 9. Riesgos si se mergea todo de golpe

1. **Las ramas feat/ NO contienen los arreglos de la auditoría.** HG-BUG-0025
   (ALTO, GPU desktop hard-stop), 0026/0027 (tokens/rate-limit API), 0028 (ALTO,
   double-active post-switchover), 0029, 0019, 0023 están arreglados solo en
   `audit/post-night-bugs`. Mergear `feat/v1.7-gpu-passthrough` "a pelo" mete un
   bug ALTO conocido. Cualquier merge de v1.2+ debe hacerse vía
   `audit/post-night-bugs` (que lo contiene todo) o tras rebasar los fixes.
2. Publicar live migration / Android / GPU sin UAT físico = anunciar features no
   verificadas en hardware real (regla de honestidad del proyecto).
3. `fix/v1.1-packaging-uat` y la cadena v1.2+ divergen en `fd1e43b`: mergear ambas
   requiere resolver el solape (build-deb.sh, test_app_identity.py) — trivial pero
   hay que hacerlo conscientemente.
4. Un merge único `v2.0-research`→main arrastra ~8k líneas sin pasos intermedios de
   validación ni releases por versión: imposible bisectar y deshacer por milestone.

## 10. Orden recomendado

1. **v1.1 primero:** merge/release de `fix/v1.1-packaging-uat` (U1 PASS ya).
2. **v1.2** (seguridad Hub/API) — con los fixes 0026/0027 de la rama audit.
3. **v1.3** (backups/templates).
4. **v1.4** (orquestación/telemetría/companion).
5. **v1.5** solo tras **U10–U12** físicos (incluye journal 0028 de la rama audit).
6. **v1.6** solo tras CI en `.github/workflows`, APK verde y **U13**.
7. **v1.7** solo tras **U14** (con el hard-stop 0025 de la rama audit).
8. **v2.0**: mergear únicamente como docs/research.

## Validación ejecutada para esta auditoría (2026-06-10)

```
git branch --all --sort=committerdate
git log --oneline --decorate --graph --all --simplify-by-decoration -80
git log --oneline --decorate main..HEAD
git diff --name-status main...HEAD   # 89 archivos
python -m compileall -q hypergery_ubuntu          # OK
QT_QPA_PLATFORM=offscreen pytest -q               # 858 passed, 8 skipped
```

`needsRealLibvirt` no re-ejecutada (tocaría el hipervisor real); se cita el último
resultado conocido: **8/8 PASS, host limpio** (noche del 2026-06-09, ver
`docs/audit/POST_NIGHT_AUDIT.md`).
