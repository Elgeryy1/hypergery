# HyperGery v1.0.1 — UAT Result (migration safety)

- **Fecha/hora:** 2026-06-09 22:18 CEST
- **Rama:** `fix/v1.0.1-migration-safety`
- **Commit validado:** `4645e3c`
- **Host real:** `gerard-MS-7E26` (KVM/libvirt `qemu:///system`, doctor todo OK: /dev/kvm, virsh, qemu-img, virt-viewer, libvirt conectado)
- **Plan de referencia:** UAT real mínimo v1.0.1 (Tests 1–5)

## Tests automáticos previos
- `python -m compileall hypergery_ubuntu` → **OK**
- Focused: `pytest tests/test_v1_state_migration.py tests/test_migration.py tests/test_registry.py tests/test_cli.py -q` → **95 passed**
- Suite completa: `pytest -q` → **668 passed** (661 base + 7 nuevos), 0 fallos, 0 skips

## Resultado UAT: **5/5 PASS**

| # | Hallazgo | Resultado |
|---|----------|-----------|
| 1 | HG-BUG-0002 — rollback state export | ✅ PASS |
| 2 | HG-BUG-0007 — integrity state package | ✅ PASS |
| 3 | HG-BUG-0003 — snapshots explicit behavior | ✅ PASS |
| 4 | HG-BUG-0004 — repo hygiene | ✅ PASS |
| 5 | HG-BUG-0001 — LAN security docs | ✅ PASS |

Método para 1–3: VM dummy desechable `uat-dummy` (HyperGery-managed, disco 1 GiB,
RAM 256 MiB, ISO placeholder), creada y eliminada en el UAT. Nunca se tocó ninguna
VM real del host. Staging local desechable en `~/uat-v101` (nunca el NAS real).

---

## Detalle por test

### Test 1 — HG-BUG-0002 (rollback seguro de state export) → PASS
- **Procedimiento:** `uat-dummy` arrancada (`running`); harness directo sobre
  `export_vm_state_package` con `shutil.copy2` monkeypatcheado para fallar
  **después** de `save_vm()` (fallo controlado, sin Hub, sin tocar el NAS).
- **Observado:**
  - Error claro: `State export failed for uat-dummy: UAT induced copy failure. Source VM resumed locally (continues where it was).`
  - Log real (`~/.local/state/hypergery/logs/hypergery.log`):
    `Domain 'uat-dummy' saved ...` → `virsh ... restore ...` →
    `Domain restored from ...` → `WARNING [teleport] state export failed for uat-dummy; resumed it locally from saved state`.
  - `backend.vm_state("uat-dummy")` → **running** (reanudada desde el estado guardado).
  - Paquete parcial **eliminado** (`leftover package dir exists: False`).
  - Sin tareas/procesos colgados.

### Test 2 — HG-BUG-0007 (integridad del paquete de estado) → PASS
- **Procedimiento:** export de estado real (sin fallo) → validación; luego copia
  con disco truncado → validación. Corrupción solo sobre la **copia**.
- **Observado:**
  - `manifest` incluye `domain_xml_sha256` y `sha256` por disco; paquete válido
    `validate_state_package(...).ok` → **True**.
  - `memory-state.save` confirmado **`root:root 0600`** → no legible por el usuario
    de sesión → `memory_state_sha256` **omitido** (integridad del RAM-state
    **best-effort**, comportamiento documentado e intencional para no romper el
    export en `qemu:///system`; libvirt como root sí restaura el fichero — ver Test 1).
  - Copia con disco truncado: `validate ok` → **False**, error
    `Size mismatch (corrupt/truncated): disks/uat-dummy.qcow2`.

### Test 3 — HG-BUG-0003 (snapshots, comportamiento explícito) → PASS
- **Procedimiento:** snapshot `uat-snap1` en VM apagada → `migrate preflight`
  (solo lectura) → `migrate package` offline a staging desechable →
  `migrate validate-package`.
- **Observado:**
  - preflight warning: *"VM has 1 snapshot(s). Snapshots are NOT migrated in
    v1.0.1: the imported VM will have no snapshots. Keep the source until you have
    confirmed you do not need them."*
  - Paquete **sin** subdir `snapshots/`; `validate-package` → `ok: True`.
  - `manifest.snapshots_migrated` → **false**; metadata conservada
    (`snapshots` count = 1, nombre `uat-snap1`) → **sin pérdida silenciosa**.
  - Tipos de asset empaquetados: solo `disk`, `iso` (ningún `snapshot`).
  - Paso 4 (import a VM copia) **omitido** por ser opcional y ya cubierto por el
    unit test `test_migration.py`; la evidencia a nivel de manifest/result es concluyente.

### Test 4 — HG-BUG-0004 (higiene de repo) → PASS
- `git check-ignore` confirma ignorados: `.claude/`, `*.exe`, `capturas virtualbox/`.
- `Claude-Setup-x64.exe` **no tracked** y **ausente** del working tree.
- `git status` no lista artefactos de tooling.

### Test 5 — HG-BUG-0001 (aviso de seguridad LAN en docs) → PASS
- **README.md** (líneas 122–133) y **SECURITY.md** (líneas 27–32) cubren los 5 puntos:
  Hub/API sin auth, solo LAN de confianza, no exponer a Internet, bind
  `127.0.0.1` por defecto (+`--allow-remote`), auth/TLS planificados para v1.2.

---

## Evidencia clave (resumen)
- `virsh save` → fallo de copia inducido → `virsh restore` → VM volvió a **ejecutando**.
- Paquete parcial **eliminado** tras el fallo.
- Disco truncado detectado por **`Size mismatch`** en `validate_state_package`.
- `memory-state.save` **`root:root 0600`** → checksum del RAM-state **best-effort** (documentado).
- `snapshots_migrated=false` + warning **"NOT migrated in v1.0.1"**, metadata conservada.
- `.gitignore` OK (`.claude/`, `*.exe`, `capturas virtualbox/`).
- README/SECURITY OK con el aviso LAN reforzado.

## Revert final
- VM dummy `uat-dummy` **eliminada** (`delete-vm --delete-disks`).
- Snapshot `uat-snap1` **eliminado**.
- Staging `~/uat-v101` **eliminado** (incluido el `memory-state.save` root-owned).
- **VMs reales intactas:** `ubuntu-migrated-migrated` siguió ejecutando; `ubuntu`,
  `hg-v06-2host-source`, `hg-v06-e2e-source` sin cambios.
- `git status` limpio (el UAT no modificó el repo).
- `main` `663f240` y tag `v1.0.0` `9b302ee` intactos.

## Veredicto
- **Apto para preparar release v1.0.1.** Los 5 fixes están validados en hardware KVM real.
- **Pendiente por orden explícita de Gerard:** bump `1.0.0`→`1.0.1`
  (`pyproject.toml` + `__init__.py`), entrada en `CHANGELOG.md`, merge a `main`,
  tag `v1.0.1` y publicación. Nada de eso se ha ejecutado en este UAT.
