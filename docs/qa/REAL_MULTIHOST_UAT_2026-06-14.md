# UAT real multi-host — 2026-06-14 (PC AMD ↔ portátil Intel)

> Sesión de aceptación sobre **hardware físico real**, conducida por SSH desde el
> PC. Cubre 4 escenarios: aceleración 3D (VirGL), live migration en caliente
> cross-vendor, migración offline (package/import) y control remoto vía Hub.
> Todas las VMs de prueba llevan prefijo `hgtest-` y se borraron al terminar;
> las VMs reales de ambos equipos quedaron intactas.

## Entorno

| | PC (origen de la sesión) | Portátil |
|---|---|---|
| Hostname | `gerard-MS-7E26` | `gery-Lenovo-ideapad-330S-14IKB` |
| IP | 192.168.1.44 | 192.168.1.73 (registrado stale como .84 en el Hub) |
| Usuario | `gerard` | `gery` |
| CPU | **AMD Ryzen 7 7700X** (`AuthenticAMD`) | **Intel Core i5-8250U** (`GenuineIntel`) |
| GPU | (RDNA2 iGPU) | **Intel UHD 620** (driver `i915`) |
| libvirt / QEMU | 12.0.0 / 10.2.1 | 12.0.0 / 10.2.1 |
| HyperGery CLI | rama `feat/gpu-passthrough` (reporta 1.5.0rc0) | 1.5.0rc0 (`/usr/bin`) |
| NAS / Hub | montado en `/home/gerard/NAS_Gerard` (CIFS) | **NO** montado |

- `qemu:///system` operable **sin sudo** en ambos (usuarios en grupo `libvirt`).
- `sudo` pide contraseña en el portátil (no bloqueó nada: todo lo necesario ya instalado).
- Conectividad `qemu+ssh` de libvirt **bidireccional** verificada (PC↔portátil).
- Hub `http://192.168.1.150:8765` → `/health` = `{"ok": true}`.

---

## Test 1 — Aceleración 3D compartida (VirGL) · ✅ PASS (host único, portátil)

**Objetivo:** confirmar que el 3D acelerado funciona vía virtio-gpu + VirGL sobre
la iGPU Intel, sin GPU passthrough, sin segunda GPU y sin reinicios.

**Setup:** VM `hgtest-virgl3d` (Ubuntu 24.04 cloud image) con el XML idéntico al
que genera el backend de la rama:
```xml
<video><model type='virtio' heads='1'><acceleration accel3d='yes'/></model></video>
<graphics type='egl-headless'><gl rendernode='/dev/dri/by-path/pci-0000:00:02.0-render'/></graphics>
```
El driver de `0000:00:02.0` es `i915` → `pick_render_node()` elige
`/dev/dri/by-path/pci-0000:00:02.0-render`.

**Evidencia — host:** QEMU arrancó sin error con
`-display egl-headless,rendernode=/dev/dri/by-path/pci-0000:00:02.0-render`
(si el stack EGL/virglrenderer estuviera roto, QEMU abortaría al arrancar).

**Evidencia — invitado (log del kernel por serie):**
```
[drm] pci: virtio-vga detected at 0000:00:01.0
[drm] features: +virgl +edid -resource_blob -host_visible
[drm] features: +context_init
[drm] cap set 0: id 1, max-version 1, max-size 308
[drm] cap set 1: id 2, max-version 2, max-size 1408
[drm] Initialized virtio_gpu 0.1.0 0 for 0000:00:01.0 on minor 0
```
`+virgl` + los dos capsets (VirGL / VirGL2) = **3D acelerado negociado de extremo a
extremo**. No se hizo `glxgears` visual (las cloud images no traen credenciales y
no había sudo para inyectarlas); la negociación a nivel de driver es la prueba
autoritativa de que el 3D está habilitado.

**Veredicto:** la aceleración 3D es la vía correcta para este hardware — sin los
riesgos del passthrough (sin dejar el host sin pantalla, sin tocar GRUB/initramfs).

---

## Test 2 — Live migration en caliente cross-vendor · ✅ PASS (con CPU de compatibilidad)

**Objetivo:** migrar en caliente una VM encendida entre PC (AMD) y portátil (Intel).

**VM:** `hgtest-livemig`, 2 GiB RAM, disco qcow2 de la cloud image. Transporte:
`qemu+ssh://`, **block migration** (`--copy-storage-all`, el NAS no está en ruta
común), ruta de disco remapeada con `--xml`, UUID del `dumpxml --migratable`.

| Intento | CPU del guest | Resultado |
|---|---|---|
| 1 | `host-passthrough` (vía `hypergery-cli v1 migrate-live`) | ❌ HyperGery **bloquea** en preflight (cross-vendor con CPU del host) — guardarraíl correcto |
| 2 | `qemu64` (compat a secas) | ❌ `error: la CPU huésped no coincide: ausencia de características: svm` |
| 3 | `qemu64` **+ `<feature policy='disable' name='svm'/>` + `name='vmx'`** | ✅ **ÉXITO** |

**Evidencia intento 3 (PC AMD → portátil Intel):**
```
Migración: [ 1,67 %] ... [99,46 %] [46,96 %] ... [100,00 %]   (re-copia de páginas sucias = pre-copy real)
EXIT=0
ORIGEN (PC): apagado     DESTINO (portátil): ejecutando
```
**Liveness en destino:** `cpu_time` 11.314696 → 11.410182 s en 3 s → el guest
**ejecuta instrucciones (vivo)**, no colgado/panic.

**Retorno Intel → AMD** (con `--migrateuri tcp://192.168.1.44` porque el portátil
no resuelve el hostname del PC para el canal NBD): **ÉXITO**, 0→100%, PC
`ejecutando`, portátil `apagado`, `cpu_time` 7.2016 → 7.2064 s (vivo).

**Conclusión:** la live migration cross-vendor AMD↔Intel **es posible y es
bidireccional**, siempre que el modelo de CPU del guest **oculte las extensiones de
virtualización del fabricante** (`svm` de AMD / `vmx` de Intel), que son lo que no
se traduce entre marcas. Origen siempre intacto hasta confirmar; nunca activa en
dos hosts (el rollback del intento fallido dejó el origen `running`).

**Tradeoff honesto:** ocultar `svm`/`vmx` impide la virtualización anidada dentro
de la VM. Irrelevante para cargas normales.

---

## Test 3 — Migración offline (package → transfer → import) · ✅ PASS

**Objetivo:** mover una VM **apagada** PC → portátil (cross-vendor seguro en frío;
es también la vía recomendada para mover una VM con 3D, que no es live-migrable).

**Flujo (herramientas reales de HyperGery):**
1. `migrate package hgtest-offline … --no-iso` → paquete con `domain.xml`,
   `disks/*.qcow2`, `manifest.json`, `logs/`, checksums.
   - **Requisito descubierto:** la VM debe ser *HyperGery-managed* (metadata
     `metadata/hg:hypergery/hg:managed=true` en el domain XML); una VM cruda da
     `ERROR: ... is not managed by HyperGery`.
2. `migrate validate-package …` → `ok: true`.
3. `scp` del paquete al portátil (el NAS no está montado allí; con Hub-Transfer no
   haría falta).
4. `migrate import … --target-vm-name hgtest-offline` → `imported: true`,
   **UUID/MAC regenerados**, `source_will_be_deleted: false` (origen intacto).
5. `start` en el portátil:
   - ❌ primero falló con `la CPU es incompatible … funcionalidades prohibidas: svm`
     (misma causa que Test 2: la CPU `qemu64` arrastraba `svm`).
   - ✅ tras añadir `disable svm`/`vmx` a la CPU de la VM importada: **arranca**,
     `cpu_time` 2.68 → 4.98 s (vivo).

**Conclusión:** la migración offline funciona de extremo a extremo; la portabilidad
cross-vendor del arranque exige la misma receta de CPU compatible que la live.

---

## Test 4 — Control remoto vía Hub (App → Hub → Agente → libvirt) · ✅ PASS

**Objetivo:** apagar de forma remota una VM del portátil desde el PC, a través del
Hub del NAS.

**Flujo:**
1. PC encola el comando en el Hub:
   ```python
   RegistryClient().create_command(
       "gery-Lenovo-ideapad-330S-14IKB", "vm_shutdown", {"vm_name": "hgtest-offline"})
   # → command_id cmd-4f4baa811ffb…, status: pending
   ```
2. Agente del portátil procesa la cola (`hypergery-cli agent once`) → comando
   `status: done`, `target_host_id: gery-Lenovo-ideapad-330S-14IKB`.
3. La VM pasó a **`apagado` en ~2 s** (ACPI shutdown graceful, asíncrono).

**Conclusión:** la cola de comandos segura del Hub funciona (solo acciones del
allowlist: `vm_start`/`vm_shutdown`/`vm_force_off`; nada de delete/undefine/shell).

---

## Hallazgo clave y mejora propuesta

La migración cross-vendor (en vivo **y** en frío) **funciona** con la receta:

```xml
<cpu mode='custom' match='exact'>
  <model fallback='allow'>qemu64</model>
  <feature policy='disable' name='svm'/>
  <feature policy='disable' name='vmx'/>
</cpu>
```

**Propuesta para HyperGery:** hoy el preflight de live migration **bloquea en duro**
el cross-vendor cuando la VM usa la CPU del host (`v1/live_migration.py`, función
`_cpu_vendor` + chequeo de vendor). En vez de prohibirlo, debería **ofrecer un
"perfil de CPU de compatibilidad"** (baseline `qemu64`/`x86-64-v2/v3` + ocultar
`svm`/`vmx`) seleccionable al crear la VM o al migrar, que **habilita** la migración
AMD↔Intel. Eso convierte el par PC↔portátil de Gerard en plenamente migrable.

## Estado de la cola de UAT humano (goalplan §6)

- **U10 / U12** (live migration en caliente + cancelación/rollback): **PASS** con la
  salvedad del perfil de CPU compatible (cross-vendor).
- **U11** (block migration sin shared storage): **PASS** (se usó `--copy-storage-all`).
- **VirGL 3D** (sustituye al objetivo de GPU passthrough U14 para el caso de uso de
  Gerard): **PASS**.
- Migración offline + control remoto vía Hub: **PASS**.

## Pendiente / a afinar antes de una "prueba a full"

1. **Registros del Hub stale:** el portátil figura con IP vieja (.84 vs .73 real) y
   los agentes están en estado `activating` (no corriendo de forma estable). Para la
   full conviene tener los agentes arrancados y los hosts frescos.
2. **NAS no montado en el portátil:** la offline usó `scp`; con Hub-Transfer (sube
   por el Hub) no haría falta montaje común.
3. **Perfil de CPU compatible:** implementar la propuesta de arriba para no tener que
   editar el XML a mano en cada VM cross-vendor.
4. **HyperGery del portátil desactualizado** (1.5.0rc0, sin VirGL): actualizar a la
   rama `feat/gpu-passthrough` si se quiere crear VMs con 3D desde la app allí.

## Limpieza

Todas las VMs `hgtest-*` y sus discos borrados en ambos equipos. Verificado al
cierre: PC con 0 VMs; portátil con sus 4 VMs originales (`ubuntu-hub-e2e`,
`ubuntu-test-v07`, `ubuntuserver`, `windowss`) intactas. Imagen base
`noble-cloud.img` conservada en el PC para la próxima prueba a full.
