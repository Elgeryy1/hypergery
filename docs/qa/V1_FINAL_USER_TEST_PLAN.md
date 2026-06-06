# Plan final de pruebas de usuario — HyperGery v1.0

**Objetivo:** validar como usuario final que HyperGery está listo para publicar v1.0 final.
**Rama bajo prueba:** `feature/v1.1-ux` (UI humanizada + consola traducida). **NO** el tag `v1.0-rc1`.
**Resultado:** se rellena en `docs/qa/V1_FINAL_USER_TEST_RESULT.md`.

## Entorno

| Rol | Equipo | Detalle |
|---|---|---|
| PC sobremesa | `gerard-MS-7E26` | usuario `gerard`, venv `~/.venvs/hypergery` |
| Portátil | `gery-Lenovo-ideapad-330S-14IKB` (192.168.1.73) | usuario `gery`, venv `/home/gery/.venvs/hypergery` |
| Hub | NAS ALPO, contenedor `hypergery-hub` | `http://192.168.1.150:8765` |
| NAS staging (PC) | `/home/gerard/NAS_Gerard/hypergery/migrations` | vía fstab |
| NAS staging (portátil) | `/mnt/hypergery-nas/hypergery/migrations` | |

> **Importante:** los dos equipos cargan el código **del mismo working tree en el NAS**. La rama que esté
> checked-out en el PC es la que ejecuta también el portátil. No cambies de rama a mitad de prueba.

### Criterios de resultado

- **PASS** — se ve lo esperado, sin sorpresas.
- **FAIL** — algo no funciona o se ve mal, pero la app sigue usable y no hay pérdida de datos.
- **BLOCKER** — pérdida/corrupción de datos, traceback en pantalla, acción destructiva sin confirmación, app inutilizable, o cualquier cosa que no publicarías jamás.
- **SKIP** — no probado (anota por qué).

Capturas: guárdalas en `docs/qa/evidence/` con nombre `NN-descripcion.png` (NN = número de captura obligatoria, ver lista al final).

---

## Bloque A — Preparación (sin abrir la app todavía)

Todo este bloque es en terminal. Si algo falla aquí, **no sigas**: arregla el entorno primero.

**A1. Rama correcta** — en el PC:
```bash
cd ~/NAS_Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox
git status --short && git log --oneline -1
```
✔ Esperado: rama `feature/v1.1-ux`, working tree limpio (puede aparecer `USER_ACCEPTANCE_TEST_V1_RC1.md` sin trackear), último commit `ui: unify host key label wording` o posterior.

**A2. Versión** — en el PC:
```bash
~/.venvs/hypergery/bin/python -c "from hypergery_ubuntu import __version__; print(__version__)"
```
✔ Esperado: `1.0.0rc1`.

**A3. Hub vivo:**
```bash
curl -s http://192.168.1.150:8765/health
```
✔ Esperado: `{"ok": true}`. ✘ BLOCKER si no responde.

**A4. Agentes registrados y al día:**
```bash
curl -s http://192.168.1.150:8765/hosts | python3 -c "import json,sys; [print(h['host_id'], h['hypergery_version'], h['status'], h['last_seen']) for h in json.load(sys.stdin)['hosts']]"
```
✔ Esperado: los **dos** hosts `online`, versión `1.0.0rc1`, `last_seen` de hace menos de ~1 minuto.
✘ FAIL si un agente está caído (arráncalo con `setsid nohup .../bin/python -m hypergery_ubuntu.cli agent run >> ~/.local/share/hypergery-agent.log 2>&1 &`).

**A5. NAS staging escribible** — incluido en doctor (A6).

**A6. Doctor en ambos equipos:**
```bash
# PC
~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli doctor
# Portátil (desde el PC)
ssh gery@192.168.1.73 '/home/gery/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli doctor'
```
✔ Esperado: **todo OK** en ambos, sin ningún FAIL. ✘ Un FAIL aquí bloquea el bloque al que afecte (NAS → F, Hub → B/G).

---

## Bloque B — App abierta en ambos equipos a la vez

**B1. Abrir en el PC primero:**
```bash
~/.venvs/hypergery/bin/hypergery
```
Qué mirar al arrancar: título de ventana con "1.0-rc1", barra lateral con secciones **Inicio, Máquinas virtuales, Laboratorios, Plantillas, Otros equipos, Migraciones, Tareas remotas, Centro de control, Diagnóstico, Ajustes**. Chips superiores: "Hub: en línea" y "NAS: …".

**B2. Abrir en el portátil** (en su pantalla, no por SSH):
```bash
/home/gery/.venvs/hypergery/bin/hypergery
```
Mismo aspecto que en el PC.

**B3. Coherencia entre las dos UIs** — con ambas abiertas, en cada una ve a **Otros equipos**:
- ✔ Los dos hosts aparecen **en línea** en ambas apps.
- ✔ En "Máquinas virtuales": el PC lista sus 3 VMs (`hg-v06-2host-source`, `hg-v06-e2e-source`, `ubuntu`); el portátil las suyas.
- ✔ Los totales del Hub (máquinas registradas) coinciden en ambas.
- ✘ FAIL si una app ve al otro host offline estando su agente vivo.

**B4. Prueba "sin manual":** durante 2 minutos navega como si no conocieras la app. Anota cualquier pantalla en la que no sabrías qué hacer. Eso va a la sección de humanización (bloque D).

---

## Bloque C — Revisión visual completa (en el PC; repite rápido en el portátil)

Recorre cada sección de la barra lateral, **de arriba abajo**. En cada una: lee todos los textos, pasa el ratón por los botones (tooltips), y NO toques todavía botones rojos.

| Pantalla | Qué mirar | Qué NO tocar |
|---|---|---|
| **Inicio** (dashboard) | tarjetas de salud (Hub/NAS/VMs/equipos), última migración, avisos | — |
| **Máquinas virtuales** | tabla con estados en español (ENCENDIDA/APAGADA/EN PAUSA), pestañas de detalle (General/Sistema/Consola/Almacenamiento/Red/Instantáneas/Registros) | **Borrar** y **Apagar a la fuerza** (botones rojos) |
| **Laboratorios** | lista de labs, topología | botones de borrado |
| **Plantillas** | lista legible | instanciar (todavía no) |
| **Otros equipos** | tarjetas de ambos hosts con badges online/CPU/RAM | — |
| **Migraciones** | historial, asistente "Mover a otro equipo" (solo abrir y cancelar) | no lanzar migración aún |
| **Tareas remotas** | órdenes vía Hub, solo consulta | no encolar nada |
| **Centro de control** | pestañas: Mi equipo, Sugerencias, Batería, Copias en el NAS, Redes, Usuarios, Equipos externos, Historial | — |
| **Diagnóstico** | el doctor integrado, todo OK | — |
| **Ajustes** | Hub/NAS/valores por defecto correctos; el callout de la consola dice "Ctrl derecho" | no guardar cambios |

Diálogos de confirmación: abre el diálogo de **Borrar** una VM de prueba y **CANCELA**. ✔ El texto debe dejar claro qué se va a borrar y debe existir cancelación obvia. ✘ BLOCKER si algún botón destructivo actúa sin confirmar.

---

## Bloque D — Idioma y humanización

Durante todo el recorrido de C, anota en la plantilla de resultados:

1. **Inglés visible** — cualquier texto en inglés en pantallas, botones, tooltips, mensajes de estado. (Los nombres técnicos VNC, SPICE, RAM, vCPU, KVM, Hub, NAS están permitidos.)
2. **Demasiado técnico** — textos que una persona normal no entendería ("qemu:///system" fuera de zonas técnicas, jerga libvirt sin explicar).
3. **JSON crudo** — JSON sin formato fuera del Centro de control/Diagnóstico (zonas técnicas permitidas).
4. **Botones confusos** — etiquetas que no dicen lo que hacen.
5. **Errores sin remedio** — fuerza un error suave (p. ej. conectar consola con la VM apagada) y comprueba que el mensaje dice **qué hacer**, no solo qué falló.

✔ PASS del bloque: cero inglés visible y cero errores "mudos". Lo técnico/confuso se anota con severidad para v1.0.1 o v1.1.

---

## Bloque E — Flujo de usuario normal (en el PC)

1. **Ver un lab:** Laboratorios → `default-lab` → ✔ se ven sus VMs y topología.
2. **Ver una VM:** Máquinas virtuales → `ubuntu` → ✔ pestañas de detalle con datos reales (disco, RAM, red).
3. **Encender y abrir consola:** selecciona `ubuntu` → **Iniciar** → espera ENCENDIDA → **Consola** → ✔ ventana "Consola HyperGery - ubuntu" con toolbar en español (Conectar/Desconectar/Reconectar/Enviar Ctrl+Alt+Supr/Soltar teclado/ratón/Pantalla completa/Ajustar a la ventana/Cerrar). Conecta, haz clic dentro (✔ "Teclado y ratón capturados…"), pulsa **Ctrl derecho** (✔ "Teclado y ratón liberados").
4. **Cerrar sin romper:** cierra la ventana de la consola → ✔ la VM **sigue encendida** (✘ BLOCKER si se apaga). Después **Apagar (suave)** → ✔ pasa a APAGADA sola.
5. **Logs:** pestaña Registros de la VM y Centro de control → Historial → ✔ legibles, con las acciones que acabas de hacer.
6. **Estado solo:** con la app del PC visible, enciende una VM **desde el portátil** → ✔ el cambio aparece en el PC sin tocar nada (puede tardar unos segundos de polling).

---

## Bloque F — NAS (commit y restore)

En el PC, terminal:

1. **Dry-run (no escribe nada):**
   ```bash
   ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run
   ```
   ✔ Muestra qué escribiría, sin tocar el NAS.
2. **Commit real (lab seguro, sin discos):**
   ```bash
   ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --confirm
   ```
   ✔ Devuelve `commit_id` nuevo. Apúntalo.
3. **Restore a /tmp (nunca a la ruta real):**
   ```bash
   ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 nas restore --lab default-lab --commit-id <COMMIT_ID> --destination /tmp/hg-restore-test --confirm
   ```
   ✔ Restaura y reporta `verified: true`. ✘ BLOCKER si `verified: false`.
4. **No sobrescribe:** repite el mismo restore al mismo destino → ✔ se niega o avisa; ✘ BLOCKER si machaca sin avisar.
5. Limpieza: `rm -rf /tmp/hg-restore-test`. En la UI: Centro de control → Copias en el NAS → ✔ aparece el commit.

---

## Bloque G — Teleport PC → portátil

**Antes:** apunta el UUID y MAC de la VM origen: `virsh dominfo ubuntu | grep UUID` y `virsh domiflist ubuntu`.

1. **Dry-run:**
   ```bash
   ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 teleport dry-run --vm ubuntu --target gery-Lenovo-ideapad-330S-14IKB --no-iso
   ```
   ✔ `ok: true`, preflight limpio, tamaño estimado razonable.
2. **Loopback (sale y entra en el PC):**
   ```bash
   ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 teleport loopback --vm ubuntu --no-iso
   ```
   ✔ Termina OK y la copia loopback se ve en `list-vms`. Borra la copia desde la UI al acabar.
3. **Host→host real desde la UI:** Máquinas virtuales → selecciona `ubuntu` (APAGADA) → **Mover a otro equipo** → destino el portátil → sigue el asistente (captura el preflight) → confirma.
   ✔ Barra de progreso, sin congelar la UI, resultado claro al acabar.
4. **Origen intacto:** en el PC, ✔ `ubuntu` sigue existiendo y arranca.
5. **Destino correcto:** en el portátil, ✔ existe la VM trasladada, **arranca**, y `virsh dominfo`/`domiflist` muestran **UUID y MAC distintos** del origen. ✘ BLOCKER si comparten UUID/MAC.
6. **Staging limpio:** ✔ no quedan restos de la transferencia en el staging del Hub/NAS (`ls` del staging antes/después).
7. Limpieza: borra la copia del portátil desde su UI (con confirmación).

---

## Bloque H — Errores controlados

El criterio general: **mensaje claro en español, que diga qué hacer, sin traceback, sin acciones a medias.** Captura el mejor ejemplo (captura obligatoria 09).

1. **Agente del portátil caído:** en el portátil `pkill -f "[c]li agent run"` → en la app del PC: Otros equipos → ✔ pasa a fuera de línea/última conexión; intenta "Mover a otro equipo" hacia él → ✔ error claro, no cuelgue. Rearranca el agente al acabar.
2. **Hub no disponible:** para el contenedor (`ssh Gery@192.168.1.150` + docker stop) **o** desconecta red. ✔ Chips "Hub: sin conexión", aviso en Inicio, la parte local sigue funcionando. Rearranca el Hub.
3. **NAS staging malo:** `HYPERGERY_NAS_STAGING_PATH=/ruta/que/no/existe ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run` → ✔ error legible, no traceback.
4. **Target offline:** teleport dry-run hacia el portátil con su agente parado → ✔ preflight lo detecta y lo dice.
5. **Destructivo sin confirmar:** intenta borrar una VM y cancela en el diálogo → ✔ no pasa nada. ✘ BLOCKER si algo se borra al cancelar.

---

## Bloque I — save_restore (teleport con estado)

⚠️ **La prueba más delicada.** Solo con la VM de prueba `ubuntu`, nunca con una VM con datos que importen. Es el rollback seguro ya validado en v1: si falla, la VM origen **se reanuda**.

1. Enciende `ubuntu` en el PC y deja algo visible en su consola (un `date` ejecutado, una ventana abierta).
2. ```bash
   ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 teleport save-restore --vm ubuntu --target gery-Lenovo-ideapad-330S-14IKB
   ```
3. ✔ Si va bien: la VM **continúa** en el portátil (misma sesión, se ve el `date` anterior — no es un reinicio).
4. ✔ Si falla (p. ej. por permisos `qemu:///system`): la VM origen **se reanuda sola** y el mensaje explica qué pasó en lenguaje normal. ✘ BLOCKER si la VM queda pausada/perdida en ambos lados.
5. **Honestidad:** comprueba que la UI/textos lo llaman "teleport con estado / save & restore" con su pausa visible — ✘ FAIL si algún texto lo vende como live migration sin corte.
6. Limpieza igual que en G.

---

## Bloque J — Veredicto

Rellena en `V1_FINAL_USER_TEST_RESULT.md`:

1. Tabla completa PASS/FAIL/BLOCKED/SKIP por prueba.
2. **Bloqueantes para v1 final** (cualquier BLOCKER, o FAIL en A, B, E, F3, G4–G5, H5, I4).
3. **Para v1.0.1** — fallos menores que no impiden publicar.
4. **Polish para v1.1** — humanización, textos, detalles visuales.
5. **Decisión: APTO / NO APTO** para publicar v1.0 final, con firma.

Regla de decisión: **APTO** = cero BLOCKER, cero FAIL en los bloques críticos listados en (2), y todos los FAIL restantes con plan asignado (v1.0.1 o v1.1).

---

## Capturas obligatorias (guardar en `docs/qa/evidence/`)

| Nº | Captura | Bloque |
|---|---|---|
| 01 | Dashboard (Inicio) en el PC | B1 |
| 02 | Dashboard (Inicio) en el portátil | B2 |
| 03 | Otros equipos con ambos hosts en línea | B3 |
| 04 | Centro de control (pestaña Mi equipo) | C |
| 05 | Consola integrada traducida, conectada a una VM | E3 |
| 06 | Preflight de "Mover a otro equipo" / teleport | G3 |
| 07 | Teleport completado (resultado en UI) | G3 |
| 08 | NAS restore con `verified: true` (terminal) | F3 |
| 09 | Error controlado sin traceback | H |
| 10 | Ajustes con estado de Hub/NAS | C |

## Orden recomendado y tiempos

- **Recorrido mínimo** (A → B → C rápido → E → F → G dry-run+UI): ~60–90 min.
- **Recorrido completo** (todos los bloques, con H e I): ~2,5–3,5 h, incluyendo transferencias reales (~5,4 GiB por teleport en red local) y capturas.
- Si solo tienes una sesión corta: haz A, B, E y G3–G5 — son los que deciden si v1 es publicable.
