# V1_KNOWN_BUGS — limitaciones y deuda conocida (objetivo: v1.1)

Formato: bug/limitación · severidad · reproducción · workaround · objetivo.

## Corregidos en la ronda de QA (2026-06-06)

Tras una revisión adversarial + pruebas dinámicas se encontraron y
arreglaron, con tests de regresión:

- **NAS path traversal** (alta): `lab_id`/`commit_id` se usaban como nombres
  de directorio sin validar; `commit_lab('../../x', …)` escribía fuera del
  NAS root. Ahora `_safe_segment()` valida los ids en commit/verify/restore/
  list y el `lab_id` debe coincidir con el manifest.
- **Commit corrupto listable** (media-alta): si fallaba la verificación de
  checksums tras copiar, el paquete quedaba y aparecía como commit válido en
  `list_commits()`/`health()`/API. Ahora se borra al fallar.
- **Pérdida de muestras de telemetría** (media): `record()` hacía
  read-modify-write sin lock; bajo concurrencia perdía casi todo. Ahora con
  lock por fichero y escritura atómica (temp+rename).
- **Ficheros parciales en memdiff** (baja): `apply_delta` podía dejar un
  fichero a medias ante OSError. Ahora se borra.
- **Rollback de teleport engañoso** (baja): decía "resumed" aunque el resume
  fallara. Ahora reporta "still paused" con log de error.
- **API expuesta por error** (media): bind no-loopback ahora exige
  `--allow-remote` explícito (la API sigue sin auth — eso es v1.2).

1. **Control Center muestra JSON crudo**
   - Severidad: baja (UX).
   - Repro: Control Center → cualquier tab.
   - Workaround: legible pero no "bonito"; Export Report para análisis.
   - v1.1: tablas/cards por tab (la prioridad 8 del goal era la estética).

2. **`v1 orchestrator plan` arranca el backend libvirt local**
   - Severidad: baja.
   - Repro: en una máquina sin virsh, el plan sale sin VMs locales (vacío).
   - Workaround: es el comportamiento degradado esperado; usar la API con
     `local_vms` inyectado para escenarios sin libvirt.
   - v1.1: detección más fina + mensaje explícito "no local backend".

3. **Telemetría remota depende del heartbeat (≤15 s de retardo)**
   - Severidad: baja.
   - Repro: cambiar carga en el host remoto; el Hub tarda un heartbeat.
   - Workaround: el staleness se marca; refrescar.
   - v1.1: endpoint `/telemetry` en el agent (campo `agent_url` ya existe).

4. **`suspend_copy_start` deja el origen pausado a propósito**
   - Severidad: informativa (decisión de seguridad, no bug).
   - Repro: teleport real; el origen queda `paused` hasta verificación.
   - Workaround: `virsh resume` o stop manual tras verificar el destino.
   - v1.1: acción guiada post-verificación en UI.

5. **API sin autenticación ni TLS**
   - Severidad: media (solo si se expone fuera de la LAN de confianza).
   - Workaround: bind por defecto 127.0.0.1; no abrir el puerto.
   - v1.2: token + TLS (NEXT_STEPS_V12_SECURITY.md).

6. **MemDiff no entiende qcow2 internamente**
   - Severidad: baja (experimental declarado).
   - Repro: deltas sobre qcow2 con realojamiento interno pueden cambiar más
     bloques de los "lógicamente" modificados.
   - Workaround: útil igualmente como estimador; usar block_size mayor.
   - v1.1/v1.2: modo raw-mapped o integración con qemu-img map.

7. **El historial de telemetría crece un archivo JSON por host sin rotación
   por tamaño** (solo por nº de muestras)
   - Severidad: baja. v1.1: rotación por bytes.

8. **Roles de External Nodes limitados** (`isard` o `unknown` al adaptar a
   HostInfo) — v1.1: rol propio `external` en HOST_ROLES.

9. **UI Control Center no expone NAS commit/teleport con confirmación**
   - Decisión deliberada esta noche (CLI/API los cubren con dry-run/confirm).
   - v1.1: diálogos con confirmación fuerte en UI.

No hay bugs conocidos que corrompan datos: todas las rutas destructivas son
opt-in, verificadas por checksum o simplemente inexistentes.
