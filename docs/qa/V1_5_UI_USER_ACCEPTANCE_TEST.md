# HyperGery v1.5.0 — UAT desde la UI (UI-first, para Gerard)

> **Esto NO publica nada.** Sin tag, sin merge a main, sin release.
> Nuevo gate de release: **v1.5.0 no está lista hasta pasar este UAT desde la
> interfaz**, sin depender de comandos para el flujo principal. Los comandos
> que aparecen son solo para **diagnóstico o verificación secundaria**.

## Antes de empezar

- Instala/actualiza el .deb (Test 1 del UAT clásico) o lanza la app desde el
  venv. Abre HyperGery: **se abre la ventana principal** con la lista de
  máquinas y el menú lateral (Inicio, Máquinas, Centro de control…).
- Solo se usan VMs `hgtest-user-*`. Tus VMs reales no se tocan.

---

## Test A — Crear una VM Ubuntu desde la UI

1. Botón **«Crear máquina»**.
2. **Nombre:** `hgtest-user-ubuntu`. **ISO de arranque:** elige una ISO de
   Ubuntu con «Examinar».
   - **Esperar:** bajo la ISO aparece su tamaño. Si la ISO es rara, un aviso.
3. **Sistema operativo:** «Linux / Ubuntu (recomendado)».
4. Siguiente → **RAM 2048 MiB**, **2 vCPU**, **disco 15 GiB** (o más).
5. Siguiente → red/almacenamiento por defecto → **Crear**.
   - **Esperar:** la VM aparece en la lista en estado APAGADA.
6. Selecciónala → **«Encender»** → **«Abrir consola»**.
   - **Esperar:** la consola VNC muestra el arranque del instalador de Ubuntu.
     Si tarda o se ve negra, mira `docs/setup/UBUNTU_VMS.md` (troubleshooting).
   - El estado de la VM en la barra debe decir ENCENDIDA.

**PASS si:** la VM se crea, enciende y la consola muestra el instalador.
**Si falla:** apaga a la fuerza (no borres), anota qué mostraba la consola y
RAM/disco. No es necesario completar la instalación para el UAT.

---

## Test B — Windows 11 desde la UI (o error humano si faltan dependencias)

1. **«Crear máquina»** → Nombre `hgtest-user-win11` → ISO de Windows 11.
2. **Sistema operativo:** «Windows 11 (UEFI + Secure Boot + TPM 2.0)».
   - **Esperar (si faltan ovmf/swtpm):** bajo la ISO aparece un aviso claro:
     «… necesita firmware UEFI (OVMF) / TPM 2.0 (swtpm)…» con el comando
     `sudo apt install ovmf` / `sudo apt install swtpm swtpm-tools`.
3. Intenta **Crear**.
   - **Si faltan dependencias:** la creación se **rechaza** con ese mensaje
     humano (no crea una VM Windows 11 incompatible a escondidas). Instala lo
     que diga (terminal, una vez) y reintenta.
   - **Si están instaladas:** la VM se crea con UEFI + Secure Boot + TPM 2.0.
     Enciéndela y abre la consola: el instalador de Windows 11 **ya no se queja**
     de «TPM 2.0» ni de «arranque seguro».

**PASS si:** o bien se crea una VM Windows 11 que el instalador acepta, o bien
HyperGery la rechaza con el aviso humano y el comando (nunca una VM silenciosa
incompatible).

**Verificación secundaria (opcional, terminal):**
`virsh dumpxml hgtest-user-win11 | grep -E 'loader|tpm|smm'` → debe verse
`loader … secure='yes'`, `<tpm>` versión 2.0 y `<smm state='on'>`.

---

## Test C — Hub Docker del NAS conectado (desde la UI)

1. Menú **Centro de control** (o el asistente de primera ejecución si es la
   primera vez) → comprueba el estado del Hub.
   - **Esperar:** el Hub `http://192.168.1.150:8765` figura conectado/sano.
2. Si es primera ejecución: **«Salud del sistema»** muestra los equipos.

**PASS si:** la UI indica el Hub conectado.
**Diagnóstico secundario:** `hypergery-cli hub health --hub-url …` → `{"ok": true}`.

---

## Test D — PC y portátil online (desde la UI)

1. Arranca el agente en cada equipo (en el portátil, su servicio/agent).
2. En la UI, **Centro de control → «Salud del sistema»** (o la pestaña de
   equipos): **PC y portátil aparecen CONECTADOS**, con RAM/última señal.

**PASS si:** ambos equipos salen «conectados» en la UI.

---

## Test E — Migrar por el Hub desde la UI (flujo OFICIAL)

1. Crea/usa una VM **apagada** `hgtest-user-hub`.
2. Selecciónala → botón **«Mover a otro equipo»**.
3. En el asistente: **Equipo destino** = el portátil (detectado por el Hub) →
   **Forma de envío = «Por el Hub … (oficial)»** → Opciones (nombre destino) →
   **«Comprobar antes de empezar»**.
   - **Esperar:** la comprobación pasa (destino online, KVM/libvirt OK).
4. **«Empezar el traslado»**.
   - **Esperar:** aparece el **ID del traslado (migration_id)** y la lista de
     estados avanza: `preflight → packaging → uploaded → waiting_target →
     importing → defining_vm → done` (se actualiza solo).
5. Pantalla de **Resultado:** «Traslado completado», la máquina original **no se
   ha tocado**, en destino se importó con UUID/MAC nuevos.

**PASS si:** llega a `done`, muestra migration_id y estados, y dice que el
origen queda intacto (source_will_be_deleted=false).

---

## Test F — Migrar una VM ENCENDIDA desde la UI (modo avanzado)

> Único modo que mantiene la VM encendida. Necesita SSH directo PC→portátil y
> (para CPU AMD↔Intel) una VM de prueba con CPU compatible — usa `hgtest-user-live`.

1. Ten `hgtest-user-live` **ENCENDIDA** (Test A pero arrancada).
2. Selecciónala → **«Mover a otro equipo»** → **Forma de envío =
   «Migración en vivo — VM ENCENDIDA, modo avanzado»**.
   - El campo **«Destino en vivo (URI)»** se rellena solo desde el Hub
     (`qemu+ssh://…/system`); ajústalo si hace falta.
3. **«Comprobar antes de empezar».**
   - **Esperar:** si la VM estuviera apagada o la URI fuera insegura
     (`qemu+tcp`), lo **rechaza** con mensaje claro. Con VM encendida + URI
     `qemu+ssh`, pasa.
4. **«Empezar el traslado».**
   - **Esperar:** Resultado «Migración en vivo completada», con **downtime
     medido en ms**, destino ENCENDIDO y origen ya no corriendo.

**PASS si:** resultado OK con downtime_ms, destino encendido, origen detenido,
sin doble-activa. **Si falla:** el origen queda corriendo e intacto (rollback);
anota el error mostrado.

> **Honesto:** el flujo E (Hub) **no** mantiene la VM continuamente encendida
> (empaqueta/importa); el flujo F **sí** (downtime ~0,15 s en pruebas).

---

## Test G — Las VMs reales NO se tocan

Tras A–F, en la lista de máquinas de la UI (y en el portátil) tus VMs reales
siguen presentes y en su estado original. Diagnóstico secundario:
`virsh list --all` en ambos equipos.

**PASS si:** ninguna VM real cambió de estado ni desapareció.

---

## Limpieza (solo hgtest-user-*)

Desde la UI: selecciona cada `hgtest-user-*` → «Apagar a la fuerza» → «Eliminar»
(con confirmación, borrando disco). En el portátil, igual con la copia importada.

---

## Checklist PASS/FAIL para Gerard

| # | Prueba (desde la UI) | PASS / FAIL | Notas |
|---|---|---|---|
| A | Crear + arrancar Ubuntu; consola muestra instalador | ☐ / ☐ | |
| B | Windows 11: se crea válida **o** error humano con comando | ☐ / ☐ | |
| C | Hub Docker NAS conectado en la UI | ☐ / ☐ | |
| D | PC y portátil «conectados» en la UI | ☐ / ☐ | |
| E | Migración por Hub: migration_id + estados → done, origen intacto | ☐ / ☐ | |
| F | Migración en vivo: downtime_ms, destino encendido, origen no | ☐ / ☐ | downtime: ____ |
| G | VMs reales intactas | ☐ / ☐ | |

**Veredicto de Gerard:**
- ☐ Todo PASS → autorizo publicar v1.5.0 (tag/release los hace Gerard a mano).
- ☐ Algún FAIL → NO publicar; anotar y reportar.

> Recordatorio: este documento no publica nada. El tag/merge/release los decide
> y ejecuta Gerard después de este UAT.
