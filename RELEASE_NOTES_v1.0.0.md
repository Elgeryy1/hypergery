# HyperGery v1.0.0 — Release Notes (BORRADOR)

> **Estado: BORRADOR.** Estas notas se preparan sobre la rama `feature/v1.1-ux` como
> final candidate. **No es la release final:** no hay merge a `main`, no hay tag `v1.0.0`
> y v1.0 **no** está declarada como final. La publicación requiere decisión explícita de
> Gerard (ver checklist en `docs/qa/V1_RELEASE_READINESS.md`).

- **Versión:** 1.0.0 (candidate; `pyproject.toml` aún en `1.0.0rc1`)
- **Fecha de redacción:** 2026-06-09
- **Rama:** `feature/v1.1-ux`

---

## Resumen ejecutivo

HyperGery v1.0 es la primera versión estable de un gestor de máquinas virtuales para Ubuntu
sobre KVM/libvirt, con una experiencia de usuario al estilo VirtualBox, completamente en
español y humanizada. Permite gestionar VMs locales y, a través de un Hub con NAS y agentes,
trabajar con varios equipos del laboratorio y **migrar máquinas de forma segura y verificable
entre hosts**, sin perder el original y regenerando identidad (UUID/MAC) en el destino.

Esta versión se centra en una base **sólida, segura y verificable**: la migración es de tipo
copia-y-verifica (no en caliente), pensada para entornos de laboratorio en LAN de confianza.
La migración en vivo queda planificada para v1.5.

## ¿Qué es HyperGery v1.0?

Una aplicación de escritorio (PySide6/Qt) que actúa como panel único para:
- Crear, configurar y operar VMs KVM/libvirt en el equipo local.
- Ver el estado del laboratorio (Hub/NAS y otros equipos) de un vistazo.
- Mover VMs entre hosts del laboratorio de forma controlada.
- Abrir consola VNC integrada, gestionar laboratorios aislados y diagnosticar el sistema.

## Highlights

- **Gestor de VMs estilo VirtualBox** para Ubuntu/KVM/libvirt (no un dashboard web).
- **UI en español y humanizada:** botones, estados (Encendida / Apagada / Pausada) y mensajes
  de error legibles; sin JSON crudo ni literales técnicos (RUNNING, shut off, DEFAULT…).
- **Layout VM-first:** árbol de VMs a la izquierda, panel de detalles en el centro
  (General/Sistema/Pantalla/Almacenamiento/Audio/Red/USB) y previsualización a la derecha.
- **Hub / NAS / agentes:** visión del laboratorio, equipos en línea y zona NAS para staging.
- **Migración segura entre hosts:** el origen permanece intacto; el destino se crea en el host
  correcto con UUID/MAC regenerados, disco verificado y arranque comprobado; staging del Hub
  limpio y sin tareas colgadas.
- **Consola VNC integrada**, ejecutada fuera del hilo de UI (sin congelación).
- **Laboratorios** aislados para experimentar sin invadir la pantalla principal.
- **Centro de control sin JSON crudo:** datos del equipo, batería, copias en el NAS, redes,
  usuarios e historial presentados como tarjetas, con acceso opcional a «detalles técnicos».
- **Tests y UAT aprobados** (ver QA abajo).

## Resultados de QA

| Verificación | Resultado |
|---|---|
| `python -m compileall hypergery_ubuntu` | **OK** (exit 0) |
| Tests Qt focalizados (`test_qt_ui`, `test_qt_v1_render`, `test_qt_iso_validation`) | **128 passed** |
| Suite completa (`pytest -q`) | **661 passed, 0 skipped** |
| UAT visual (pantalla principal, selección de VM, vistas secundarias, errores) | **PASS** |
| UAT migración (segura/verificable, host real) | **PASS** |

- Entorno verificado: Python 3.14.4 · PySide6 6.11.1 · pytest 9.0.3.
- Evidencias visuales: `docs/qa/evidence/v1-final/` (5 capturas).
- Detalle del UAT: `docs/qa/V1_FINAL_UAT_RESULT.md`.

## Known issues

- **Centro de control → Redes:** muestra un error relacionado con DHCP/CIDR/Duplicate Gateway.
  No afecta al flujo principal de gestión/migración. Aceptado como known issue de v1.0.
- **Hub/API sin autenticación fuerte:** usar únicamente en **LAN de confianza**. El
  endurecimiento de la autenticación queda para una versión posterior.
- **Live migration fuera de v1.0:** la migración de v1.0 es segura/verificable (no en caliente).
  La migración en vivo está planificada para **v1.5** (ver `docs/roadmap/V1_5_LIVE_MIGRATION.md`).

## Instalación / upgrade

Requisitos del host: Ubuntu con KVM/libvirt operativos, acceso a `qemu:///system` y permisos
del usuario en el grupo `libvirt`. Para la UI se necesita PySide6.

Instalación en entorno virtual (recomendado):

```bash
python -m venv ~/.venvs/hypergery
source ~/.venvs/hypergery/bin/activate
pip install -e hypergery-ubuntu
```

Ejecución de la app:

```bash
QT_QPA_PLATFORM=xcb ~/.venvs/hypergery/bin/hypergery
```

Notas de upgrade desde release candidate (1.0.0rc1):
- Antes del release final habrá que subir la versión de `pyproject.toml` de `1.0.0rc1` a `1.0.0`.
- No hay migración de estado destructiva conocida; el estado v1 se migra de forma compatible
  (cubierto por `tests/test_v1_state_migration.py`).

## Seguridad y limitaciones

- **Pensado para LAN de confianza:** el Hub/API no implementa autenticación fuerte en v1.0.
  No exponer el Hub a redes no confiables.
- **Migración no destructiva:** el original nunca se toca; el destino regenera UUID/MAC.
- **Rutas de paquetes de migración validadas:** se rechazan rutas inseguras / path traversal
  (fix `d731440`).
- **Operaciones potencialmente destructivas** (apagar, eliminar, snapshots) requieren acción
  explícita del usuario y no se ejecutan de forma automática.
- La live migration **no** está disponible: no intentar migrar VMs encendidas esperando
  continuidad de servicio en v1.0.

## Próximos pasos

- **v1.0.1** — polish y bugfix; resolver el known issue de Centro de control → Redes.
- **v1.5** — **live migration** real (VM encendida, downtime mínimo). Roadmap:
  `docs/roadmap/V1_5_LIVE_MIGRATION.md`.
- **Autenticación fuerte del Hub/API** — endurecer el acceso más allá de la LAN de confianza.
- **Refactor de `ui_qt/main_window.py`** — reducir deuda técnica conforme crece la UI.
