# v2.0 — Investigación (no construcción)

> Estado: INVESTIGACIÓN. Nada de este documento es código comprometido; son
> análisis de viabilidad con recomendación honesta. Lo construible hoy ya se
> construyó (v1.1–v1.7); esto es lo que NO debe prometerse sin prototipar.

## 1. HG-MEMDIFF propio (qcow2 / dirty blocks)

**Qué hay:** `v1/memdiff.py` (experimental) hace hashing por bloques de 1 MiB
sobre el fichero crudo — NO entiende qcow2: un cambio de un cluster qcow2
puede mover offsets físicos y disparar falsos positivos masivos.

**Lo que haría falta de verdad:**
- Parsear las tablas L1/L2 de qcow2 y comparar a nivel de cluster lógico
  (64 KiB por defecto), no de offset físico. Complejidad media-alta y formato
  con versiones (v2/v3, refcounts, snapshots internos, bitmaps).
- Alternativa mucho mejor y soportada: **dirty bitmaps de QEMU**
  (`qemu-img bitmap`, blockdev-backup con `bitmap-mode=incremental`, y
  `virsh backup-begin --backupxml` con checkpoints de libvirt ≥ 7.x). Hace
  exactamente lo que HG-MEMDIFF persigue (transferir solo bloques sucios)
  con el conocimiento del formato dentro de QEMU, no en HyperGery.

**Recomendación:** abandonar el parser propio; prototipar backups
incrementales con checkpoints de libvirt (`virsh backup-begin` /
`backup-dumpxml`). Encaja directo con las políticas de backup de v1.3.
Esfuerzo estimado del prototipo: 1–2 noches; riesgo bajo (API estable).

## 2. Storage dedup

- Dedup genérico de paquetes en el NAS: contenido qcow2 con offsets variables
  hace que el dedup por fichero no encuentre casi nada; dedup por bloques
  requiere un almacén content-addressed (tipo borg/restic/casync).
- **Recomendación pragmática:** (a) `qemu-img convert -O qcow2 -c` para
  compresión de paquetes fríos; (b) backing files compartidos para plantillas
  (`qemu-img create -b base.qcow2`), que ya es dedup "gratis" para labs
  clonados; (c) si el NAS es btrfs/ZFS, activar dedup/compresión del
  filesystem y no reimplementarlo en HyperGery. No construir un dedup propio.

## 3. Packet visualizer

- Fuente de datos viable sin tocar los guests: `tcpdump -i hgbrXXXX` en los
  bridges de los labs (requiere CAP_NET_RAW/root) o contadores de
  `/sys/class/net/<bridge>/statistics` (sin privilegios, solo volumen).
- MVP honesto: gráfica de tráfico por red de lab en el Centro de control con
  los contadores sysfs (poll 1s, sin payloads, sin privilegios). La captura
  de paquetes real (protocolos, conversaciones) exige root + parsing pcap
  (scapy/dpkt) y consideraciones de privacidad → segunda fase.
- Esfuerzo MVP: 1 noche (telemetry + UI chart). Captura completa: 3+.

## 4. vGPU / SR-IOV / Looking Glass

- **vGPU (NVIDIA GRID/mdev):** requiere GPUs datacenter con licencia; fuera
  de alcance para hardware doméstico. No prometer.
- **SR-IOV gráfico (Intel):** i915 SR-IOV está fuera del kernel mainline
  para consumo (DKMS de terceros en Alder Lake+). La iGPU actual
  (gerard-MS-7E26) podría soportarlo vía módulo externo: experimental,
  riesgo de pantalla. Solo investigar en una sesión presencial.
- **Looking Glass:** sí es viable con la 2ª GPU del U14 (passthrough v1.7 +
  IVSHMEM + cliente looking-glass). Es el siguiente paso natural tras U14.
  Esfuerzo: 1–2 noches una vez U14 esté validado.

## 5. Plugins

- Lo barato y seguro: puntos de extensión declarativos (entry_points de
  Python para proveedores de telemetría/acciones de menú), con el API v1
  como superficie. Un sistema de plugins arbitrarios (código de terceros en
  el proceso Qt) abre problemas de seguridad que el RBAC de v1.2 no cubre.
- Recomendación: posponer hasta que exista demanda real; documentar el API
  v1 (ya estable y autenticado) como la vía de integración oficial.

## Prioridad recomendada para la siguiente iteración

1. Backups incrementales con checkpoints de libvirt (sustituye HG-MEMDIFF).
2. Looking Glass tras validar U14.
3. Packet visualizer MVP (contadores sysfs).
4. Dedup → delegar en filesystem/backing files (no construir).
5. Plugins → posponer.
