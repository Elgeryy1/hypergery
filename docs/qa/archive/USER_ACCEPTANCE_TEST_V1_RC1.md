# USER_ACCEPTANCE_TEST_V1_RC1 — Plan de pruebas manual de usuario

**Objetivo**: validar la experiencia real de uso de HyperGery **v1.0-rc1** como
usuario (Gerard), no como desarrollador. El smoke automático/asistido ya pasó
(23 PASS · 0 FAIL · 1 BLOCKED · 1 SKIP — ver
[V1_MANUAL_SMOKE_RESULT.md](V1_MANUAL_SMOKE_RESULT.md)); esto cubre lo que el
smoke no cubre: **la GUI con sesión interactiva (el SKIP del smoke), la
usabilidad y la primera impresión**.

**Reglas durante el UAT**:
- No se arregla nada sobre la marcha. Solo se apunta.
- No se ejecuta nada con `--confirm` salvo donde este plan lo dice explícitamente.
- El origen de cualquier teleport/migración **nunca** se borra (es invariante
  del producto; si pasa, es bug bloqueante).
- Cualquier salida rara, traceback o mensaje confuso → a la sección NOTES y al
  bloque K.

**Convenciones**:
- `PY` = `~/.venvs/hypergery/bin/python` (exporta una vez: `PY=~/.venvs/hypergery/bin/python`)
- Sobremesa = `gerard-MS-7E26` (donde se ejecuta este UAT)
- Portátil = `gery-Lenovo-ideapad-330S-14IKB` (`ssh gery@192.168.1.73`)
- Hub = NAS QNAP "ALPO" `http://192.168.1.150:8765`
- NAS staging (ruta fiable, vía fstab): `HYPERGERY_NAS_STAGING_PATH=/home/gerard/NAS_Gerard/hypergery`
  (el bind `/mnt/hypergery-nas` NO es persistente — limitación conocida #3 de las release notes)

**Orden recomendado**: A → B → C → D → E → F → G → I → H → J → L.
(I antes que H para que las pruebas de error no dejen nada a medias antes del
save_restore; K es transversal, se rellena durante todo el recorrido.)

**Recorrido mínimo** (si hay poco tiempo): A → B → C → D1–D4 → F → G1–G2 → L.

---

## Resumen de tiempos

| Bloque | Contenido | Duración estimada |
| --- | --- | --- |
| A | Preparación | 20–30 min |
| B | Primera impresión | 10 min |
| C | Control Center / UI | 25 min |
| D | CLI v1 | 15 min |
| E | API v1 | 15 min |
| F | NAS commit/restore | 15 min |
| G | Teleport | 30–45 min |
| H | save_restore | 15 min |
| I | Casos de error | 25 min |
| J | Usuario normal | 20 min |
| K | Captura de evidencias | transversal |
| L | Criterio de aceptación | 10 min |
| **Total completo** | | **~3,5–4,5 h** |
| **Recorrido mínimo** | A+B+C+D parcial+F+G loopback+L | **~1,5–2 h** |

---

## A. Preparación (20–30 min)

> Objetivo: arrancar desde cero sobre el tag exacto de la release, con Hub,
> dos agentes y NAS verificados ANTES de tocar la app.

### A1 — Situarse en el tag v1.0-rc1

```bash
cd ~/NAS_Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox
git fetch --tags
git checkout v1.0-rc1
git status
```

**Esperado**: `HEAD detached at v1.0-rc1`, working tree limpio. Se prueba el
**tag**, no `develop` (el UAT valida lo publicado, no lo que venga después).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### A2 — Verificar versión instalada en el venv

```bash
PY=~/.venvs/hypergery/bin/python
$PY -c "import hypergery_ubuntu; print(hypergery_ubuntu.__version__)"
```

**Esperado**: `1.0.0rc1`. Si sale otra cosa, reinstalar editable antes de seguir:
`$PY -m pip install -e ./hypergery-ubuntu`.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### A3 — Hub vivo en el NAS

```bash
curl -s http://192.168.1.150:8765/health
curl -s http://192.168.1.150:8765/hosts
```

**Esperado**: `/health` → `{"ok": true}`. `/hosts` → JSON con los hosts
registrados. Si el Hub no responde: revisar Container Station en el NAS
(contenedor `hypergery-hub`), no continuar hasta que responda.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### A4 — Agente de la sobremesa

```bash
$PY -m hypergery_ubuntu.cli agent config show
# si no hay agente corriendo como servicio:
$PY -m hypergery_ubuntu.cli agent run   # dejar en una terminal aparte
# o instalarlo como servicio de usuario:
./scripts/install-agent-user-service.sh
```

**Esperado**: el agente arranca sin traceback y en <15 s la sobremesa aparece
`online` en `curl -s http://192.168.1.150:8765/hosts`.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### A5 — Agente del portátil

```bash
ssh gery@192.168.1.73 'setsid nohup ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli agent run >/tmp/hypergery-agent.log 2>&1 &'
sleep 20 && curl -s http://192.168.1.150:8765/hosts
```

**Esperado**: ambos hosts `online` en `/hosts`.
**Ojo**: si hay que matar el agente remoto, usar el patrón con corchete
(`pkill -f "[c]li agent run"`) — el patrón sin corchete mata la propia sesión SSH.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### A6 — NAS accesible para staging

```bash
export HYPERGERY_NAS_STAGING_PATH=/home/gerard/NAS_Gerard/hypergery
ls "$HYPERGERY_NAS_STAGING_PATH"
$PY -m hypergery_ubuntu.cli v1 nas status
```

**Esperado**: el directorio lista contenido (p. ej. `labs-commits/`,
`migrations/`) y `nas status` informa sano, con la lista de commits previos
(debería verse al menos `commit-2026-06-06T105937Z0000-83442881` del smoke).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### A7 — Doctor (chequeo global sin tocar nada)

```bash
$PY -m hypergery_ubuntu.cli doctor
```

**Esperado**: Python, KVM, libvirt, Hub, NAS staging OK. Apuntar cualquier
WARN aunque no bloquee.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

> **Gate del bloque A**: no pasar a B si A3 (Hub), A4 (agente local) o A6 (NAS)
> fallan. B–C pueden hacerse sin el portátil; G (host→host) no.

---

## B. Primera impresión de la app (10 min)

> Objetivo: medir la experiencia "abro la app después de meses" (no la usas
> desde v0.8). Hazlo SIN releer documentación primero — eso es parte de la prueba.

### B1 — Abrir la app

```bash
./scripts/dev-run.sh
# o directamente: $PY -m hypergery_ubuntu
```

**Esperado**: la app abre sin errores en consola ni diálogos de fallo.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### B2 — Versión visible

**Acción**: localizar dónde la app muestra su versión (título de ventana,
About, dashboard…).

**Esperado**: se lee `v1.0-rc1` en algún sitio visible sin buscar mucho.
Si no se encuentra en <1 min → FAIL de UX (candidato v1.1).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### B3 — Mapa mental en 3 minutos

**Acción**: sin tocar docs, intenta responder mirando solo la sidebar y el
dashboard:

1. ¿Dónde veo mis hosts? → ______________________
2. ¿Dónde veo mis labs? → ______________________
3. ¿Dónde veo mis VMs (locales y remotas)? → ______________________
4. ¿Dónde veo el estado del NAS/Hub? → ______________________
5. ¿Desde dónde lanzaría un teleport/migración? → ______________________
6. ¿Dónde están los logs? → ______________________

**Esperado**: respondes 5 de 6 sin dudar. Cada una que no encuentres en
<1 min, apúntala como hallazgo UX (bloque K).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### B4 — Cosas confusas

**Acción**: apunta literalmente cualquier cosa que te haya hecho dudar en los
primeros 10 minutos (nombres de menú, iconos, orden de la sidebar, textos en
inglés/español mezclados…). No filtres: todo vale para v1.1.

**Notas**: ______________________

---

## C. Control Center / UI (25 min)

> Objetivo: cubrir el SKIP del smoke (test 24): el Control Center y la
> navegación general con sesión gráfica real. Recuerda: que el Control Center
> muestre **JSON crudo es limitación conocida** (V1_KNOWN_BUGS #1, prevista
> para v1.1) — apunta DÓNDE molesta más, pero no es FAIL por sí mismo.

### C1 — Recorrido completo de la sidebar

**Acción**: visitar una a una todas las páginas (Dashboard, VMs, Labs,
Remote Hosts, Migrations, Commands, Control Center, Diagnostics, Settings).

**Esperado**: ninguna página casca, queda en blanco ni se queda "cargando"
para siempre. Apuntar tiempos de carga molestos (>3 s).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### C2 — Control Center: las 8 tabs

**Acción**: abrir Control Center y pasar por las 8 tabs (health, hosts,
telemetry, battery, labs, network, orchestrator, guests…), con el Hub online.

**Esperado**:
- Cada tab carga datos reales (los 2 hosts, telemetría con números plausibles).
- Ninguna tab lanza traceback ni congela la UI.
- El botón **Export Report** genera el informe y dice dónde lo deja.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### C3 — Estados online/offline en Remote Hosts

**Acción**: página Remote Hosts con ambos agentes vivos.

**Esperado**: 2 hosts `online`, last-seen reciente, RAM/disco reales,
KVM/libvirt ready, URL del Hub y estado del Hub visibles, contador de VMs.
(El rol `unknown` del portátil es cosmético conocido — apuntar, no FAIL.)

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### C4 — Botones principales sin ejecutar nada destructivo

**Acción**: en VMs/Labs/Migrations, abrir (y CANCELAR) los diálogos
principales: Live Migration, Start Lab / Shutdown Lab, View VMs de un host
remoto, Resources…, Hub Staging Maintenance (solo dry-run).

**Esperado**: todos los diálogos abren, los destructivos piden confirmación
explícita, y **Cancelar** siempre deja todo como estaba.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### C5 — Errores visibles y mensajes feos

**Acción**: durante todo el bloque, cazar: JSON crudo fuera del Control
Center, tracebacks de Python en diálogos, mensajes de error sin acción clara
("Error: None"), textos cortados.

**Esperado**: fuera del Control Center no debería aparecer JSON crudo. Cada
hallazgo → lista en K con pantalla y captura.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### C6 — ¿Se puede usar sin mirar la documentación cada 2 minutos?

**Pregunta de juicio** (responder honesto al final del bloque):
- ¿Cuántas veces has tenido que abrir un .md para entender una pantalla? ____
- ¿Qué pantalla es la peor en esto? ______________________

**Esperado**: ≤2 consultas a docs en todo el bloque C.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

---

## D. CLI v1 (15 min)

> Todos estos comandos son de solo lectura — sin riesgo. Ejecutar en la
> sobremesa con el export de A6 activo.

### D1 — Salud y registro de hosts

```bash
$PY -m hypergery_ubuntu.cli v1 health
$PY -m hypergery_ubuntu.cli v1 hosts
```

**Esperado**: `health` → hosts online + NAS + batería (en la sobremesa la
batería degrada limpia a `unavailable`, sin traceback — es lo correcto).
`hosts` → 2 hosts con roles y RAM real.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### D2 — Telemetría y batería

```bash
$PY -m hypergery_ubuntu.cli v1 telemetry
$PY -m hypergery_ubuntu.cli v1 battery
# y la batería REAL en el portátil:
ssh gery@192.168.1.73 '~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli v1 battery'
```

**Esperado**: CPU/RAM/disco plausibles y `alerts: []` (o alertas con sentido).
En el portátil: porcentaje real, tier coherente (≥50% → `normal`), acciones
recomendadas coherentes con el tier.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### D3 — Validadores de labs y red

```bash
$PY -m hypergery_ubuntu.cli v1 labs validate
$PY -m hypergery_ubuntu.cli v1 network validate
```

**Esperado**: AMBOS deben seguir detectando el conflicto real preexistente:
labs `hg-v03-par` e `importar` comparten `192.168.197.0/24`. Si ya
reasignaste esa subred, esperado = sin conflictos. Lo importante: salida
coherente entre los dos comandos y comprensible sin leer código.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### D4 — Orchestrator y RBAC

```bash
$PY -m hypergery_ubuntu.cli v1 orchestrator plan
$PY -m hypergery_ubuntu.cli v1 guests list
```

**Esperado**: planes explicables (razón, battery_tier, confidence) sobre los
hosts/VMs reales; **nunca ejecuta nada**. `guests list` → `{"users": []}` si
no has creado usuarios, sin traceback.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### D5 — Comandos que NO tocar en este UAT

Lista de exclusión (peligrosos o fuera de alcance — no ejecutar):

| Comando | Por qué no |
| --- | --- |
| `hub cleanup-staging --confirm` | borra staging real; solo dry-run en este UAT |
| `v1 api serve --allow-remote` / `--host 0.0.0.0` | expone la API sin auth fuera de loopback |
| `v1 teleport save-restore --target <host remoto>` fuera del bloque H | cross-host está BLOCKED en `qemu:///system`; solo se prueba el rollback controlado en H |
| Borrar VMs/labs/templates (`delete`/`undefine`) salvo limpieza marcada en G/J | el UAT no debe destruir datos preexistentes |
| `virsh` directo contra VMs preexistentes | saltarse la app invalida la prueba |
| `migrate remote` con VMs preexistentes que no sean de prueba | usa solo las VM designadas en G |

**Confirmado leído**: ☐

---

## E. API v1 básica (15 min)

### E1 — Levantar la API (solo loopback)

```bash
$PY -m hypergery_ubuntu.cli v1 api serve &
sleep 2 && curl -s http://127.0.0.1:8799/health
```

**Esperado**: envelope estable
`{"ok": true, "data": …, "error": null, "timestamp": …, "api_version": "v1"}`.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### E2 — GETs principales

```bash
curl -s http://127.0.0.1:8799/hosts
curl -s http://127.0.0.1:8799/battery
curl -s http://127.0.0.1:8799/telemetry
curl -s http://127.0.0.1:8799/nas/status
curl -s http://127.0.0.1:8799/orchestrator/plan
curl -s http://127.0.0.1:8799/labs
curl -s http://127.0.0.1:8799/vms
```

**Esperado**: todos con `"ok": true` y datos coherentes con lo visto en D
(2 hosts, mismos planes del orchestrator, commits del NAS listados).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### E3 — Errores esperados (la API debe fallar BIEN)

```bash
# endpoint inexistente:
curl -s http://127.0.0.1:8799/no-existe
# host inexistente:
curl -s http://127.0.0.1:8799/hosts/no-such-host
```

**Esperado**: JSON de error con envelope (`"ok": false`, `error.code`,
`error.message` legible) — nunca HTML, nunca traceback.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### E4 — Confirm guard de /teleport/start

```bash
# SIN confirm → debe ser rechazado sin hacer NADA:
curl -s -X POST http://127.0.0.1:8799/teleport/start \
  -H 'Content-Type: application/json' \
  -d '{"vm_name": "cualquiera", "mode": "dry_run", "target_host_id": ""}'
```

**Esperado**: rechazo con error claro pidiendo `"confirm": true`. Ninguna VM
se toca. (NO repetir con `confirm: true` — el teleport real se hace en G por CLI.)

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### E5 — Apagar la API

```bash
kill %1   # o el PID del api serve
```

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

---

## F. NAS commit/restore (15 min)

> Seguro por diseño: commit solo escribe metadatos del lab en el NAS, restore
> escribe en un destino nuevo y **nunca sobreescribe**. Aun así: dry-run primero, siempre.

### F1 — Dry-run del commit

```bash
export HYPERGERY_NAS_STAGING_PATH=/home/gerard/NAS_Gerard/hypergery
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run
```

**Esperado**: plan con `lab_manifest.json`, tamaño en bytes, `dry_run: true`.
Nada escrito en el NAS todavía (comprobar que no aparece commit nuevo en
`ls "$HYPERGERY_NAS_STAGING_PATH/labs-commits/default-lab/"`).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### F2 — Commit real

```bash
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --confirm
ls "$HYPERGERY_NAS_STAGING_PATH/labs-commits/default-lab/"
```

**Esperado**: nuevo `commit-<timestamp>-<id>` con `verified: true` en la
salida. En el directorio: el paquete del commit con manifest y checksums.
**Apuntar el commit-id**: ______________________

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### F3 — Restore a destino limpio

```bash
$PY -m hypergery_ubuntu.cli v1 nas restore --lab default-lab \
  --commit-id <COMMIT_ID_DE_F2> \
  --destination /tmp/hg-uat-restore --confirm
ls -la /tmp/hg-uat-restore
```

**Esperado**: restore con hash validado, `verified: true`, archivos en
`/tmp/hg-uat-restore`. **Nada vivo tocado**: el lab original sigue idéntico.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### F4 — Verificar checksums a mano (confianza extra)

```bash
# comparar el hash real del manifest restaurado con el del paquete:
sha256sum /tmp/hg-uat-restore/lab_manifest.json
grep -r sha256 "$HYPERGERY_NAS_STAGING_PATH/labs-commits/default-lab/<COMMIT_ID_DE_F2>/" | head -5
```

**Esperado**: el SHA-256 calculado coincide con el registrado en el paquete.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### F5 — Restore NO sobreescribe

```bash
# repetir el restore al MISMO destino ya poblado:
$PY -m hypergery_ubuntu.cli v1 nas restore --lab default-lab \
  --commit-id <COMMIT_ID_DE_F2> \
  --destination /tmp/hg-uat-restore --confirm
```

**Esperado**: error claro negándose a sobreescribir (o equivalente seguro).
Si sobreescribe en silencio → **FAIL bloqueante**.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

Limpieza: `rm -rf /tmp/hg-uat-restore` (solo el tmp; el commit del NAS se queda como evidencia).

---

## G. Teleport (30–45 min)

> La VM de pruebas designada es `hg-v06-2host-source` (sobremesa). Su ISO
> adjunta vive bajo `/mnt/hypergery-nas/...` (bind no persistente) → usar
> `--no-iso`, igual que en el smoke. El origen NUNCA debe quedar dañado.

### G1 — Dry-run hacia el portátil

```bash
$PY -m hypergery_ubuntu.cli v1 teleport dry-run \
  --vm hg-v06-2host-source \
  --target gery-Lenovo-ideapad-330S-14IKB --no-iso
```

**Esperado**: preflight OK, target online comprobado,
`source_will_be_deleted: false`, y NADA copiado.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### G2 — Loopback real (mismo host)

```bash
$PY -m hypergery_ubuntu.cli v1 teleport loopback \
  --vm hg-v06-2host-source \
  --staging-dir /tmp/hg-uat-teleport --no-iso
virsh list --all | grep -i loopback
virsh domuuid hg-v06-2host-source
virsh domuuid hg-v06-2host-source-loopback
```

**Esperado**: aparece `hg-v06-2host-source-loopback` con **UUID distinto** al
origen; el origen sigue definido, con su disco intacto.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### G3 — Host→host real (sobremesa → portátil), ambos hosts disponibles

El CLI `v1 teleport` no expone `suspend_copy_start` host→host; el camino de
usuario es el wizard **Live Migration** de la app (recomendado para el UAT,
porque además prueba la UI) o el CLI clásico:

```bash
# Opción A (recomendada): app → VM hg-v06-2host-source → Live Migration
#   → target el Lenovo → transfer Hub → SIN ISO → preflight → ejecutar.
# Opción B (CLI):
$PY -m hypergery_ubuntu.cli migrate remote hg-v06-2host-source \
  --transfer hub \
  --source-host-id gerard-MS-7E26 \
  --target-host-id gery-Lenovo-ideapad-330S-14IKB \
  --target-vm-name hg-uat-teleport --no-iso
$PY -m hypergery_ubuntu.cli migrate status --migration-id <id devuelto>
```

**Esperado**: migración → `done` (en el smoke tardó ~80 s con este tamaño).

**Qué mirar en ORIGEN (sobremesa)**:
```bash
virsh list --all | grep hg-v06-2host-source
virsh domuuid hg-v06-2host-source
ls -la ~/.local/share/hypergery/vms/ | grep -i 2host
```
Esperado: VM definida, mismo UUID de siempre, disco intacto.
⚠️ Si el flujo usó suspend: el origen puede quedar `paused` **a propósito**
(decisión de seguridad documentada, V1_KNOWN_BUGS #4) → `virsh resume
hg-v06-2host-source` tras verificar el destino. Apuntar si el mensaje te lo
explicó o lo tuviste que saber tú (hallazgo UX).

**Qué mirar en DESTINO (portátil)**:
```bash
ssh gery@192.168.1.73 'virsh list --all | grep hg-uat-teleport'
ssh gery@192.168.1.73 'virsh domuuid hg-uat-teleport'
ssh gery@192.168.1.73 'virsh domiflist hg-uat-teleport'
```
Esperado: VM `running`, **UUID nuevo** (≠ origen), **MAC nueva**.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### G4 — Hub staging limpio tras el import

```bash
curl -s http://192.168.1.150:8765/packages
# o: $PY -m hypergery_ubuntu.cli hub packages
```

**Esperado**: 0 paquetes (el target borra su copia y la del Hub tras importar).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### G5 — Limpieza de artefactos del bloque G

```bash
# loopback en la sobremesa:
virsh destroy hg-v06-2host-source-loopback 2>/dev/null; virsh undefine hg-v06-2host-source-loopback --remove-all-storage
# VM teleportada en el portátil:
ssh gery@192.168.1.73 'virsh destroy hg-uat-teleport 2>/dev/null; virsh undefine hg-uat-teleport --remove-all-storage'
rm -rf /tmp/hg-uat-teleport
# verificar que los ORIGINALES siguen:
virsh list --all
```

**Esperado**: solo desaparecen los artefactos del UAT; `hg-v06-2host-source`,
`hg-v06-e2e-source` y `ubuntu` siguen en la sobremesa.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

---

## H. save_restore (15 min)

> **Qué es**: teleport con estado — congela la VM (`virsh save`, RAM+CPU),
> envía disco+estado y el destino la **restaura donde estaba** (no reinicia).
> **Qué NO es**: live migration con cero downtime. La VM está offline durante
> la transferencia. No venderlo como live migration completa.
>
> **Qué SÍ puedes probar hoy**: el mecanismo y el **rollback seguro** en local.
> **Qué está BLOCKED**: el envío cross-host en `qemu:///system` (el setup
> actual): el fichero de estado que escribe libvirt es root-owned y el proceso
> origen no puede leerlo para subirlo. Necesitaría `qemu:///session`, storage
> compartido o un ACL — documentado en docs/API_V1.md y release notes (#1).
> **No es un bug de esta release**: es el BLOCKED conocido del smoke (test 22).

### H1 — Rollback seguro con VM encendida (la prueba que SÍ aplica)

Usar una VM de prueba que puedas permitirte pausar 1 minuto
(`hg-v06-e2e-source`, como en el smoke):

```bash
virsh start hg-v06-e2e-source   # si no está running
$PY -m hypergery_ubuntu.cli v1 teleport save-restore \
  --vm hg-v06-e2e-source \
  --target gery-Lenovo-ideapad-330S-14IKB
virsh list --all | grep hg-v06-e2e-source
```

**Esperado** (en este entorno `qemu:///system`):
1. La VM se congela (save real).
2. El engine detecta el fichero de estado ilegible.
3. **Reanuda la VM localmente** → vuelve a `running`.
4. Devuelve un error claro y accionable (que mencione el porqué y las
   alternativas), no un traceback.

**FAIL bloqueante si**: la VM queda parada/guardada sin reanudar, o el error
no explica nada.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### H2 — Verificar que no quedó basura

```bash
virsh list --all
ls /tmp | grep -i hg- ; ls ~/.local/share/hypergery/ | grep -i teleport
curl -s http://192.168.1.150:8765/packages
```

**Esperado**: VM `running`, sin staging huérfano local ni en el Hub.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### H3 — Juicio de honestidad del producto

**Pregunta**: leyendo solo lo que la app/CLI te ha dicho en H1, ¿un usuario
entendería que save_restore cross-host no funciona en su setup y qué
necesitaría para que funcione? ☐ Sí ☐ No — si No, apuntar como hallazgo
doc/UX para v1.1.

---

## I. Casos de error (25 min)

> Objetivo: comprobar que el sistema falla BIEN — mensajes claros, nada roto,
> estados recuperables. Hacerlos en este orden y deshacer cada uno antes del siguiente.

### I1 — Agente caído → host offline

```bash
ssh gery@192.168.1.73 'pkill -f "[c]li agent run"'
# esperar ~30-60 s (umbral de offline):
$PY -m hypergery_ubuntu.cli v1 hosts
```

**Esperado**: portátil pasa a `offline` en CLI y en la página Remote Hosts de
la app (comprobar AMBOS). Reiniciar el agente (comando de A5) → `online` en <15 s.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### I2 — NAS no disponible para los servicios v1

```bash
# apuntar a una ruta inexistente SOLO en esta shell:
HYPERGERY_NAS_STAGING_PATH=/tmp/no-existe-nas $PY -m hypergery_ubuntu.cli v1 nas status
HYPERGERY_NAS_STAGING_PATH=/tmp/no-existe-nas $PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run
```

**Esperado**: error claro tipo NAS unavailable / ruta no válida. Sin traceback,
y por supuesto sin crear `/tmp/no-existe-nas`.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### I3 — Hub no disponible

```bash
HYPERGERY_HUB_URL=http://192.168.1.150:9999 $PY -m hypergery_ubuntu.cli v1 hosts
HYPERGERY_HUB_URL=http://192.168.1.150:9999 $PY -m hypergery_ubuntu.cli v1 health
```

**Esperado**: el registro degrada con elegancia (hosts locales siguen
apareciendo; lo remoto marcado no disponible). En la app: abrir Remote Hosts
con esa URL mala en Settings (y **restaurarla después**) debería mostrar
estado de Hub caído, no colgar la UI.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### I4 — Target offline en teleport

```bash
# con el agente del portátil parado (repetir kill de I1):
$PY -m hypergery_ubuntu.cli v1 teleport dry-run \
  --vm hg-v06-2host-source --target gery-Lenovo-ideapad-330S-14IKB --no-iso
```

**Esperado**: rechazo en preflight con motivo "host offline" claro. Nada
copiado, nada suspendido. Reiniciar el agente al terminar.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### I5 — Conflicto de red/lab visible

```bash
$PY -m hypergery_ubuntu.cli v1 network validate
```

**Esperado**: si el conflicto `hg-v03-par`/`importar` sigue sin resolver, debe
seguir saliendo aquí Y verse también en la tab Network del Control Center.
Pregunta UX: ¿la salida te dice QUÉ hacer para resolverlo? ☐ Sí ☐ No

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### I6 — Intento destructivo sin confirmación

```bash
# cleanup de staging sin --confirm → debe ser dry-run:
$PY -m hypergery_ubuntu.cli hub cleanup-staging --older-than-hours 24
# nas commit sin --confirm → debe ser dry-run:
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab
```

**Esperado**: ambos informan de lo que HARÍAN sin hacerlo (dry-run por
defecto). En la app: Force Off de una VM debe pedir confirmación siempre.
Si algo destructivo se ejecuta sin confirm → **FAIL bloqueante**.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

---

## J. Prueba de "usuario normal" (20 min)

> Objetivo: el ciclo de vida completo que haría alguien que no ha leído este
> repo. Solo con la app (GUI), sin CLI salvo donde se indica.

### J1 — Crear o cargar un lab

**Acción**: desde la página Labs, crear un lab nuevo de prueba
(`uat-lab-rc1`) o abrir uno existente. Si lo creas desde template, usar el
wizard de 3 páginas.

**Esperado**: el lab aparece con su red `hg-net-…` y subred sin colisiones.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### J2 — Entender el estado del lab de un vistazo

**Acción**: abrir la card/detalle del lab y la tab Topology.

**Esperado**: sabes en <30 s cuántas VMs hay, cuáles corren (verde) y cuáles
no, y en qué host está cada una.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### J3 — Operación segura

**Acción**: arrancar UNA VM del lab desde la UI, abrir su consola
(HyperGery Console si es VNC), y apagarla con **ACPI Shutdown** (no Force Off).

**Esperado**: arranque y apagado limpios, estados de la UI actualizados solos.

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### J4 — Mirar logs

**Acción**: encontrar los logs desde la app (Diagnostics) y por CLI:
```bash
$PY -m hypergery_ubuntu.cli v1 logs --limit 20 2>/dev/null || ls ~/.local/state/hypergery/logs/
```

**Esperado**: localizas los eventos de lo que acabas de hacer (operation_id
agrupando la operación). Pregunta UX: ¿entenderías estos logs sin conocer el
código? ☐ Sí ☐ No

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

### J5 — Cerrar todo limpiamente

**Acción**: apagar las VMs del lab (Shutdown Lab si hay varias — orden
role-aware), borrar el lab de prueba `uat-lab-rc1` SI lo creaste en J1
(con su confirmación), cerrar la app.

**Esperado**: cierre sin errores en consola; al reabrir la app, el estado es
coherente (el lab de prueba ya no está; lo demás, intacto).

**Resultado**: ☐ PASS ☐ FAIL — Notas: ______________________

---

## K. Qué capturar (transversal)

**Screenshots recomendadas** (carpeta sugerida: `~/uat-v1rc1/screenshots/`):
1. Dashboard al abrir (con la versión visible si está).
2. Remote Hosts con los 2 hosts online.
3. Control Center: tab más representativa + la más fea (JSON crudo).
4. Diálogo Live Migration con el preflight OK.
5. Página Migrations con el teleport de G3 en `done`.
6. Remote Hosts con el portátil `offline` (I1).
7. Cualquier mensaje de error feo/confuso que encuentres.
8. Topology del lab de J2.

**Comandos y outputs que guardar** (un solo fichero `~/uat-v1rc1/outputs.txt`):
- `v1 health`, `v1 hosts`, `v1 telemetry` del bloque D.
- Salida completa del commit/restore de F (con commit-id y `verified: true`).
- Salida del teleport G3 + los `virsh domuuid`/`domiflist` de origen y destino.
- Salida íntegra del error de H1 (es la evidencia del rollback seguro).
- Los errores de I2/I3/I4 (literales, para evaluar calidad de mensaje).

**Logs importantes**:
- `~/.local/state/hypergery/logs/` (sobremesa) — copiar los JSONL del día.
- `/tmp/hypergery-agent.log` en el portátil.
- Si el Hub hace algo raro: logs del contenedor `hypergery-hub` en Container Station.

**Bugs UX**: una línea por hallazgo en este formato (van directos a v1.1):
```
[pantalla/comando] — qué esperabas — qué viste — gravedad (bloqueante/molesto/polish)
```

---

## L. Criterio de aceptación (10 min)

### "Gerard aprueba v1.0-rc1" si y solo si:

1. Bloques A–G y I–J terminan **sin ningún FAIL bloqueante** (lista abajo).
2. H1 demuestra el rollback seguro (VM nunca queda parada sin reanudar).
3. Ninguna VM, lab, template ni dato preexistente ha sido alterado o borrado
   por ningún flujo (verificación final: `virsh list --all` en ambos hosts +
   `ls ~/.local/share/hypergery/labs/`).
4. La GUI (cubriendo el SKIP del smoke) no casca en ninguna pantalla.

### FAIL bloqueantes de v1.0 final (paran la release hasta arreglo):

- Pérdida o corrupción de cualquier dato: VM origen tocada en teleport,
  restore que sobreescribe (F5), commit `verified: false`.
- Acción destructiva ejecutada sin confirmación (I6).
- VM que queda parada/colgada tras un fallo de teleport/save_restore (H1).
- Crash de la app o traceback en un flujo principal (C1, G3, J).
- API que devuelve traceback/HTML en vez de envelope de error (E3).

### Va a v1.0.1 (no bloquea v1.0 final, pero se arregla pronto):

- Mensajes de error correctos pero poco accionables (I2–I5 con texto pobre).
- Estados de UI que no se refrescan solos y exigen reabrir la página.
- Inconsistencias CLI↔API↔UI en datos que deberían ser idénticos (D vs E vs C).
- El origen `paused` post-teleport sin mensaje que explique el porqué (G3).

### Polish de v1.1 (apuntar, no contar como fallo de este UAT):

- JSON crudo en el Control Center (ya planificado, V1_KNOWN_BUGS #1).
- Rol `unknown` del portátil en el registry.
- Textos confusos, mezcla de idiomas, iconografía, tiempos de carga <3 s.
- Falta de NAS commit/teleport con confirmación desde la UI (decisión
  deliberada de rc1, V1_KNOWN_BUGS #9).
- Todo lo recogido en B4/C6/K como "molesto" o "polish".

### Veredicto final

| Campo | Valor |
| --- | --- |
| Fecha del UAT | __________ |
| Commit/tag probado | `v1.0-rc1` |
| Totales | ____ PASS · ____ FAIL · ____ N/A |
| FAIL bloqueantes | ____ |
| **Decisión** | ☐ APROBADO para seguir hacia v1.0 final vía v1.1 · ☐ RECHAZADO (bloqueantes arriba) |
| Firma | Gerard |
