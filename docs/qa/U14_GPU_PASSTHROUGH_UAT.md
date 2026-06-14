# U14 — UAT real de GPU passthrough (RTX 2070 → VM)

- **Rama:** `feat/gpu-passthrough` (sobre `release/v1.5.0-rc`; NO toca la RC)
- **Host:** sobremesa gerard-MS-7E26 — RTX 2070 (`0000:01:00.0`, grupo IOMMU 13,
  4 funciones: GPU + audio HDMI + USB-C + UCSI) + iGPU AMD Raphael (`0000:11:00.0`)
- **VM de prueba:** `hgtest-gpu` (UEFI/OVMF, 4 GiB, ISO Ubuntu 24.04 live) — ya creada

## Estado previo verificado (2026-06-11)

| Comprobación | Resultado |
|---|---|
| IOMMU activo | ✅ 35 grupos (AMD lo activa por defecto, sin tocar GRUB) |
| Grupo IOMMU de la 2070 | ✅ limpio (solo funciones 01:00.x) |
| vfio-pci disponible | ✅ módulo presente |
| `v1 gpu preflight 0000:01:00.0` | ⛔ **bloqueado a propósito**: el único monitor (DP-4) cuelga de la 2070 |

## Paso 0 — REQUIERE A GERARD (físico)

1. Apagar el equipo (o en caliente si te atreves: el escritorio puede parpadear).
2. **Mover el cable del monitor de la RTX 2070 al conector de vídeo de la
   PLACA BASE** (iGPU AMD).
3. Arrancar y abrir sesión normal. Comprobar: `cat /sys/class/drm/card*-*/status`
   debe mostrar `connected` en la tarjeta de `0000:11:00.0` (amdgpu).

Tras esto el preflight pasará y la opción «GPU física…» de la UI mostrará la
2070 como apta ✅.

## Pasos del UAT (desde la UI, `./scripts/dev-run.sh`)

1. Seleccionar `hgtest-gpu` (apagada) → menú **Máquina → GPU física…**
2. Debe listar la RTX 2070 ✅ (con nombre real vía pci.ids) y la iGPU ⛔
   (motivo: es la GPU del escritorio / única pantalla).
3. Conectar GPU → confirmar → debe avisar: Code 43 mitigado, UEFI ya activo,
   live migration bloqueada.
4. Iniciar `hgtest-gpu`. libvirt hace el bind a vfio-pci automáticamente
   (`managed='yes'`); no hace falta sudo.
5. En el guest (live): `lspci | grep -i nvidia` debe mostrar la 2070 y su audio.
6. Apagar la VM → la 2070 vuelve al host (`lspci -nnk` → driver nvidia de nuevo,
   puede tardar unos segundos o requerir `nvidia-smi` para reactivarse).
7. Intentar **Mover a otro equipo** con la GPU conectada → el preflight debe
   bloquearlo con mensaje claro.
8. UI → Quitar GPU de la máquina → el XML pierde los `<hostdev>`.

## INCIDENTE 2026-06-11 — congelón de vídeo en el primer intento

Con el monitor ya en la iGPU, el primer arranque de `hgtest-gpu` **congeló el
escritorio** del host. Causa raíz (journal del boot anterior, 17:01:33):

```
kernel: NVRM: Attempting to remove device 0000:01:00.0 with non-zero usage count!
gnome-shell: Failed to lock front buffer on /dev/dri/card2
```

gnome-shell/mutter (Wayland) abre TODAS las GPUs como dispositivos KMS aunque
no pinten en ellas — incluso en una sesión recién iniciada con el monitor en la
iGPU (verificado: 1 MiB abierto tras reiniciar). El detach en caliente del
driver nvidia con usage count > 0 cuelga el compositor. **Conclusión: en un
host de escritorio GNOME, el detach en caliente NO es viable**; hay que dedicar
la GPU con vfio-pci desde el arranque (sección siguiente). Recuperación del
incidente: reinicio; la 2070 volvió sola a sus drivers (managed=yes no llegó a
consumar el detach).

## Si el paso 4 falla con «device busy / module in use»

gnome-shell (Wayland) abre TODOS los nodos DRM aunque el monitor esté en la
iGPU; a veces el driver nvidia no se deja soltar en caliente. Escalada:

1. Cerrar sesión y volver a entrar (mutter suelta el nodo) y reintentar.
2. Plan B (persistente, decisión de Gerard): bind de vfio-pci en el arranque —
   `hypergery-cli v1 gpu propose-host-changes` imprime los cambios exactos de
   GRUB/initramfs; se aplican A MANO y con reinicio.

## Recuperación

- Host sin pantalla en la iGPU: volver a enchufar el cable a la 2070 (siempre
  funciona; la 2070 solo queda sin driver mientras la VM esté encendida).
- Devolver la GPU al host a mano: `hypergery-cli v1 gpu unbind 0000:01:00.0`
  (grupo entero vía drivers_probe).
- La VM es `hgtest-*`: se puede borrar sin miedo al acabar.

## DECISIÓN DE PRODUCTO 2026-06-11 (Gerard + jefe de proyecto Claude)

Tras el incidente, **la aceleración gráfica oficial de HyperGery es VirGL**
(checkbox «Aceleración 3D» en el creador): la GPU del host se comparte con las
VMs vía virtio-gpu, sin vfio, sin sudo, sin reiniciar y sin congelones — y
funciona en cualquier equipo, también con una sola GPU. El passthrough
completo (este U14) queda como **modo avanzado**: requiere dedicar la GPU con
vfio-pci en el arranque (fichero en `/tmp/hypergery-vfio.conf` preparado, 3
comandos sudo + reinicio, reversible) y se validará cuando Gerard decida
dedicar la 2070. No bloquea nada.

**VirGL verificado en real (2026-06-11):** `hgtest-virgl` (UEFI, Ubuntu live)
arrancada con `virtio-vga-gl` + `egl-headless` sobre el nodo de render de la
iGPU (`pci-0000:11:00.0-render`, amdgpu). Lecciones de la prueba real:

- Sin `rendernode` explícito, qemu muere con `EGL_NOT_INITIALIZED`: libvirt no
  concede ningún nodo DRM al cgroup si el XML no lo nombra. → `pick_render_node()`
  elige la ruta by-path (estable) de una GPU con driver Mesa.
- El EGL headless del driver NVIDIA propietario no sirve para libvirt-qemu
  (necesita /dev/nvidia*): Mesa (amdgpu/i915) es el camino fiable.
- Una VM con VirGL **no puede live-migrarse** (igual que con hostdev): el
  preflight v1.5 ahora la bloquea con mensaje claro, y el checkbox de la UI
  avisa y desactiva «CPU compatible» (acelerada O migrable, nunca ambas).
- El detach de hostdevs desde el código nuevo (`detach_gpus_from_vm`) se
  ejecutó en real sobre `hgtest-gpu`: las 4 funciones fuera, XML limpio. ✅

## Resultado del passthrough completo

_(pendiente — se ejecutará cuando se dedique la GPU; ver Decisión de producto)_

| Paso | Resultado |
|---|---|
| Preflight tras mover el cable | |
| Attach desde la UI | |
| Arranque con GPU (bind automático) | |
| GPU visible en el guest | |
| GPU devuelta al host al apagar | |
| Migración bloqueada con hostdev | |
| Detach desde la UI | |
