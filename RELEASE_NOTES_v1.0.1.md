# HyperGery v1.0.1 — Release Notes

> **Estado: release estable (bugfix / migration safety).** Corrección sobre v1.0.0
> centrada en la seguridad de la migración y la higiene del repositorio. Sin
> features nuevas; sin cambios de live migration (sigue planificada para v1.5).

- **Versión:** 1.0.1 (`pyproject.toml`, `hypergery_ubuntu/__init__.py` y
  `ui_qt/styles.py` en `1.0.1`; la UI muestra `v1.0.1`).
- **Fecha:** 2026-06-09
- **Origen:** rama `fix/v1.0.1-migration-safety`, integrada en `main` y etiquetada `v1.0.1`.
- **Tipo:** bugfix release (migration safety + repo hygiene + security docs).

---

## Resumen ejecutivo

v1.0.1 cierra cinco hallazgos de la auditoría post-release de v1.0.0
(`docs/audit/`). El foco es **no perder ni dejar a medias una VM durante una
migración/teleport** y **decir la verdad sobre lo que se migra**:

- Un fallo a mitad del *state export* ya **no deja la VM de origen apagada**: se
  reanuda desde su estado guardado y se limpia el paquete parcial.
- Los **paquetes de estado** llevan checksums y se **verifica su integridad**.
- Los **snapshots** dejan de "viajar para luego descartarse": v1.0.1 **avisa
  explícitamente** que no se migran, sin pérdida silenciosa.
- Higiene del repo (`.gitignore`) y **avisos de seguridad LAN reforzados** para el
  Hub/API sin autenticación.

Validado con tests automáticos y un **UAT real en host KVM** (`gerard-MS-7E26`):
**5/5 PASS**.

---

## Bugs cerrados

### HG-BUG-0002 — Rollback seguro en *state export* (High, blocker)
`v1/state_migration.export_vm_state_package` congelaba la VM con `save_vm()` y, si
una copia de disco fallaba después, **dejaba la VM de origen apagada con un paquete
a medias y sin reanudarla**. Ahora todo lo posterior a `save_vm()` está envuelto en
recuperación: ante fallo se **reanuda el origen desde su estado guardado** y se
borra el paquete parcial; si la reanudación también falla, se **conserva
`memory-state.save`** y se lanza un error claro con el comando `virsh restore` para
recuperación manual.

### HG-BUG-0007 — Integridad/checksums del paquete de estado (Medium)
`validate_state_package` solo comprobaba existencia. Ahora el manifest lleva
`sha256`+`size` de `domain.xml`, discos y (cuando es legible) `memory-state.save`,
y la validación detecta truncamiento/corrupción. Compatibilidad: los paquetes
anteriores (sin checksums) siguen validando por existencia.

### HG-BUG-0003 — Snapshots: comportamiento explícito, **no migrados en v1.0.1** (High, blocker)
Antes los snapshots se empaquetaban y verificaban pero el importador los
descartaba (pérdida silenciosa). Ahora **no se empaquetan**, se conserva su
metadata para visibilidad, el manifest marca `snapshots_migrated=false` y se
**avisa explícitamente** en el preflight y en el resultado del import
("Snapshots are NOT migrated in v1.0.1").

### HG-BUG-0004 — Higiene de repositorio (High, hygiene)
`.gitignore` ahora cubre `.claude/`, `*.exe` y `capturas virtualbox/`, y se retiró
el instalador ajeno `Claude-Setup-x64.exe` (126 MB) del working tree para evitar
commits accidentales.

### HG-BUG-0001 — Avisos de seguridad LAN/Hub (mitigación + docs)
README y SECURITY.md dejan claro que el Hub/API **no tienen autenticación ni TLS**
en la línea v1.0.x: usar **solo en LAN de confianza**, bind `127.0.0.1` por
defecto, **no exponer a Internet**. La autenticación por token + TLS sigue
planificada para **v1.2** (no implementada aquí).

---

## Resultados QA

- `python -m compileall hypergery_ubuntu` → **OK**
- Focused: `pytest tests/test_v1_state_migration.py tests/test_migration.py tests/test_registry.py tests/test_cli.py -q` → **95 passed**
- Suite completa: `pytest -q` → **668 passed** (661 base + 7 nuevos), 0 fallos, 0 skips
- **UAT real 5/5 PASS** en host KVM `gerard-MS-7E26` (`qemu:///system`):
  ver [docs/qa/V1_0_1_UAT_RESULT.md](docs/qa/V1_0_1_UAT_RESULT.md).
  - `virsh save` → fallo de copia inducido → `virsh restore` → VM volvió a *ejecutando*.
  - Paquete parcial eliminado.
  - Disco truncado detectado por `Size mismatch`.
  - `memory-state.save` confirmado `root:root 0600` → checksum del RAM-state best-effort.
  - `snapshots_migrated=false` + warning "NOT migrated in v1.0.1".
  - `.gitignore` y README/SECURITY verificados.

---

## Known limitations

- **Hub/API sin autenticación fuerte** hasta **v1.2** (token + TLS). Usar solo en
  LAN de confianza; no exponer a Internet.
- **Live migration** (RAM en caliente / downtime mínimo) queda **fuera de v1.0.1**
  y va a **v1.5**.
- **`memory-state.save` root-owned** en `qemu:///system`: el checksum del RAM-state
  es **best-effort** cuando el fichero no es legible por el usuario de sesión
  (libvirt, como root, sí lo restaura). Comportamiento intencional y documentado.
- **Snapshots no se migran** en v1.0.1: se avisa explícitamente; conserva el origen
  hasta confirmar que no los necesitas.
- Otros hallazgos del audit (concurrencia SQLite del Hub, `closeEvent` Qt, redes del
  Centro de control, tests de libvirt real) quedan para **v1.1**.

---

## Upgrade notes (desde v1.0.0)

- Actualización **drop-in**: no hay cambios de esquema ni de datos. Reinstala el
  paquete editable o haz `git pull` y vuelve a lanzar la app.
- Los **paquetes de migración/estado existentes siguen siendo válidos** (los de
  estado sin checksums validan por existencia; los nuevos llevan checksums).
- Si dependías de que los snapshots viajaran en la migración: **no lo hacían** (se
  descartaban en destino). A partir de v1.0.1 se te avisa explícitamente; conserva
  la VM de origen hasta validar el destino.
- Si exponías el Hub más allá de loopback, revisa los avisos de seguridad: hazlo
  solo dentro de una LAN de confianza.

---

## Próximos pasos

- **v1.1 — robustez/refactor:** robustez del Hub (`busy_timeout`/WAL SQLite, TTL de
  comandos, límites de upload), `closeEvent` Qt con cancelación de jobs, redes del
  Centro de control alineadas con libvirt real, suite de tests `needsRealLibvirt`,
  e inicio del refactor de `main_window.py`.
- **v1.5 — live migration:** migración con estado de RAM en caliente y downtime
  mínimo, con máquina de estados de migración (preflight/transfer/switchover/
  rollback) y progreso uniforme Hub↔agente↔UI.
