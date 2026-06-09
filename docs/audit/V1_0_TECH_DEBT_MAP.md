# HyperGery v1.0.0 — Tech Debt Map

> Mapa de deuda técnica con prioridad. No son bugs (van a `V1_0_BUG_REGISTER.md`); son costes estructurales que frenan el desarrollo futuro, especialmente la live migration de v1.5.

## Resumen de prioridad

| # | Deuda | Impacto | Esfuerzo | Prioridad |
|---|-------|---------|----------|-----------|
| TD-1 | `main_window.py` (4653 líneas) monolítico | Alto | Alto | v1.1 (incremental) |
| TD-2 | `dialogs.py` (2900 líneas) monolítico | Medio | Alto | v1.1+ |
| TD-3 | Ciclo de vida de jobs Qt sin centralizar | Alto (bloquea live mig.) | Medio | v1.1 |
| TD-4 | Sin abstracción "Job de migración" con fases/rollback | Alto (bloquea v1.5) | Alto | v1.5 prep |
| TD-5 | Hub sin auth ni capa de limpieza/retención | Alto | Medio | v1.1/v1.2 |
| TD-6 | Modelo de red lógico (`subnet`) vs real (hash octet) duplicado | Medio | Medio | v1.1 |
| TD-7 | `app_tk.py` (763) UI legacy en el árbol | Bajo | Bajo | v1.1 (retirar) |
| TD-8 | Versión en 2 fuentes; packaging/repo hygiene | Bajo | Bajo | v1.1 |
| TD-9 | Progreso por callback ad-hoc, sin canal uniforme | Medio (bloquea v1.5) | Medio | v1.5 prep |
| TD-10 | Docs de proceso dispersas en raíz | Bajo | Bajo | v1.0.1/v1.1 |

---

## TD-1 — `ui_qt/main_window.py` (4653 líneas)

**Síntoma:** un único `MainWindow` concentra navegación, páginas (VMs, labs, Centro de control), wizard de nueva VM, acciones de toolbar/menú, preview, ejecución de jobs y refresco. ~30 handlers `*_dialog.exec()`.

**Coste:** difícil de testear por unidad, alto riesgo de regresión al tocar cualquier área, merge conflicts, y bloquea mejoras transversales (p. ej. `closeEvent` con cancelación — HG-BUG-0008).

**Plan incremental (sin big-bang):**
1. Extraer cada "página" a su propio widget/módulo (`pages/vms.py`, `pages/labs.py`, `pages/control_center.py`).
2. Extraer el **gestor de jobs** (ver TD-3) a un componente reutilizable.
3. Extraer el wizard de Nueva VM y los flujos de migración a controladores.
4. `MainWindow` queda como ensamblador + navegación.

**Criterio:** cada página testeable de forma aislada (offscreen); `main_window.py` < ~1500 líneas.

## TD-2 — `ui_qt/dialogs.py` (2900 líneas)

Múltiples diálogos en un fichero (settings, snapshot, cleanup preview, migración, etc.). Dividir por diálogo en `dialogs/`. Prioridad menor que TD-1; hacerlo a la par cuando se toque cada flujo.

## TD-3 — Ciclo de vida de jobs Qt sin centralizar

**Síntoma:** `run_operation` y `_capture_preview` crean `BackendJob(QThread)` ad-hoc, los guardan en listas y conectan señales a mano. No hay `closeEvent` (HG-BUG-0008), no hay cancelación, no hay límite de concurrencia, el preview duplica jobs (HG-BUG-0015).

**Coste:** crashes al cerrar, trabajo redundante, y **es el principal bloqueo de UI para live migration** (que necesita jobs largos, cancelables y con progreso).

**Plan:**
- Un `JobManager` (QObject) que registre jobs, exponga `active`, cancele, y haga `wait` acotado en `closeEvent`.
- Throttle/cache de preview por VM.
- Cancelación cooperativa (flag chequeado por el `fn`).

**Criterio:** cerrar la ventana con jobs activos no destruye hilos vivos; preview no duplica; test offscreen lo cubre.

## TD-4 — Sin abstracción "Job de migración" con fases y rollback

**Síntoma:** `migration.start_remote_migration` es un procedimiento lineal que entremezcla preflight, packaging, upload, creación de comando y actualización de estado. El rollback está repartido (`cleanup_failed_migration`, `export_vm_package` con su `try/except`, y **falta** en state export — HG-BUG-0002).

**Coste:** difícil añadir fases (live migration: dirty-page sync, switchover, activate), difícil un rollback consistente por fase, difícil reportar progreso uniforme.

**Plan (prep v1.5):**
- Modelar una **máquina de estados de migración** explícita (estados ya enumerados en `REMOTE_MIGRATION_STEPS`) con, por fase: `run`, `rollback`, `progress`.
- Centralizar la limpieza/rollback en un único punto por fase.
- Hacer el origen "intocable hasta confirmación" un invariante del modelo, no una decisión por función.

## TD-5 — Hub sin auth ni capa de limpieza/retención

`registry/server.py`/`store.py`: sin auth (HG-BUG-0001), sin TTL de comandos/events (HG-BUG-0006), sin `busy_timeout` (HG-BUG-0005), sin límites de upload (HG-BUG-0010).

**Plan:** introducir un middleware de auth (token), `busy_timeout`+WAL, retención de comandos/events, y límites de recursos. Es deuda transversal de seguridad y robustez; ver `V1_0_SECURITY_REVIEW.md`.

## TD-6 — Modelo de red lógico vs. real duplicado

`v1/networks.py` razona sobre un campo `subnet` que no está sincronizado con la red real de libvirt (`backend.network_ip_address`, octeto por hash). Esto produce HG-BUG-0009 (errores falsos) y HG-BUG-0012 (colisión real no detectada).

**Plan:** una sola fuente de verdad. O bien el modelo lógico se **deriva de la red libvirt real** (`net-dumpxml`), o bien se persiste un `subnet` único por lab y la red libvirt se construye desde él (eliminando el hash de octeto). Lo segundo además resuelve la colisión.

## TD-7 — `app_tk.py` (763) UI Tk legacy

Coexiste con la UI Qt (la oficial). Si ya no se mantiene, retirarla reduce superficie y confusión. Confirmar que ningún flujo/documentación la referencia antes de eliminar.

## TD-8 — Packaging / versión / hygiene

- Versión en `pyproject.toml` y `__init__.py` (HG-BUG-0017) → fuente única.
- `.exe`/`.claude/` sin gitignore (HG-BUG-0004), HTML/zip de diseño versionados (HG-BUG-0018).
- Considerar un script de export "limpio" que genere un tarball sin cachés/binarios para distribución.

## TD-9 — Progreso por callback ad-hoc

`export_vm_package` usa `progress_callback(label, i, n)`; el Hub solo ofrece polling (`poll_remote_migration_status`). No hay canal de progreso uniforme Hub↔agente↔UI.

**Plan (prep v1.5):** definir un contrato de progreso (porcentaje + fase + mensaje) propagado por el Job de migración (TD-4) y expuesto por el Hub (idealmente eventos push o long-poll), consumido por la UI sin bloquear.

## TD-10 — Docs de proceso dispersas en raíz

Reports de sesión, handoffs, next-steps y rc1 en la raíz. Consolidar en `docs/archive/` y dejar en raíz solo README/CHANGELOG/LICENSE/SECURITY/CONTRIBUTING + release notes vigentes.

---

## Orden recomendado de pago de deuda

1. **v1.1:** TD-3 (jobs Qt, desbloquea UI y arregla 0008/0015), TD-5 (Hub robustez), TD-6 (redes), TD-8/TD-10 (hygiene), inicio de TD-1.
2. **v1.5 prep:** TD-4 + TD-9 (juntos: máquina de estados + progreso uniforme) — son el cimiento de la live migration.
3. **Continuo:** TD-1/TD-2 incremental al tocar cada área; TD-7 cuando se confirme que Tk está muerto.
