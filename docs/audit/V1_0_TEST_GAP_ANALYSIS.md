# HyperGery v1.0.0 — Test Gap Analysis

> Estado del suite: **661 passed, 0 skipped** (`pytest -q`, ~12s, Python 3.14.4). 38 ficheros de test, ~17k líneas.

## 1. Qué está BIEN cubierto

- **Migración (offline-copy):** `test_migration.py` (441 líneas) cubre preflight, manifest, export/import, **rechazo de rutas inseguras** (path traversal, absolutos, symlinks — regresión de los fixes pre-v1), cleanup de paquete parcial.
- **State migration:** `test_v1_state_migration.py` (374) — export/import/validate y rechazo de traversal.
- **Hub/registry:** `test_registry.py` (569) — store, comandos, migraciones, staging cleanup, `_safe_package_path`.
- **Agente:** `test_agent.py` (487) — ejecución de comandos, power commands con allowlist y validación de estados.
- **CLI:** `test_cli.py` (451) — incluye la regresión de `host test` no bloqueante y `--dry-run` que siempre gana.
- **UI Qt (offscreen):** `test_qt_ui.py` (2039), `test_qt_v1_render.py`, `test_qt_preview.py`, `test_qt_iso_validation.py`, `test_qt_templates.py` — render por secciones, validación de ISO, preview (incluido ignorar resultado de VM no seleccionada).
- **Backend estático/fixes:** `test_backend_static.py` (519), `test_backend_fixes.py` (396).
- **v1 core:** orchestrator (doble conteo RAM), telemetry (atomicidad/lock), memdiff, nas (commit corrupto borrado, dry-run), networks/rbac/nodes, teleport/memdiff.
- **Humanización de errores:** `test_humanize.py` (442) — buena cobertura de mensajes.

Cobertura conceptual: **lógica pura, validaciones, parsing, stores y rutas de seguridad ya parcheadas** están bien. Es un suite serio.

## 2. Qué FALTA (gaps reales)

### 2.1 Crítico para los bugs High de este audit
- **Rollback de state export en fallo de copia (HG-BUG-0002).** No hay test que simule `OSError` a mitad de copia de discos y verifique que (a) el paquete parcial se borra y (b) la VM de origen se reanuda. **Este test fallaría hoy** y documentaría el bug.
- **Snapshots tras import (HG-BUG-0003).** No hay test que exporte una VM con snapshot e importe verificando que los snapshots llegan (o que se avisa de que no). El comportamiento actual (empaquetar y descartar) pasa desapercibido.

### 2.2 Integración con libvirt real (HG-BUG-0011)
- **No existe marcador `needsRealLibvirt`** ni smoke tests reales. Todo `virsh`/`qemu-img` es mock. Falta una suite opcional (skip si no hay `virsh`) que ejercite: crear VM trivial, export, import en el mismo host (nombre distinto), arranque/apagado, borrado. Sin esto, regresiones en la interacción real no se detectan en CI.

### 2.3 Concurrencia (HG-BUG-0005)
- No hay test que lance N hilos escribiendo heartbeats/reportes contra el mismo SQLite y verifique 0 `database is locked`. Caza el gap de `busy_timeout`.

### 2.4 Ciclo de vida de UI (HG-BUG-0008)
- No hay test que lance un `BackendJob` lento y llame a `MainWindow.close()` verificando que no se destruye un QThread vivo (offscreen).

### 2.5 Integridad y robustez
- **Checksums de state package (HG-BUG-0007):** test que trunca `memory-state.save` y espera `ok=False`.
- **Preflight de espacio en import (HG-BUG-0013):** test con espacio insuficiente simulado.
- **Expiración de comandos (HG-BUG-0006):** test que un comando antiguo no se sirve como pendiente.
- **Upload con límite (HG-BUG-0010):** test que un PUT sobredimensionado devuelve 4xx sin escribir.
- **Colisión de octetos de red (HG-BUG-0012):** test que N lab_ids no colisionan o se reasignan.

### 2.6 Negativos / edge cases poco cubiertos
- Payloads malformados al Hub (JSON no-objeto ya cubierto; faltan tipos inesperados en cada endpoint POST).
- `poll_remote_migration_status` con `command` en estados raros/desconocidos.
- Clock drift / `last_seen` con tz naive (parcialmente cubierto por `effective_host_status`).
- Red caída / NAS caído / Hub caído (resiliencia del agente): el swallow de excepciones (HG-BUG-0021) no está testeado para verificar logging.

## 3. Riesgo de "tests falsamente verdes"

- El **mock del backend** es permisivo: muchos tests de migración usan un backend simulado que **no ejecuta virsh**, por lo que el camino real de `define_domain_xml`/`restore_vm`/`snapshot` no se valida. Es la causa de que HG-BUG-0003 (snapshots) no salte en CI pese a "passed".
- "0 skipped" se interpreta como cobertura total, pero **no hay rama de integración real**; conviene introducir skips intencionados (`needsRealLibvirt`) para reflejar la realidad.

## 4. Tests de regresión a añadir (resumen accionable)

| Test | Caza | Prioridad |
|------|------|-----------|
| State export: fallo de copia → rollback + resume origen | HG-BUG-0002 | v1.0.1 |
| Migración con snapshot → presencia/aviso en import | HG-BUG-0003 | v1.0.1 |
| State package con fichero truncado → validación falla | HG-BUG-0007 | v1.0.1 |
| `.gitignore` cubre `*.exe`/`.claude/` | HG-BUG-0004 | v1.0.1 |
| SQLite concurrente sin "database is locked" | HG-BUG-0005 | v1.1 |
| `MainWindow.close()` con job vivo no destruye QThread | HG-BUG-0008 | v1.1 |
| Comando antiguo no servido como pendiente | HG-BUG-0006 | v1.1 |
| Import con espacio insuficiente → preflight claro | HG-BUG-0013 | v1.1 |
| PUT sobredimensionado → 4xx sin escribir | HG-BUG-0010 | v1.1 |
| Unicidad/manejo de colisión de octetos de red | HG-BUG-0012 | v1.1 |
| `pyproject` y `__version__` coinciden | HG-BUG-0017 | v1.1 |

## 5. Suite `needsRealLibvirt` (propuesta)

Marcador que hace **skip si `shutil.which("virsh") is None`** o si falta una variable `HYPERGERY_REAL_LIBVIRT=1`. Set mínimo a correr en el host KVM (PC):
1. Crear VM trivial (ISO pequeña), confirmar `dominfo`.
2. Export del paquete → validar checksums.
3. Import en el mismo host con nombre distinto → UUID/MAC regenerados.
4. Arranque/apagado/force-off por estados permitidos.
5. Borrado con `delete_disks` (solo VM de prueba marcada como managed).
6. State migration de una VM encendida y **fallo inducido** (HG-BUG-0002).

## 6. Cobertura aproximada

No hay `pytest-cov` configurado en el repo. **Recomendación:** añadir `coverage`/`pytest-cov` a dev-deps y publicar un número de línea/branch como gate informativo (no bloqueante) en CI, separando "unit (mock)" de "needsRealLibvirt".

## 7. Matriz CI propuesta

| Job | Entorno | Qué corre | Gate |
|-----|---------|-----------|------|
| unit | Python 3.12/3.13/3.14, sin libvirt | `pytest -q` (mock) | bloqueante |
| qt-offscreen | + PySide6, `QT_QPA_PLATFORM=offscreen` | tests Qt | bloqueante |
| lint/static | ruff/mypy (si se adoptan) | estático | informativo |
| coverage | unit + cov | `pytest --cov` | informativo |
| real-libvirt | host KVM autohospedado (PC) | `needsRealLibvirt` | manual/nightly |

Hoy el proyecto corre en al menos Python 3.13 y 3.14 (cachés `.pyc` de ambos); conviene fijar la matriz explícita.
