# HyperGery v1.7.0

Gestor/hipervisor de escritorio para Ubuntu sobre **KVM/QEMU/libvirt**. Esta
versión se distribuye como **paquete Debian (`.deb`)** — no necesitas clonar el
código ni instalar nada con pip para usarla.

## Instalación (recomendada: `.deb`)

Descarga `hypergery_1.7.0_all.deb` desde la página de Releases e instálalo:

```bash
sudo apt install -y ./hypergery_1.7.0_all.deb
```

`apt` resuelve las dependencias (PySide6, etc.). Para arrancar: `hypergery`
(o desde el menú de aplicaciones). El agente multi-host se habilita solo por
sesión de usuario. Desinstalar (`sudo apt remove hypergery`) **no borra tus
datos** (`~/.config/hypergery`, `~/.local/share/hypergery`).

Requisitos del host (los instala `apt` como recomendados o ya los tienes):
`qemu-system-x86`, `libvirt-daemon-system`, `libvirt-clients`, `virt-viewer`,
`qemu-utils`, `ovmf`. El usuario debe estar en los grupos `kvm` y `libvirt`.

## Novedades desde v1.0.1 (último release público)

Las versiones v1.1–v1.6 se desarrollaron pero **nunca se publicaron** como release;
este v1.7.0 es el primer release desde v1.0.1, así que si vienes de v1.0.1 lo
recibes **todo de golpe**. Resumen acumulado por versión:

- **v1.1 — App instalable + robustez:** identidad de app y empaquetado **`.deb`**,
  JobManager (cierre sin colgarse), Hub robusto (WAL/busy_timeout, TTL de comandos,
  límite de upload), redes coherentes con libvirt, suite `needsRealLibvirt`.
- **v1.2 — Seguridad Hub/API:** token bearer obligatorio (ficheros `0600`,
  rate-limit), RBAC aplicado en el API, pairing, tokens por usuario.
- **v1.3 — Backups y plantillas:** políticas de backup al NAS con retención,
  **Backup Verifier** (restaura y arranca para validar), snapshot branching, tags
  y presupuestos por lab.
- **v1.4 — Orquestación y telemetría:** telemetría en cada heartbeat, orchestrator
  aplicable con confirmación, `GET /dashboard`, API companion (acciones seguras).
- **v1.5 — Live migration en caliente** (detalle abajo).
- **v1.6 — App Android nativa** (detalle abajo).
- **v1.7 — GPU/3D + consola remota** (detalle abajo).

## Novedades destacadas de v1.7 (y de los hitos no publicados)

### Aceleración 3D compartida (VirGL)
GPU virtio con `accel3d` + `egl-headless`: el guest obtiene 3D acelerado por la
GPU del host **sin GPU passthrough, sin segunda GPU y sin reinicios**. Es la vía
recomendada para 3D. Validado en hardware real (Intel UHD 620): el guest negocia
`+virgl` de extremo a extremo.

### GPU passthrough (VFIO/PCI)
Detección de GPUs y grupos IOMMU, preflight con **parada dura** (rechaza la GPU
del escritorio si no hay segunda GPU), bind a `vfio-pci` con rollback, `<hostdev>`
en el XML, anti-Code-43 para NVIDIA. Los cambios de host (GRUB/initramfs) solo se
**proponen**, nunca se aplican solos.

### Live migration en caliente (RAM+CPU)
Migración en vivo sobre `virsh migrate` (pre-copy, auto-converge, postcopy
opcional, block migration sin almacenamiento compartido, downtime medido, abort
con origen intacto, nunca activa en dos hosts). **Validado en hardware real con
la prueba de fuego**: un Ubuntu Server con nginx + PostgreSQL + Redis migrado
AMD→Intel mientras servía tráfico — **0 peticiones HTTP perdidas de 1060**,
switchover de **~0,23 s**, mismo `boot_id` (no se reinició), datos intactos.

> **Migración entre fabricantes (AMD↔Intel):** posible **con un perfil de CPU de
> compatibilidad** (`qemu64` ocultando `svm`/`vmx`). Con CPU `host-passthrough` el
> preflight bloquea el cruce de fabricante (correcto). Una VM con GPU passthrough o
> VirGL no es live-migrable: el preflight lo bloquea y se mueve apagada por el Hub.

### Consola remota integrada
La consola propia de HyperGery ahora abre VMs de **otros equipos**: tuneliza el
VNC del host remoto por SSH (`ssh -L`) y la pinta como si fuera local. Antes solo
había consola para VMs locales.

### App Android nativa
Cliente Kotlin/Compose contra el API seguro (token + TLS por VPN/WireGuard):
pairing seguro, inventario, dashboard con progreso en vivo y acciones seguras
(start / ACPI shutdown / snapshot con confirmación).

## Correcciones de teclado en la consola integrada

- **Ctrl+letra** (Ctrl+C, Ctrl+D, Ctrl+Z…) ahora llega al guest — antes se perdía
  la letra y no podías, p. ej., salir de `top`.
- **AltGr** (ISO_Level3_Shift) se envía al guest → los caracteres de tercer nivel
  (`| @ # ~ \`) salen bien.
- El **keymap del VNC** se fija automáticamente al layout del host, de modo que
  los símbolos de teclados no-US se mapean correctamente (el keymap debe coincidir
  con el layout del guest; override con `HYPERGERY_VNC_KEYMAP`).

## Corrección de migración

- **Block migration** ahora fija `--migrateuri tcp://<host>` para que el canal de
  datos/NBD use una dirección alcanzable, evitando el error `address resolution
  failed for <hostname>` cuando el origen no resuelve el hostname del destino por
  DNS.

## Seguridad (recordatorio)

El Hub y el API son **solo LAN/VPN**: usan token bearer obligatorio (ficheros
`0600`, rate-limit), pero **no expongas el Hub a Internet** sin TLS/VPN. Conexiones
entre equipos solo por canales legítimos (SSH, WireGuard, Tailscale, HTTPS/TLS).

## Estado de pruebas

- `pytest`: **993 passed, 8 skipped** (skips = suite `needsRealLibvirt` y real-only).
- UAT real multi-host (AMD Ryzen 7 7700X ↔ Intel i5-8250U): VirGL 3D, live
  migration en caliente cross-vendor (bidireccional), migración offline y control
  remoto vía Hub — todo **PASS**. Detalle en
  [docs/qa/REAL_MULTIHOST_UAT_2026-06-14.md](qa/REAL_MULTIHOST_UAT_2026-06-14.md).

## Limitaciones honestas

- Migración cross-vendor solo con perfil de CPU de compatibilidad (sin virtualización
  anidada en esas VMs).
- Sin live-RAM con motor propio (HG-MEMDIFF sigue siendo investigación).
- Consola remota: VNC sobre túnel SSH (requiere `ssh` y acceso al host remoto).
- App Android: requiere desplegar el API con TLS/VPN; no exponer el Hub a Internet.
