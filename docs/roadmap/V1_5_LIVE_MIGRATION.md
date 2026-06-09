# HyperGery v1.5 — Live Migration (Roadmap)

> Documento de planificación. **No implementa nada en v1.0.** Sirve para acordar alcance,
> requisitos y criterios de aceptación de la migración en vivo antes de empezar a desarrollarla.

## Objetivo

Permitir mover una VM **encendida** de un host a otro del laboratorio con **downtime mínimo**
(idealmente sub-segundo en buenas condiciones de red), manteniendo el servicio en ejecución y
preservando estado de memoria, conexiones y disco, frente a la migración v1.0 que es de tipo
copia-y-verifica con la VM apagada.

## Requisitos técnicos

- libvirt/QEMU-KVM en origen y destino con versiones compatibles para migración.
- API de libvirt de migración: `virDomainMigrate` / `virDomainMigrateToURI3` (migrate3).
- Conectividad libvirt directa o gestionada (TLS recomendado) entre hosts.
- CPU compatible entre hosts (mismo flag set o `host-model`/`host-passthrough` compatibles); en
  su defecto, baseline de CPU común para evitar fallos por instrucciones no disponibles.
- Reloj sincronizado (NTP) entre hosts.
- Ancho de banda suficiente para transferir el working set de memoria dentro del umbral de
  convergencia.

## Prerrequisitos de hosts

- Mismo modelo/arquitectura de CPU compatible (o baseline común configurado).
- Versiones de libvirt/QEMU compatibles para migración en vivo.
- Acceso de red entre hosts en los puertos de migración de QEMU (rango configurable) y al
  endpoint libvirt remoto.
- Almacenamiento: o bien **storage compartido** accesible por ambos hosts, o capacidad de
  **block migration** (copia de disco en caliente).
- Usuario/credenciales con permisos de migración en ambos extremos (clave del endurecimiento de
  auth del Hub, dependencia con el trabajo de seguridad).

## Estrategia libvirt: migrate vs migrate3

- **`virDomainMigrateToURI3` (migrate3)** como API principal: parámetros tipados, soporte de
  flags modernos, control fino de ancho de banda, post-copy y disks a migrar.
- Flags candidatos:
  - `VIR_MIGRATE_LIVE` — migración en vivo.
  - `VIR_MIGRATE_PEER2PEER` / `VIR_MIGRATE_TUNNELLED` — control de la ruta de datos.
  - `VIR_MIGRATE_PERSIST_DEST` + `VIR_MIGRATE_UNDEFINE_SOURCE` — persistir en destino y limpiar
    el origen sólo al confirmar éxito.
  - `VIR_MIGRATE_NON_SHARED_DISK` / `VIR_MIGRATE_NON_SHARED_INC` — block migration (full/incremental).
  - `VIR_MIGRATE_AUTO_CONVERGE` y/o `VIR_MIGRATE_POSTCOPY` — garantizar convergencia en VMs con
    memoria muy activa.
- Mantener la migración v1.0 (offline, copia-y-verifica) como **modo seguro/fallback** seleccionable.

## Storage compartido vs block migration

- **Storage compartido** (NFS/iSCSI/Ceph/NAS): preferido. Sólo se migra memoria/estado → más
  rápido y simple; el disco no se copia.
- **Block migration** (`NON_SHARED_DISK`): cuando no hay storage compartido. Copia el disco en
  caliente además de la memoria; mayor duración y consumo de red; requiere control de consistencia.
- Decisión automática según topología detectada (¿el path del disco es accesible en destino?),
  con override manual en la UI.

## Validaciones previas (preflight)

- Compatibilidad de CPU entre hosts.
- Versiones libvirt/QEMU compatibles.
- Conectividad y puertos de migración abiertos.
- Disponibilidad del storage en destino (compartido o espacio para block migration).
- Recursos en destino: RAM/CPU/disco suficientes.
- Estado de la VM apto (encendida, sin operaciones en curso, sin medios no migrables).
- Sin duplicidad de nombre/UUID/MAC en destino.
- Estimación de working set y ancho de banda → previsión de convergencia/downtime.

## Rollback

- La VM origen **no se elimina** hasta que el destino confirma estado `running` y sanity checks.
- Si la migración falla o no converge: abortar (`virDomainAbortJob`), dejar el origen intacto y
  en ejecución, limpiar restos en destino y staging del Hub.
- Política explícita anti doble-arranque: nunca dejar la VM activa en ambos hosts.
- Registro humano del intento (origen, destino, motivo del fallo) en el historial de migraciones.

## UI de progreso

- Diálogo de migración en vivo con fases claras: preflight → transferencia de memoria →
  (block migration si aplica) → conmutación → verificación.
- Barra/porcentaje de memoria transferida, velocidad, datos restantes y ETA.
- Indicador de convergencia y aviso si se activa auto-converge/post-copy.
- Botón **Cancelar** seguro (aborta sin tocar el origen).
- Mensajes humanos (coherentes con la humanización de v1.0), sin volcados técnicos salvo en
  «detalles técnicos».

## Métricas de downtime

- **Downtime real** de conmutación (tiempo en que la VM no responde).
- Duración total de la migración.
- Memoria total transferida y velocidad media.
- Nº de iteraciones de pre-copy / activación de post-copy.
- Objetivo: downtime de conmutación **< 1 s** en LAN con storage compartido; documentar
  resultados por escenario (compartido vs block migration).

## Criterios de aceptación

- [ ] Migrar una VM encendida entre dos hosts del laboratorio sin pérdida de servicio percibida.
- [ ] Downtime de conmutación medido y dentro del objetivo en escenario con storage compartido.
- [ ] Block migration funcional cuando no hay storage compartido.
- [ ] El origen permanece intacto y operativo si la migración se cancela o falla (rollback OK).
- [ ] Nunca queda la VM activa en ambos hosts; sin UUID/MAC duplicados en destino.
- [ ] Preflight bloquea migraciones inviables con mensaje humano y accionable.
- [ ] UI muestra progreso, ETA y permite cancelar de forma segura.
- [ ] Historial registra el resultado (éxito/fallo, métricas) sin traceback.
- [ ] Cobertura de tests para preflight, rollback y selección compartido/block.
- [ ] Documentación de operador y requisitos de hosts.
