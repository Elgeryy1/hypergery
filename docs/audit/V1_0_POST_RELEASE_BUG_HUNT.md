# HyperGery v1.0.0 — Post-Release Bug Hunt (Auditoría total)

> Rama: `audit/v1.0-post-release-bug-hunt` · Fecha: 2026-06-09 · Auditor: revisión de código asistida (Claude)
> Alcance: **solo auditoría y documentación**. No se ha modificado código funcional, ni `main`, ni el tag `v1.0.0`, ni se ha ejecutado ninguna acción destructiva (no se arrancaron/apagaron/borraron VMs, no se lanzaron migraciones ni teleport reales).

---

## 1. Resumen ejecutivo

HyperGery v1.0.0 es, en líneas generales, un proyecto **sólido y maduro** para una v1: el suite de tests pasa limpio (661 passed), el código está bien estructurado por capas (backend libvirt, migración, Hub/registry, agente, UI Qt, CLI), y se nota que ha pasado por varias rondas de revisión adversarial previas (path traversal en paquetes, atomicidad de stores, doble conteo de RAM, etc. ya corregidos y con tests de regresión).

Dicho esto, **la auditoría no es blandita** y ha encontrado problemas reales que el release no documenta o documenta a la baja:

- **Ningún bug Critical confirmado** (no hay RCE, no hay corrupción de datos silenciosa en el camino feliz, no hay borrado destructivo sin opt-in).
- **4 hallazgos High**, de los cuales **2 son funcionales de migración** y deberían bloquear cualquier promesa de "migración segura" sin matices:
  - El **export de estado (teleport con RAM)** congela la VM de origen *antes* de copiar discos y **no limpia ni reanuda** si la copia falla → una VM en producción puede quedar **apagada con un paquete a medias** y sin rollback automático.
  - Los **snapshots se empaquetan pero nunca se importan** → pérdida silenciosa de snapshots en la migración.
- **El Hub/API sin autenticación** está documentado como "LAN de confianza", pero la severidad real es mayor de lo reconocido: cualquier equipo de la LAN puede **forzar el apagado de VMs**, **borrar paquetes en staging** e **inyectar comandos**, sin credencial alguna.
- **Higiene de repo**: un instalador Windows de **126 MB (`Claude-Setup-x64.exe`)** y la carpeta `.claude/` están en el árbol de trabajo y **no están en `.gitignore`** → riesgo real de commit accidental.

**Recomendación global:** no hace falta un hotfix de emergencia (no hay corrupción en producción del camino feliz), **pero sí una v1.0.1** que cierre los dos problemas de migración (HG-BUG-0002, HG-BUG-0003), endurezca la higiene del repo (HG-BUG-0004) y al menos avise/limite el Hub sin auth. La autenticación completa del Hub puede mantenerse para v1.2 como estaba planeado, pero el README debe subir el tono de la advertencia.

### Conteo de hallazgos

| Severidad | Nº |
|-----------|----|
| Critical  | 0  |
| High      | 4  |
| Medium    | 7  |
| Low       | 9  |
| Info      | 4  |
| **Total** | **24** |

---

## 2. Metodología

1. **Inventario** completo del repo (find/wc/du, `git ls-files`).
2. **Verificación segura**: `compileall` + `pytest -q` en el venv del proyecto. Sin tocar libvirt real.
3. **Lectura módulo a módulo** de los componentes de riesgo: `migration.py`, `v1/state_migration.py`, `registry/server.py`, `registry/store.py`, `agent.py`, `backend.py`, `v1/networks.py`, `config.py`, `ui_qt/workers.py`, `ui_qt/main_window.py` (ciclo de vida de jobs), `ui_qt/console.py`, `ui_qt/screenshot.py`, `cli.py`.
4. **Búsqueda automatizada** de patrones peligrosos (`subprocess`, `shell=True`, `eval/exec/pickle/yaml.load`, `tarfile/zipfile/extractall`, `rmtree/unlink/undefine/destroy`, `QThread/closeEvent`, secretos).
5. **Interpretación** de cada hallazgo: confirmación por lectura de código, reproducción conceptual y propuesta de fix + test. Lo no confirmable se marca **Needs verification**.

### Comandos ejecutados (seguros)

```bash
# Rama de auditoría
git checkout main && git pull --ff-only origin main && git checkout -b audit/v1.0-post-release-bug-hunt

# Inventario
find . -type f -not -path "./.git/*" | sort        # 421 ficheros
find . -type f -name "*.py" ...                     # 87 módulos .py
wc -l $(...python...) | sort -n | tail              # mayores: main_window.py 4653, dialogs.py 2900, test_qt_ui.py 2039
du -ah . --exclude=.git | sort -h | tail            # Claude-Setup-x64.exe 126M, design HTML/zip ~1.7M

# Verificación
source ~/.venvs/hypergery/bin/activate
python -m compileall -q hypergery_ubuntu            # COMPILE_OK
pytest -q                                           # 661 passed in ~12s

# Patrones
rg -n "shell=True|os.system|os.popen" ...           # 0 resultados (bien)
rg -n "eval\(|exec\(|pickle|yaml.load|extractall|tarfile|zipfile" ...  # 0 (bien)
rg -n "subprocess.(run|Popen|...)" ...              # solo backend/doctor/screenshot/external_nodes, con listas de args
git check-ignore Claude-Setup-x64.exe .claude/ "capturas virtualbox/"  # NOT IGNORED
```

### Entorno de auditoría

- SO: Linux 7.0.0 (entorno de edición; **no es** el host KVM de producción).
- Python: **3.14.4** (venv `~/.venvs/hypergery`). El proyecto se ejecuta también bajo 3.13 (hay `.pyc` 3.13 y 3.14 en caché).
- **No hay libvirt/virsh/qemu** disponibles para ejercitar las rutas reales en este entorno → los tests son 100% con mocks (ver §Gaps de tests).

---

## 3. Inventario del repo

### Módulos Python (87 ficheros, ~33k líneas)

- **Núcleo** (`hypergery_ubuntu/`): `backend.py` (1208), `migration.py` (989), `cli.py` (724), `app_tk.py` (763, UI Tk legacy), `labs.py` (357), `templates.py` (451), `config.py`, `doctor.py`, `agent.py` (526).
- **Hub/registry** (`registry/`): `server.py` (473, HTTP), `store.py` (577, SQLite), `client.py`.
- **v1** (`v1/`): `api.py` (355), `teleport.py` (428), `nas.py` (323), `telemetry.py` (333), `memdiff.py` (250), `state_migration.py`, `orchestrator.py`, `networks.py`, `rbac.py`, `hosts.py`, `external_nodes.py`, `providers.py`, etc.
- **UI Qt** (`ui_qt/`): `main_window.py` (**4653**, ver deuda técnica), `dialogs.py` (**2900**), `console.py` (900), `v1_render.py` (785), `humanize.py` (749), `styles.py` (614), `detail_panel.py`, `topology.py`, `workers.py`, etc.

### Tests (38 ficheros)
`test_migration.py`, `test_v1_state_migration.py`, `test_registry.py`, `test_agent.py`, `test_backend*.py`, `test_cli.py`, `test_qt_ui.py` (2039), `test_v1_*` (api, teleport, nas, hosts, orchestrator, networks_rbac_nodes, labs_providers, integration), etc.
- **Sin marcadores `needsRealLibvirt`/`skipif`** → "661 passed, 0 skipped" significa que **no existen tests de integración con libvirt real**; todo `virsh`/`qemu-img` está mockeado (ver HG-BUG-0011).

### Scripts (`scripts/`)
`install-ubuntu-deps.sh`, `bootstrap-ubuntu.sh`, `preflight.sh`, `dev-run.sh`, `acceptance-ubuntu.sh`, `acceptance-real-host.sh`, `install-agent-user-service.sh`, `install-desktop-launcher.sh`, `start-second-host.sh`.

### Docker / Hub / NAS
`docker/Dockerfile`, `docker/docker-compose.yml`, `docker/README.md`, `docker/.env.example` (solo `HYPERGERY_HUB_PORT` y `HYPERGERY_NAS_ROOT`, **sin secretos**).

### Docs / release
~40 ficheros `.md`. En raíz conviven release notes (v0.6, v0.7, **v1.0-rc1**, v1.0.0), reports de sesión (V09/V10), handoffs y `goal.md` (gitignored). `docs/` con guías, arquitectura, roadmap, QA y evidencias PNG.

### Ficheros sospechosos / no deberían estar
- **`Claude-Setup-x64.exe` (126 MB)** — instalador Windows, en raíz, **no gitignored** (untracked hoy). HG-BUG-0004.
- **`.claude/`** — config local del agente, **no gitignored**. HG-BUG-0004.
- **`capturas virtualbox/` (620 KB)** — capturas, no gitignored.
- **`docs/design/v0.7/HyperGery.zip` (1.4 MB)** y `*.html` (1.7 MB ×2) — **versionados** (tracked), bloat del repo. HG-BUG-0018.
- Cachés `__pycache__`/`.pytest_cache` presentes en disco pero **correctamente gitignored** (no tracked). Bien.

### Secretos
`rg` de password/token/secret/api_key/bearer **no encontró secretos reales** en el código. `.gitignore` cubre `.env`, `*.key`, `*.pem`, `secrets.*`, `firebase*.json`. **Bien.** Única "fuga" es la IP de laboratorio doméstico `192.168.1.150` hardcodeada como placeholder en `config.py` (HG-BUG-0020, intencional/documentada).

---

## 4. Matriz de riesgo

| ID | Título | Sev | Categoría | Blocker | Release |
|----|--------|-----|-----------|---------|---------|
| HG-BUG-0001 | Hub/API sin auth en endpoints destructivos | High | Security | No* | v1.0.1 (mitigación) / v1.2 (auth) |
| HG-BUG-0002 | State export congela origen y no hace rollback si falla la copia | High | Migration | **Sí** | v1.0.1 |
| HG-BUG-0003 | Snapshots se empaquetan pero no se importan (pérdida silenciosa) | High | Migration | **Sí** | v1.0.1 |
| HG-BUG-0004 | `Claude-Setup-x64.exe` (126MB) y `.claude/` no gitignored | High | Packaging | No | v1.0.1 |
| HG-BUG-0005 | SQLite sin `busy_timeout` → "database is locked" (500) en concurrencia | Medium | Hub/Concurrency | No | v1.1 |
| HG-BUG-0006 | `commands`/`events` sin TTL; replay de comando obsoleto al reconectar agente | Medium | Hub | No | v1.1 |
| HG-BUG-0007 | Paquetes de estado sin checksums; validación solo comprueba existencia | Medium | Migration | No | v1.0.1 |
| HG-BUG-0008 | MainWindow sin `closeEvent`: QThreads vivos al cerrar → crash/abort | Medium | UI | No | v1.1 |
| HG-BUG-0009 | Centro de control → Redes: errores falsos CIDR/Gateway/DHCP | Medium | UI/Backend | No | v1.1 |
| HG-BUG-0010 | Hub PUT sin límite de tamaño → llenar NAS staging (DoS) | Medium | Hub/Security | No | v1.1 |
| HG-BUG-0011 | Sin tests de libvirt real ("0 skipped" enmascara cobertura mock-only) | Medium | Tests | No | v1.1 |
| HG-BUG-0012 | Colisión de octeto en `network_ip_address` (~180 octetos) | Low | Backend | No | v1.1 (Needs verification) |
| HG-BUG-0013 | Import sin preflight de espacio libre en destino | Low | Migration | No | v1.1 |
| HG-BUG-0014 | `_stop_connect_worker` congela UI hasta 10s al cerrar consola | Low | UI | No | v1.1 (ya conocido) |
| HG-BUG-0015 | Preview lanza varios jobs de captura sin throttle/cache | Low | UI/Perf | No | v1.1 (ya conocido) |
| HG-BUG-0016 | TOCTOU en `ensure_network` entre `net-info` y `net-start` | Low | Backend | No | v1.1 |
| HG-BUG-0017 | Versión duplicada en `pyproject.toml` y `__init__.py` | Low | Packaging | No | v1.1 |
| HG-BUG-0018 | Bloat de repo: HTML/zip de diseño + docs handoff en raíz | Low | Packaging | No | v1.1 |
| HG-BUG-0019 | Screenshot deja temp en `/tmp` si el proceso muere | Low | Security | No | backlog |
| HG-BUG-0020 | IP de laboratorio doméstico hardcodeada como placeholder | Info | Security | No | backlog |
| HG-BUG-0021 | El agente traga excepciones (`except: pass`) en heartbeat/report | Low | Hub | No | v1.1 |
| HG-BUG-0022 | Control Center muestra JSON crudo / textos en inglés | Low | UX | No | v1.1 (ya conocido) |
| HG-BUG-0023 | Errores de libvirt no humanizados en rutas CLI/agente | Info | Backend/UX | No | v1.1 |
| HG-BUG-0024 | `RELEASE_NOTES_v1.0-rc1.md` retenido tras v1.0.0 | Info | Docs | No | v1.0.1 |

\* HG-BUG-0001 no es blocker **bajo el supuesto de LAN de confianza**; pasa a blocker si HyperGery se usa fuera de ese supuesto.

El detalle completo de cada hallazgo (descripción, impacto, reproducción, fix y test) está en **`V1_0_BUG_REGISTER.md`**. Aquí se resumen los grupos.

---

## 5. Hallazgos por área

### 5.1 Bugs High

- **HG-BUG-0002 (Migration, blocker):** `v1/state_migration.export_vm_state_package` llama `backend.save_vm()` (que **apaga** la VM dejando su estado en `memory-state.save`) y *después* copia los discos en un bucle. Si una `shutil.copy2` de disco falla (NAS lleno, EIO, permiso), **no hay `try/except` que limpie el paquete parcial ni que reanude la VM**. La VM, que estaba `running`, queda `shut off`, con un paquete a medias. Contrasta con `migration.export_vm_package`, que sí envuelve todo en `try/except BaseException → rmtree`. **El origen sí se toca y queda peor que antes.**
- **HG-BUG-0003 (Migration, blocker):** `export_vm_package` recolecta, empaqueta, calcula sha256 y copia los **snapshots** (subdir `snapshots/`), pero `import_vm_package` solo itera `./devices/disk` del `domain.xml` y **nunca restaura snapshots** ni sus ficheros. Resultado: se transfiere y se verifica algo que se descarta en destino → **pérdida silenciosa de snapshots** y trabajo/espacio desperdiciado. El preflight avisa "valida antes de borrar el origen", pero no dice que los snapshots no viajan.
- **HG-BUG-0001 (Security):** `registry/server.py` no tiene **ninguna** autenticación. `do_POST` acepta `commands` (incluido `vm_force_off`), `do_PUT` sube ficheros a staging, `do_DELETE` borra paquetes enteros, `packages/cleanup` borra en lote. Cualquiera en la LAN con la IP:puerto del Hub puede apagar VMs por la fuerza y borrar paquetes. Documentado como "LAN de confianza" y diferido a v1.2, pero la **severidad real es mayor** que la nota actual del README.
- **HG-BUG-0004 (Packaging):** `Claude-Setup-x64.exe` (126 MB) y `.claude/` no están en `.gitignore` (`git check-ignore` → NOT IGNORED). Hoy están untracked, pero un `git add .` los versionaría. `*.exe` debería estar en `.gitignore`.

### 5.2 Bugs Medium

- **HG-BUG-0005 (Concurrency):** `RegistryStore.connect()` abre SQLite con `isolation_level=None` y **sin `PRAGMA busy_timeout`**, servido por `ThreadingHTTPServer`. Con varios agentes haciendo heartbeat + la UI haciendo polling, las escrituras concurrentes pueden lanzar `sqlite3.OperationalError: database is locked`, que sale como **HTTP 500** intermitente.
- **HG-BUG-0006 (Hub):** Las tablas `commands` y `events` crecen sin límite y **no hay expiración**. Un comando `pending` encolado para un agente offline (p. ej. `vm_force_off`) se ejecutará **cuando el agente reconecte horas después** → acción peligrosa con retraso. No hay TTL ni descarte de comandos viejos.
- **HG-BUG-0007 (Migration):** `validate_state_package` solo comprueba **existencia** de `memory-state.save`, `domain.xml` y discos; no hay sha256 ni tamaño (a diferencia de `validate_vm_package`). Un `memory-state.save` truncado por un NAS inestable pasa la validación y luego falla (o restaura estado corrupto) en `restore_vm`.
- **HG-BUG-0008 (UI):** `MainWindow` **no define `closeEvent`**. Los `BackendJob(QThread)` en `self.jobs`/`self._preview_jobs` no se esperan al cerrar. Cerrar la ventana durante una operación (export/import/migración) produce "QThread: Destroyed while thread is still running" → posible abort y operación de backend interrumpida.
- **HG-BUG-0009 (UI/Backend):** El tab Redes del Centro de control (`v1/api.py:256` → `network_from_lab`) deriva la red lógica del campo `lab["subnet"]`, que está **vacío** para la mayoría de labs (→ error "missing CIDR") o, si se rellena duplicado, dispara conflictos. Mientras tanto las redes **reales** de libvirt usan octetos derivados por hash (`backend.network_ip_address`). El modelo de validación está **divorciado** de las redes reales → errores falsos. Root-cause del known issue documentado.
- **HG-BUG-0010 (Hub/Security):** `_receive_package_file` (PUT) escribe el cuerpo entero a disco sin límite de tamaño ni control de espacio. Un cliente LAN puede **llenar el disco de staging del NAS** (DoS). La protección de traversal está bien; el límite de recursos no.
- **HG-BUG-0011 (Tests):** No hay tests gated por libvirt real. "0 skipped" da una falsa sensación de cobertura: las rutas que ejecutan `virsh`/`qemu-img` de verdad (define/restore/save/net-define) solo se prueban con mocks.

### 5.3 Bugs Low / Info
Ver registro. Destacan: colisión potencial de octetos de red a escala (HG-BUG-0012, *Needs verification*), falta de preflight de espacio en import (HG-BUG-0013), los dos issues de UI ya conocidos (0014, 0015), TOCTOU de red (0016), versión duplicada (0017), bloat de repo (0018) y el agente que traga excepciones (0021).

### 5.4 Deuda técnica
Ver **`V1_0_TECH_DEBT_MAP.md`**. Resumen: `main_window.py` (4653) y `dialogs.py` (2900) son monolitos; el ciclo de vida de jobs Qt no está centralizado; el Hub carece de capa de auth/limpieza; `app_tk.py` (763) es UI legacy que sigue en el árbol; el modelo de red lógico vs. real está duplicado.

### 5.5 Gaps de tests
Ver **`V1_0_TEST_GAP_ANALYSIS.md`**. Faltan: tests de libvirt real (marcador `needsRealLibvirt`), test de cleanup/rollback en fallo de state export (cazaría 0002), test de que los snapshots sobreviven al import (cazaría 0003), tests de concurrencia SQLite (0005), test de `closeEvent` con job vivo (0008).

### 5.6 Seguridad
Ver **`V1_0_SECURITY_REVIEW.md`**. Lo bueno: 0 `shell=True`, 0 `eval/exec/pickle/yaml.load`, subprocess siempre con listas de args, path traversal cerrado en paquetes (`safe_package_member`) y en NAS (`_safe_segment`), validación estricta de nombres VM/lab/host. Lo pendiente: auth del Hub, límites de recursos, y endurecimiento de permisos de ficheros temporales/config.

### 5.7 UX
Confirmaciones presentes en acciones destructivas de UI; CLI con `--confirm`/`--dry-run`. Pendientes (ya conocidos): JSON crudo en Control Center, algún texto en inglés, freeze de 10s al cerrar consola, preview redundante.

### 5.8 Docs
`RELEASE_NOTES_v1.0-rc1.md` sigue en raíz tras v1.0.0 (HG-BUG-0024). Conviven muchos reports de sesión/handoff en raíz que deberían moverse a `docs/archive/`.

### 5.9 Packaging
`.exe` y `.claude/` sin gitignore (0004), HTML/zip de diseño versionados (0018), versión en dos sitios (0017). Instalación pip editable correcta vía `pyproject.toml`.

---

## 6. Recomendaciones y planes

### Plan v1.0.1 (cierre obligatorio antes de prometer "migración segura")
1. **HG-BUG-0002** — Envolver `export_vm_state_package` en `try/except`: limpiar el paquete parcial y **reanudar la VM de origen** (`virsh start`/`resume`) si falla tras `save_vm`. Criterio de aceptación: un fallo simulado de copia deja la VM de origen **en su estado previo** y sin paquete a medias; test de regresión que lo verifique.
2. **HG-BUG-0003** — O bien **importar los snapshots**, o bien **dejar de empaquetarlos** y avisar explícitamente que la migración v1 no transfiere snapshots. Criterio: el comportamiento documentado coincide con el real; test que verifica snapshots tras import (o su ausencia avisada).
3. **HG-BUG-0004** — Añadir `*.exe`, `.claude/`, `capturas virtualbox/` a `.gitignore`. Criterio: `git check-ignore` los reconoce; `git status` limpio.
4. **HG-BUG-0007** — Checksums sha256 en el paquete de estado + verificación en `validate_state_package`. Criterio: un fichero truncado falla la validación con mensaje claro.
5. **HG-BUG-0001 (mitigación)** — Subir el tono de la advertencia del README + bind a `127.0.0.1` por defecto (ya existe `--allow-remote`) y mensaje al arrancar el Hub recordando que no hay auth. Criterio: arrancar sin `--allow-remote` no escucha en `0.0.0.0`.
6. **HG-BUG-0024** — Mover/eliminar `RELEASE_NOTES_v1.0-rc1.md` y reports de sesión a `docs/archive/`.

### Plan v1.1
- HG-BUG-0005 (`busy_timeout` + retry), HG-BUG-0006 (TTL/limpieza de comandos y events), HG-BUG-0008 (`closeEvent` con `wait` acotado), HG-BUG-0009 (sincronizar modelo de red lógico con el real o derivarlo de libvirt), HG-BUG-0010 (límite de tamaño en upload), HG-BUG-0011 (suite `needsRealLibvirt`), HG-BUG-0013/0016/0021, refactor inicial de `main_window.py`, HG-BUG-0014/0015/0022 (UX), HG-BUG-0017/0018 (higiene).

### Plan v1.5 (live migration) — bloqueos arquitectónicos detectados
- **No hay abstracción de "Job de migración"** con fases (preflight/package/transfer/import/activate/rollback) como máquina de estados reutilizable: hoy `start_remote_migration` es un procedimiento lineal. Para live migration hace falta aislar fases con progreso y rollback por fase.
- **El progreso es por callback ad-hoc** (`progress_callback(label, i, n)`); no hay un canal de progreso uniforme Hub↔agente↔UI. Live migration necesita progreso continuo (dirty pages, etc.).
- **El Hub no tiene streaming/eventos push**; todo es polling (`poll_remote_migration_status`). Live migration querrá eventos en tiempo real.
- **La UI puede bloquear**: sin `closeEvent` ni cancelación de jobs (HG-BUG-0008), una live migration larga sería frágil. Hace falta cancelación cooperativa.
- **`virsh migrate` real no existe aún**; el modelo actual es offline-copy + restore-from-state. La capa `backend.virsh` está lista para añadirlo, pero la orquestación (origen↔destino simultáneos, conexión qemu+tls) no está abstraída.

### Backlog
HG-BUG-0019, HG-BUG-0020, HG-BUG-0023, retirada de `app_tk.py` legacy si ya no se usa.

---

## 7. Qué probar con hardware real (PC + portátil + NAS)

1. **Teleport de VM apagada** PC→portátil vía NAS (camino feliz ya validado): repetir y confirmar UUID/MAC regenerados y red reasignada.
2. **State migration de VM encendida** y **forzar un fallo de copia a mitad** (p. ej. desmontar el NAS durante el copiado) → verificar HG-BUG-0002 (¿queda la VM de origen apagada?).
3. **Migrar una VM con snapshots** → verificar HG-BUG-0003 (¿llegan los snapshots al destino?).
4. **Dos agentes + UI haciendo polling** contra el Hub a la vez → buscar HTTP 500 "database is locked" (HG-BUG-0005).
5. **Encolar `vm_force_off` con el agente offline**, esperar y reconectar → ver si se ejecuta tarde (HG-BUG-0006).
6. **Cerrar la ventana durante un export/import** → ver el aviso "QThread destroyed" / abort (HG-BUG-0008).
7. **Centro de control → Redes** con 2+ labs → confirmar los errores falsos de CIDR/gateway/DHCP (HG-BUG-0009).
8. Subir un fichero gigante por PUT al Hub → ver si llena el disco (HG-BUG-0010).

---

## 8. Criterios de aceptación (resumen)

Cada bug del registro incluye su test recomendado. Para cerrar un issue: (a) test de regresión que falle antes y pase después, (b) comportamiento documentado = comportamiento real, (c) sin nuevos warnings en `pytest -q`, (d) para los de migración, validación en hardware real según §7.
