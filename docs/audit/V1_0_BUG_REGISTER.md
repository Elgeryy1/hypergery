# HyperGery v1.0.0 — Bug Register

Registro detallado de los 24 hallazgos. IDs estables `HG-BUG-NNNN`. Estado inicial: **Open**.
Líneas aproximadas referidas al estado del repo en la rama `audit/v1.0-post-release-bug-hunt` (= `v1.0.0`).

Índice rápido: [Tabla resumen](#tabla-resumen) · [Detalle](#detalle)

## Tabla resumen

| ID | Sev | Categoría | Archivo principal | Blocker | Release |
|----|-----|-----------|-------------------|---------|---------|
| HG-BUG-0001 | High | Security | `registry/server.py` | No* | v1.2 (auth) / v1.0.1 (mitig.) |
| HG-BUG-0002 | High | Migration | `v1/state_migration.py` | Sí | v1.0.1 |
| HG-BUG-0003 | High | Migration | `migration.py` | Sí | v1.0.1 |
| HG-BUG-0004 | High | Packaging | `.gitignore` | No | v1.0.1 |
| HG-BUG-0005 | Medium | Concurrency | `registry/store.py` | No | v1.1 |
| HG-BUG-0006 | Medium | Hub | `registry/store.py` | No | v1.1 |
| HG-BUG-0007 | Medium | Migration | `v1/state_migration.py` | No | v1.0.1 |
| HG-BUG-0008 | Medium | UI | `ui_qt/main_window.py` | No | v1.1 |
| HG-BUG-0009 | Medium | UI/Backend | `v1/networks.py` | No | v1.1 |
| HG-BUG-0010 | Medium | Hub/Security | `registry/server.py` | No | v1.1 |
| HG-BUG-0011 | Medium | Tests | `tests/` | No | v1.1 |
| HG-BUG-0012 | Low | Backend | `backend.py` | No | v1.1 |
| HG-BUG-0013 | Low | Migration | `migration.py` | No | v1.1 |
| HG-BUG-0014 | Low | UI | `ui_qt/console.py` | No | v1.1 |
| HG-BUG-0015 | Low | UI/Perf | `ui_qt/main_window.py` | No | v1.1 |
| HG-BUG-0016 | Low | Backend | `backend.py` | No | v1.1 |
| HG-BUG-0017 | Low | Packaging | `pyproject.toml` | No | v1.1 |
| HG-BUG-0018 | Low | Packaging | `docs/design/` | No | v1.1 |
| HG-BUG-0019 | Low | Security | `ui_qt/screenshot.py` | No | backlog |
| HG-BUG-0020 | Info | Security | `config.py` | No | backlog |
| HG-BUG-0021 | Low | Hub | `agent.py` | No | v1.1 |
| HG-BUG-0022 | Low | UX | `ui_qt/v1_render.py` | No | v1.1 |
| HG-BUG-0023 | Info | Backend/UX | `cli.py` / `agent.py` | No | v1.1 |
| HG-BUG-0024 | Info | Docs | `RELEASE_NOTES_v1.0-rc1.md` | No | v1.0.1 |

\* No blocker bajo "LAN de confianza"; blocker fuera de ese supuesto.

---

## Detalle

### HG-BUG-0001 — Hub/API HTTP sin autenticación en endpoints destructivos

- **Severidad:** High
- **Categoría:** Security / Hub
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/registry/server.py`
- **Líneas aproximadas:** 302-457 (do_PUT/do_DELETE/do_POST), 412-453 (commands, packages/cleanup)
- **Estado:** Open · **Blocker:** No (bajo LAN de confianza) · **Release objetivo:** v1.0.1 (mitigación) / v1.2 (auth completa)
- **Descripción:** Ningún endpoint exige credencial. `POST /commands` crea comandos (incluido `vm_force_off`), `PUT /packages/{id}/{path}` sube ficheros, `DELETE /packages/{id}` borra paquetes, `POST /packages/cleanup` borra en lote.
- **Impacto:** Cualquier equipo de la LAN que alcance el puerto del Hub puede forzar el apagado de VMs, borrar paquetes en staging e inyectar comandos. Documentado como "LAN de confianza", pero la nota del README minimiza la severidad real.
- **Cómo reproducir:** Arrancar el Hub; desde otra máquina de la LAN: `curl -XPOST $HUB/commands -d '{"command_type":"vm_force_off","target_host_id":"<host>","payload":{"vm_name":"<vm>"}}'`. El comando se encola y el agente lo ejecuta.
- **Resultado esperado:** Endpoints mutantes/destructivos requieren token (o al menos bind loopback por defecto y advertencia fuerte).
- **Resultado actual:** Acceso anónimo total.
- **Propuesta de fix:** v1.0.1: confirmar bind `127.0.0.1` por defecto (ya hay `--allow-remote`), banner de arranque advirtiendo "sin auth", README con aviso destacado. v1.2: token compartido (cabecera `Authorization`) + TLS opcional (ya planificado en `NEXT_STEPS_V12_SECURITY.md`).
- **Tests recomendados:** Test de que arrancar sin `--allow-remote` no escucha en `0.0.0.0`; (v1.2) test de 401 sin token en endpoints mutantes.
- **Notas:** Coherente con known issue #5. La auditoría solo eleva la visibilidad de la severidad.

### HG-BUG-0002 — State export congela la VM de origen y no hace rollback si falla la copia

- **Severidad:** High
- **Categoría:** Migration
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/v1/state_migration.py`
- **Líneas aproximadas:** 27-98 (`export_vm_state_package`), en especial 62 (`save_vm`) y 64-77 (bucle de copia de discos)
- **Estado:** Open · **Blocker:** Sí · **Release objetivo:** v1.0.1
- **Descripción:** El flujo es: validar → crear dir paquete → `backend.save_vm()` (que **apaga** la VM dejando su RAM en `memory-state.save`) → copiar discos en bucle → escribir manifest. **No hay `try/except`** alrededor de la copia de discos. Si una `shutil.copy2` falla (NAS lleno, EIO, permisos), la excepción sube **sin limpiar el paquete parcial y sin reanudar la VM**.
- **Impacto:** Una VM que estaba `running` queda `shut off` con un paquete a medias. El origen **sí se toca** y queda peor que antes; el usuario debe restaurar manualmente desde `memory-state.save`. Rompe la promesa de "no tocar el origen si falla".
- **Cómo reproducir:** State export de una VM encendida con 2+ discos; desmontar/llenar el NAS destino durante la copia del segundo disco. La VM de origen queda apagada y el dir `state-<vm>` queda parcial.
- **Resultado esperado:** Ante fallo, borrar el paquete parcial y **reanudar/arrancar** la VM de origen a su estado previo (o restaurar desde el propio `memory-state.save` recién creado).
- **Resultado actual:** VM de origen apagada + paquete parcial + sin rollback.
- **Propuesta de fix:** Envolver el cuerpo posterior a `save_vm` en `try/except BaseException`: en fallo, `rmtree(package, ignore_errors=True)` y `backend.restore_vm(memory_state)` o `backend.start_vm(vm_name)`; re-lanzar el error original. Modelar igual que `migration.export_vm_package`.
- **Tests recomendados:** Test con `backend` mock donde la copia del disco lanza `OSError`; aserción de que el dir del paquete no existe y de que se invocó la reanudación del origen.
- **Notas:** Es el hallazgo funcional más serio. Contrasta con el cuidado de `migration.export_vm_package` (líneas 429-483), que sí limpia.

### HG-BUG-0003 — Los snapshots se empaquetan pero nunca se importan (pérdida silenciosa)

- **Severidad:** High
- **Categoría:** Migration
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/migration.py`
- **Líneas aproximadas:** 157-191 (`_snapshot_assets`), 446-460 (copia de assets incl. snapshots), 640-661 (import: solo `./devices/disk`)
- **Estado:** Open · **Blocker:** Sí · **Release objetivo:** v1.0.1
- **Descripción:** `collect_vm_assets`/`export_vm_package` recolectan, copian y calculan sha256 de los snapshots (subdir `snapshots/`). Pero `import_vm_package` solo recorre `root.findall("./devices/disk")` y **no procesa los assets de tipo `snapshot` ni redefine snapshots** en el destino.
- **Impacto:** El usuario cree que migró la VM "completa" (los snapshots viajan en el paquete y se verifican), pero en destino los snapshots no existen → pérdida silenciosa de puntos de restauración. Además, tiempo/espacio desperdiciado copiando algo que se descarta.
- **Cómo reproducir:** Crear snapshot en una VM, exportar paquete (incluye `snapshots/`), importar en otro host: la VM importada no tiene snapshots.
- **Resultado esperado:** O bien restaurar los snapshots en import (`virsh snapshot-create` con los XML guardados + sus discos), o bien **no empaquetarlos** y avisar claramente que v1 no migra snapshots.
- **Resultado actual:** Empaquetados y descartados sin aviso.
- **Propuesta de fix:** Decisión de producto. Mínimo viable v1.0.1: no incluir snapshots por defecto + warning explícito en preflight/manifest ("snapshots no se transfieren en v1"). Completo (v1.1+): restaurar snapshots en import.
- **Tests recomendados:** Test que exporta una VM con snapshot (mock backend) e importa, comprobando el comportamiento documentado (presencia o aviso de ausencia).
- **Notas:** El preflight ya avisa "valida import antes de borrar el origen" (línea 320) pero no menciona que los snapshots no viajan.

### HG-BUG-0004 — `Claude-Setup-x64.exe` (126 MB) y `.claude/` no están en `.gitignore`

- **Severidad:** High
- **Categoría:** Packaging / Repo hygiene
- **Archivos:** `.gitignore`, raíz del repo (`Claude-Setup-x64.exe`, `.claude/`, `capturas virtualbox/`)
- **Líneas aproximadas:** `.gitignore` completo (no cubre `*.exe` ni `.claude/`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.0.1
- **Descripción:** `git check-ignore Claude-Setup-x64.exe .claude/ "capturas virtualbox/"` devuelve NOT IGNORED. Son untracked hoy, pero un `git add .` los versionaría (126 MB de binario Windows en el repo).
- **Impacto:** Riesgo alto de commit accidental de un binario enorme y de config local; bloat permanente del historial.
- **Cómo reproducir:** `git check-ignore Claude-Setup-x64.exe` → vacío (no ignorado).
- **Resultado esperado:** Estos artefactos ignorados.
- **Resultado actual:** No ignorados.
- **Propuesta de fix:** Añadir a `.gitignore`: `*.exe`, `.claude/`, `capturas virtualbox/`. Borrar el `.exe` del árbol de trabajo (es ajeno al proyecto).
- **Tests recomendados:** `test_scripts_static.py` o similar: aserción de que `.gitignore` cubre `*.exe` y `.claude/`.
- **Notas:** El `.exe` parece descargado por error; no pertenece a HyperGery.

### HG-BUG-0005 — SQLite sin `busy_timeout` → "database is locked" en concurrencia

- **Severidad:** Medium
- **Categoría:** Concurrency / Hub
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/registry/store.py`
- **Líneas aproximadas:** 84-87 (`connect`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** `sqlite3.connect(..., isolation_level=None)` (autocommit) sin `PRAGMA busy_timeout` ni `journal_mode=WAL`, servido por `ThreadingHTTPServer`. Bajo escritura concurrente (varios heartbeats + polling de UI) SQLite puede devolver `OperationalError: database is locked` de inmediato.
- **Impacto:** HTTP 500 intermitentes en el Hub bajo carga de varios agentes; heartbeats/reportes perdidos.
- **Cómo reproducir:** Varios agentes + UI haciendo polling simultáneo contra el Hub; observar 500 ocasionales.
- **Resultado esperado:** Las escrituras concurrentes esperan/reintentan, no fallan.
- **Resultado actual:** Fallo inmediato bajo contención.
- **Propuesta de fix:** `conn.execute("PRAGMA busy_timeout=5000")` y `PRAGMA journal_mode=WAL` en `connect()`; opcional retry con backoff.
- **Tests recomendados:** Test con N hilos escribiendo heartbeats en paralelo sobre la misma DB; aserción de 0 errores.
- **Notas:** Severidad sube con el nº de agentes; en 2 hosts es ocasional.

### HG-BUG-0006 — `commands`/`events` sin TTL; replay de comando obsoleto al reconectar el agente

- **Severidad:** Medium
- **Categoría:** Hub
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/registry/store.py`, `agent.py`
- **Líneas aproximadas:** store 439-445 (`pending_commands_for_host`), 541-577 (events); agent 450-481 (`run_once`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** Los comandos `pending` no expiran. Un agente offline que reconecta ejecuta **todos** los comandos pendientes acumulados, sin importar su antigüedad. La tabla `events` también crece sin límite.
- **Impacto:** Un `vm_force_off`/`vm_shutdown` encolado hace horas se ejecuta tarde al reconectar → acción peligrosa fuera de contexto. Crecimiento ilimitado de tablas.
- **Cómo reproducir:** Encolar `vm_force_off` con el agente apagado; arrancar el agente más tarde; la VM se apaga.
- **Resultado esperado:** Comandos con TTL (descartar/expirar pendientes antiguos); limpieza periódica de events.
- **Resultado actual:** Sin expiración; replay garantizado.
- **Propuesta de fix:** Campo `expires_at` o filtrar por antigüedad en `pending_commands_for_host`; marcar `expired` los viejos. Retención por nº/edad en `events`.
- **Tests recomendados:** Test que crea un comando con `created_at` antiguo y verifica que no se devuelve como pendiente.
- **Notas:** Relacionado con idempotencia: `import_vm_package` es idempotente-seguro (falla si la VM ya existe), pero los power commands no.

### HG-BUG-0007 — Paquetes de estado sin checksums; validación solo comprueba existencia

- **Severidad:** Medium
- **Categoría:** Migration
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/v1/state_migration.py`
- **Líneas aproximadas:** 79-91 (manifest sin sha256), 101-130 (`validate_state_package` solo `is_file`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.0.1
- **Descripción:** A diferencia de `migration.validate_vm_package` (que verifica tamaño y sha256), el paquete de estado no guarda checksums y la validación solo comprueba que los ficheros existen.
- **Impacto:** Un `memory-state.save` o disco truncado por NAS inestable pasa la validación y luego falla en `restore_vm` (o restaura estado corrupto).
- **Cómo reproducir:** Truncar `memory-state.save` de un paquete válido; `validate_state_package` devuelve ok=True.
- **Resultado esperado:** La validación detecta el truncamiento por checksum/tamaño.
- **Resultado actual:** No lo detecta.
- **Propuesta de fix:** Añadir sha256+size por asset al manifest en export; verificarlos en `validate_state_package`.
- **Tests recomendados:** Test que trunca el memory-state y espera ok=False con mensaje de checksum.
- **Notas:** Paralelo directo con la protección ya existente en `migration.py`.

### HG-BUG-0008 — MainWindow sin `closeEvent`: QThreads vivos al cerrar → crash/abort

- **Severidad:** Medium
- **Categoría:** UI
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/ui_qt/main_window.py`
- **Líneas aproximadas:** 129-131 (listas de jobs), 3995-4009 (preview jobs), 4049-4091 (`run_operation`); **no existe `closeEvent`**
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** `BackendJob(QThread)` se guardan en `self.jobs`/`self._preview_jobs` (evita GC), pero no hay `closeEvent` que haga `wait()` al cerrar. Cerrar la ventana con un job en marcha destruye el QThread en ejecución.
- **Impacto:** "QThread: Destroyed while thread is still running" → posible abort del proceso; una operación de backend (export/import) queda interrumpida a mitad.
- **Cómo reproducir:** Lanzar un export largo y cerrar la ventana mientras corre.
- **Resultado esperado:** Al cerrar, esperar (con timeout razonable) a los jobs o advertir que hay operaciones en curso.
- **Resultado actual:** Destrucción de hilos vivos.
- **Propuesta de fix:** Implementar `closeEvent`: si hay jobs activos, preguntar/avisar y hacer `job.wait(ms)` acotado; cancelar preview jobs (best-effort). Centralizar el ciclo de vida (ver deuda técnica).
- **Tests recomendados:** Test Qt (offscreen) que lanza un job lento y llama a `close()`, verificando que no se destruye un hilo en ejecución.
- **Notas:** `console.py` sí tiene `closeEvent`; el patrón existe, falta replicarlo en MainWindow.

### HG-BUG-0009 — Centro de control → Redes: errores falsos CIDR/Gateway/DHCP

- **Severidad:** Medium
- **Categoría:** UI / Backend
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/v1/networks.py`, `v1/api.py`, `backend.py`
- **Líneas aproximadas:** networks 36-56 (`network_from_lab`), 59-67 (`_parse_cidr`); api 256-258; backend 477-482 (`network_ip_address`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** El tab Redes construye `Network` desde el campo `lab["subnet"]`, vacío en la mayoría de labs (→ error "missing CIDR") o, si está duplicado, dispara "Duplicate gateway"/"CIDR conflict"/"DHCP conflict". Pero las redes **reales** de libvirt usan octetos derivados por hash (`network_ip_address`), no `subnet`. El modelo lógico está divorciado del real.
- **Impacto:** El usuario ve errores de red que no corresponden a las redes reales (que funcionan). Confusión y pérdida de confianza. Es el known issue documentado, ahora con root-cause.
- **Cómo reproducir:** Crear 2 labs, abrir Centro de control → Redes.
- **Resultado esperado:** El tab refleja las redes reales (sin conflictos espurios) o explica que el modelo es lógico.
- **Resultado actual:** Errores falsos.
- **Propuesta de fix:** Derivar `Network.cidr`/`gateway` de la red libvirt real (`net-dumpxml`) en vez del campo `subnet`; o rellenar `subnet` de forma consistente y única por lab; o suprimir el chequeo cuando no hay subnet asignado.
- **Tests recomendados:** Test que dos labs sin `subnet` no producen errores de red en `validate_networks`.
- **Notas:** Ver también HG-BUG-0012 (colisión de octetos en la red real).

### HG-BUG-0010 — Hub PUT sin límite de tamaño → llenar NAS staging (DoS)

- **Severidad:** Medium
- **Categoría:** Hub / Security
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/registry/server.py`
- **Líneas aproximadas:** 284-300 (`_receive_package_file`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** El PUT escribe `Content-Length` bytes a staging sin límite de tamaño ni comprobación de espacio libre. Sin auth (HG-BUG-0001), cualquiera puede subir hasta llenar el disco.
- **Impacto:** DoS por agotamiento de disco del NAS staging; afecta migraciones legítimas.
- **Cómo reproducir:** `curl -XPUT $HUB/packages/x/big.bin --data-binary @bigfile`.
- **Resultado esperado:** Límite configurable y/o comprobación de espacio antes de escribir.
- **Resultado actual:** Sin límite.
- **Propuesta de fix:** Tamaño máximo por fichero/paquete; `shutil.disk_usage` previo; (con auth) cuota por host.
- **Tests recomendados:** Test que un upload por encima del límite devuelve 4xx sin escribir.
- **Notas:** El traversal sí está protegido (`_safe_package_path`); el problema es de recursos.

### HG-BUG-0011 — Sin tests de libvirt real; "0 skipped" enmascara cobertura mock-only

- **Severidad:** Medium
- **Categoría:** Tests
- **Archivos:** `hypergery-ubuntu/tests/` (todos)
- **Líneas aproximadas:** N/A (ausencia de marcador `needsRealLibvirt`/`skipif`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** No hay tests gated por libvirt real. "661 passed, 0 skipped" sugiere cobertura total, pero las rutas que ejecutan `virsh`/`qemu-img` (define/restore/save/net-define/snapshot) solo se prueban con mocks.
- **Impacto:** Bugs como HG-BUG-0003 (snapshots no importados) o regresiones en la interacción real con virsh no los caza CI.
- **Cómo reproducir:** `pytest -q` → 0 skipped; `rg "needsRealLibvirt"` → 0 resultados.
- **Resultado esperado:** Suite opcional `needsRealLibvirt` (skip si no hay virsh) que ejercite el camino real.
- **Resultado actual:** Solo mocks.
- **Propuesta de fix:** Añadir marcador `needsRealLibvirt` (skip por defecto) y un pequeño set de smoke tests reales para el workflow de migración; documentar cómo correrlos en el host KVM.
- **Tests recomendados:** El propio marcador + 3-4 smokes (crear/exportar/importar/borrar VM trivial).
- **Notas:** Ver `V1_0_TEST_GAP_ANALYSIS.md`.

### HG-BUG-0012 — Colisión de octeto en `network_ip_address` (~180 octetos)

- **Severidad:** Low · **Needs verification**
- **Categoría:** Backend
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/backend.py`
- **Líneas aproximadas:** 477-482
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** La IP de red se deriva como `192.168.{20 + hash%180}.1`. Con ~180 octetos posibles, por paradoja del cumpleaños dos labs colisionan en el mismo octeto con probabilidad ~50% alrededor de ~16 labs → mismo gateway/subred en libvirt → conflicto real.
- **Impacto:** A escala (muchos labs) dos redes HyperGery comparten subred 192.168.X → `net-start` falla o tráfico cruzado.
- **Cómo reproducir:** Crear labs hasta encontrar dos con el mismo octeto (verificar con `network_ip_address` para una lista de lab_ids).
- **Resultado esperado:** Asignación de subred sin colisiones (registro de octetos usados).
- **Resultado actual:** Colisión probabilística no detectada.
- **Propuesta de fix:** Llevar un registro de octetos asignados y elegir el primero libre; o detectar colisión en `ensure_network` y reasignar.
- **Tests recomendados:** Test que genera N lab_ids y comprueba unicidad/manejo de colisión.
- **Notas:** Confirmar con hardware real cuántos labs son realistas; severidad baja en el lab doméstico de 2 hosts.

### HG-BUG-0013 — Import sin preflight de espacio libre en el destino

- **Severidad:** Low
- **Categoría:** Migration
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/migration.py`
- **Líneas aproximadas:** 596-661 (`import_vm_package`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** El import copia discos al destino sin comprobar espacio libre antes. El export sí lo comprueba (líneas 322-333); el import no.
- **Impacto:** Con disco insuficiente, la copia falla a mitad. `cleanup_failed_migration` limpia los parciales (bien), pero el usuario recibe un error tardío en vez de un preflight claro.
- **Cómo reproducir:** Import en un destino con menos espacio que la suma de discos.
- **Resultado esperado:** Preflight de espacio antes de copiar.
- **Resultado actual:** Fallo a mitad + cleanup.
- **Propuesta de fix:** `shutil.disk_usage(backend.vms_dir)` ≥ suma de `package_size_bytes` antes de copiar.
- **Tests recomendados:** Test con espacio simulado insuficiente → error de preflight claro.
- **Notas:** El cleanup ya protege contra estado corrupto; esto es UX/robustez.

### HG-BUG-0014 — `_stop_connect_worker` congela la UI hasta 10s al cerrar la consola

- **Severidad:** Low · **Categoría:** UI
- **Archivos:** `hypergery-ubuntu/hypergery_ubuntu/ui_qt/console.py`
- **Líneas aproximadas:** zona `_stop_connect_worker`/`closeEvent` (898+)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción/Impacto/Fix:** Ya documentado en `V1_KNOWN_BUGS.md`: `thread.wait()` sin límite puede congelar hasta el timeout de 10s. Acotado y con señales desconectadas. Fix v1.1: `wait` acotado + mantener QThread vivo hasta `finished` (reparent + deleteLater).
- **Tests recomendados:** Test que el cierre con worker de conexión activo retorna en < umbral.
- **Notas:** Decisión consciente para evitar el crash "QThread destroyed".

### HG-BUG-0015 — Preview lanza varios jobs de captura sin throttle/cache

- **Severidad:** Low · **Categoría:** UI / Performance
- **Archivos:** `ui_qt/main_window.py` (3983-4024), `ui_qt/detail_panel.py`
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción/Impacto/Fix:** Ya documentado: cambiar rápido de VM lanza múltiples capturas. Fix: throttle/cache por VM (15-30s), no lanzar si ya hay captura en curso, ignorar resultado si la VM ya no está seleccionada (esto último ya se hace en `_on_preview_captured`).
- **Tests recomendados:** Test que cambios rápidos de selección no acumulan jobs.
- **Notas:** Solo trabajo redundante; no corrompe.

### HG-BUG-0016 — TOCTOU en `ensure_network` entre `net-info` y `net-start`

- **Severidad:** Low · **Categoría:** Backend / Concurrency
- **Archivos:** `backend.py` lines 549-573
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** Entre los `net-info` y el `net-start`/`net-define`, otro proceso (segundo agente, virsh manual) podría definir/arrancar la misma red → `net-start` "already active" o `net-define` duplicado.
- **Impacto:** Error transitorio al crear/importar VMs en paralelo en el mismo host.
- **Propuesta de fix:** Tratar `net-start` con `check=False` y aceptar "already active"; idem `net-define`.
- **Tests recomendados:** Test que `net-start` sobre red ya activa no lanza error.
- **Notas:** Bajo, requiere concurrencia real en el mismo host.

### HG-BUG-0017 — Versión duplicada en `pyproject.toml` y `__init__.py`

- **Severidad:** Low · **Categoría:** Packaging
- **Archivos:** `hypergery-ubuntu/pyproject.toml:3`, `hypergery_ubuntu/__init__.py:3`
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** `version = "1.0.0"` en dos sitios; hoy coinciden, pero son dos fuentes de verdad.
- **Impacto:** Riesgo de divergencia en el próximo bump (release notes vs runtime).
- **Propuesta de fix:** Fuente única (p. ej. `__version__` leído por `pyproject` con `dynamic`, o derivar `__version__` de metadata).
- **Tests recomendados:** Test que `pyproject` y `__version__` coinciden.

### HG-BUG-0018 — Bloat de repo: HTML/zip de diseño versionados + docs handoff en raíz

- **Severidad:** Low · **Categoría:** Packaging / Repo hygiene
- **Archivos:** `docs/design/v0.7/HyperGery.zip` (1.4MB), `*.html` (1.7MB ×2); raíz: `V09_REPORT.md`, `V10_REPORT.md`, `RESUMEN_EJECUTIVO_SESION.md`, `NEXT_STEPS_*`, `FINAL_V09_V10_HANDOVER.md`, `HANDOFF_UBUNTU.md`
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción/Impacto:** Binarios de diseño grandes en git + abundancia de docs de proceso en raíz dificultan la navegación y engordan el clon.
- **Propuesta de fix:** Mover HTML/zip a releases/assets externos o a `docs/archive/`; consolidar handoffs en `docs/archive/`.
- **Tests recomendados:** N/A.

### HG-BUG-0019 — Screenshot deja temp en `/tmp` si el proceso muere

- **Severidad:** Low · **Categoría:** Security
- **Archivos:** `ui_qt/screenshot.py:35-56`
- **Estado:** Open · **Blocker:** No · **Release objetivo:** backlog
- **Descripción:** `NamedTemporaryFile(delete=False)` (modo 0600, correcto) se borra en `finally`, pero si el proceso recibe SIGKILL antes, el `.ppm` con el framebuffer del invitado queda en `/tmp`.
- **Impacto:** Fuga menor del contenido de pantalla en máquinas compartidas; bajo (0600, solo el usuario).
- **Propuesta de fix:** Escribir en un subdir bajo `XDG_RUNTIME_DIR` con limpieza al inicio; o mantener en memoria si virsh soportara stdout.
- **Tests recomendados:** N/A (best-effort).
- **Notas:** El nombre de la VM va como **argumento** de lista a virsh (no shell) → sin inyección.

### HG-BUG-0020 — IP de laboratorio doméstico hardcodeada como placeholder

- **Severidad:** Info · **Categoría:** Security
- **Archivos:** `config.py:28` (`HUB_URL_PLACEHOLDER = "http://192.168.1.150:8765"`)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** backlog
- **Descripción:** IP de la red doméstica del autor como valor de respaldo. Marcado `source="default"` y oculto por `hub_is_configured()`.
- **Impacto:** Fuga informativa trivial; ningún secreto. Intencional y documentado.
- **Propuesta de fix:** Usar un placeholder neutro (`http://hub.local:8765` o cadena vacía).
- **Tests recomendados:** N/A.

### HG-BUG-0021 — El agente traga excepciones en heartbeat/report (`except: pass`)

- **Severidad:** Low · **Categoría:** Hub
- **Archivos:** `agent.py` 224-230 (heartbeat→report_vms), 372-375, 437-440, 478-479
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** Varios `try/except Exception: pass` silencian fallos de `report_vms`/`update_migration_status`. Ocultan problemas de red/Hub.
- **Impacto:** Diagnóstico difícil: el inventario del Hub puede quedar desactualizado sin rastro en logs.
- **Propuesta de fix:** Loguear el fallo (nivel warning) aunque se continúe.
- **Tests recomendados:** Test que un fallo de report_vms se loguea.
- **Notas:** El swallow en `run_forever` es deliberado (resiliencia), pero debe loguear.

### HG-BUG-0022 — Control Center muestra JSON crudo / textos en inglés

- **Severidad:** Low · **Categoría:** UX
- **Archivos:** `ui_qt/v1_render.py`
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción/Fix:** Ya documentado en known issues. Sustituir JSON por tablas/cards; revisar strings en inglés.
- **Tests recomendados:** Snapshot de render por sección (ya hay `test_qt_v1_render.py`).

### HG-BUG-0023 — Errores de libvirt no humanizados en rutas CLI/agente

- **Severidad:** Info · **Categoría:** Backend / UX
- **Archivos:** `cli.py`, `agent.py` (mensajes vía `stderr` de virsh)
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.1
- **Descripción:** `humanize_error_message` se aplica en la UI Qt, pero la CLI y el agente devuelven el `stderr` de virsh tal cual.
- **Impacto:** Mensajes técnicos para el usuario de CLI.
- **Propuesta de fix:** Reusar la humanización en CLI/agente para errores frecuentes.
- **Tests recomendados:** Test de mapeo de errores comunes.

### HG-BUG-0024 — `RELEASE_NOTES_v1.0-rc1.md` retenido tras v1.0.0

- **Severidad:** Info · **Categoría:** Docs
- **Archivos:** raíz: `RELEASE_NOTES_v1.0-rc1.md`; refs en `README.md`, `CHANGELOG.md`, `docs/qa/`
- **Estado:** Open · **Blocker:** No · **Release objetivo:** v1.0.1
- **Descripción:** Tras publicar v1.0.0, las notas de rc1 siguen en raíz; varias docs aún referencian rc1.
- **Impacto:** Confusión menor sobre la versión vigente.
- **Propuesta de fix:** Mover rc1 a `docs/archive/` y revisar referencias.
- **Tests recomendados:** N/A.
