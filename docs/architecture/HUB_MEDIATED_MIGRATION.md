# Arquitectura: migración mediada por el Hub (flujo oficial v1.5)

> **Visión de producto (Gerard, 2026-06-10):** TODO pasa por el Hub Docker del
> NAS. `Origen → Hub → Destino`. Ningún host migra por libre: los agentes
> obedecen jobs del Hub. La migración directa host-a-host por libvirt
> (`qemu+ssh`) queda como **modo avanzado/experimental**, no como flujo
> principal.

## Topología

```
   ┌──────────────┐        ┌──────────────────────┐        ┌──────────────┐
   │  PC origen   │        │   NAS (QNAP)         │        │   Portátil   │
   │  HyperGery   │ ─────► │   Hub Docker         │ ─────► │   destino    │
   │  + Agent     │  sube  │   - jobs/migrations  │ baja   │   + Agent    │
   │              │ estado │   - cola de comandos │ comando│              │
   │              │ ◄───── │   - staging paquetes │ ─────► │              │
   └──────────────┘ status │   - auth + auditoría │ status └──────────────┘
                           └──────────────────────┘
```

## El flujo oficial, fase a fase (implementado HOY)

| Fase | Quién | Qué hace | Estado en el Hub |
|---|---|---|---|
| 1. Job | origen → Hub | `migrate remote --transfer hub` crea `migration_id`; preflight (espacio, destino online y KVM-ready) | `preflight` |
| 2. Autorización | Hub | token Bearer obligatorio en TODOS los endpoints (v1.2); sin token/RBAC no hay job | 401 si falta |
| 3. Empaquetado | origen | export del estado/disco/manifest con **sha256 por asset** | `packaging` |
| 4. Subida | origen → Hub | `upload_package` al staging del Hub (límite de tamaño, anti-traversal); la copia local temporal se borra, **la VM origen no se toca** | `uploaded` |
| 5. Coordinación | Hub | encola el comando `remote-import` para el host destino (cola con TTL) | `waiting_target` |
| 6. Descarga | destino (agente) | el agente recoge el job, `download_package` del staging | `importing` |
| 7. Validación | destino | **checksums sha256 verificados**; paquete corrupto → rollback, destino limpio | `failed` si no cuadra |
| 8. Activación | destino | import con UUID/MAC regenerados; `start_after_import` solo si el job lo pide | `done` |
| 9. Liberación origen | Hub/usuario | **el origen NUNCA se borra automáticamente** (`source_will_be_deleted: false`); se libera solo tras confirmar el destino | auditado |
| 10. Auditoría | Hub | tabla de eventos (incl. fallos de auth), `hub packages`, limpieza segura de staging | persistente |

Para VMs ENCENDIDAS, el mismo esquema con `v1 teleport` (save → paquete de
estado por el Hub/NAS → restore): si el envío falla, **el origen se reanuda
localmente desde su estado guardado** (garantía v1.0.1, UAT real 5/5).

## Anti doble-activa

- Paquete importado con **UUID y MAC regenerados** (copia, no clon idéntico) y
  discos propios: no hay corrupción cruzada posible.
- Teleport save/restore: el origen queda guardado/parado y solo se reanuda
  localmente ante fallo (nunca a la vez que el destino).
- Journal persistente (`migration_journal.py`): bloquea `start_vm` de una VM
  con migración en vuelo; verificado en UAT real (retuvo la entrada durante el
  fallo de locking de U10).

## Modo avanzado (NO flujo principal): live migration directa

`v1 migrate-live` (qemu+ssh/qemu+tls, RAM en caliente, downtime ~145 ms en el
UAT). Requiere conectividad libvirt directa entre hosts, CPU compatible y
(para shared storage) NFS. **Posicionamiento: experimental/avanzado, para
laboratorio; no bloquea release; las migraciones normales van por el Hub.**
CIFS/SMB rechazado para shared storage (guard en preflight).

## Auditoría de la visión: qué existe y qué falta

**Ya implementado** (v0.7→v1.2, validado en UAT reales): job en Hub, auth
obligatoria, estados por fase, staging central con límites, cola de comandos
con TTL, agentes obedeciendo jobs, checksums, rollback en destino, origen
intocable hasta confirmación, auditoría de eventos, teleport con safe-resume.

**Pendiente para versiones siguientes (no bloquea v1.5):**
1. **Decisión de activación en el Hub**: hoy `start_after_import` se fija al
   crear el job; la visión completa quiere que el Hub decida la activación y
   la liberación del origen como pasos explícitos del job (aprobación en dos
   fases). → candidato v1.6.
2. **Journal extendido al flujo Hub en ambos extremos**: hoy cubre la live
   migration; extenderlo a teleport/import como cinturón extra. → v1.6.
3. **UI**: el Centro de control muestra `/progress`; falta una vista de jobs
   de migración del Hub de primera clase. → con el wizard de migración.
