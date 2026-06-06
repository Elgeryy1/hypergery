# goal.md — HyperGery v0.8.0 Full Overnight Roadmap

## Objetivo general

Completar HyperGery v0.8.0 después de la Fase 1 ya validada en real.

Este archivo está pensado para pegarse como `goal.md` en el repo y usarlo con Claude/Codex en modo largo, ultra o multi-agent durante la noche.

La prioridad no es ir rápido. La prioridad es dejar HyperGery v0.8 sólido, testeado, documentado, seguro y listo para que mañana solo haga falta smoke manual real con los dos hosts.

---

# 0. Contexto actual

HyperGery v0.7.0 ya está publicado.

Estado esperado:

- `main` contiene HyperGery v0.7.0.
- `develop` está abierto para HyperGery v0.8.0.
- v0.7.0 incluyó:
  - Visual Refresh completo.
  - Hub Docker en NAS.
  - Hub URL por defecto: `http://192.168.1.150:8765`.
  - Hub Transfer como modo recomendado/default.
  - NAS Clone clásico como fallback.
  - Migrations history real.
  - Remote Hosts.
  - Remote VM inventory.
  - Agent user service installer.
  - 249 tests OK al publicar v0.7.0.

Fase 1 de v0.8 ya está completada y validada:

- Remote VM Power Control.
- `vm_start`.
- `vm_shutdown`.
- `vm_force_off`.
- UI en `Remote Hosts → View VMs`.
- comandos vía `App → Hub NAS → Agent destino → libvirt`.
- allowlist doble en Hub y Agent.
- sin delete remoto.
- sin shell remoto.
- sin consola remota.
- 260 tests OK.
- probado en real entre PC y Lenovo.

---

# 1. Objetivo de este goal

Implementar las 5 fases restantes de v0.8 de forma ordenada, segura y testeada:

1. **Fase 2 — Hub staging cleanup / maintenance**
2. **Fase 3 — Remote VM Details + Remote Command Queue UI**
3. **Fase 4 — Labs Workspace real**
4. **Fase 5 — Lab Power Actions + Polish**
5. **Fase 6 — Stabilization, docs, smoke final y release prep**

Objetivo nocturno:

- Dejar v0.8 implementada todo lo posible.
- Dejar tests verdes.
- Dejar docs alineadas.
- Actualizar el Hub Docker del NAS si cambia código del Hub/API.
- Dejar claro qué debe probar el usuario mañana.
- No hacer release.
- No tocar main.
- No taggear.

---

# 2. Reglas críticas globales

Estas reglas aplican a todas las fases.

- Trabajar solo en `develop`.
- No tocar `main` salvo permiso explícito del usuario.
- No crear tags.
- No crear releases.
- No borrar VMs reales.
- No borrar datos NAS.
- No hacer `docker compose down -v`.
- No ejecutar migraciones reales salvo confirmación explícita del usuario.
- No ejecutar acciones destructivas reales salvo que el usuario lo confirme.
- No implementar features fuera del scope de estas fases.
- No implementar true live RAM / HG-MEMDIFF.
- No implementar AutoBoost.
- No implementar Android Hub.
- No implementar IsardVDI.
- No implementar P2P.
- No implementar delete remoto.
- No implementar undefine remoto.
- No implementar delete-disks remoto.
- No implementar comandos shell remotos.
- No implementar consola remota integrada sin diseño previo.
- No exponer VNC remoto en LAN por defecto.
- No guardar secretos.
- No escribir passwords ni claves en docs.
- No añadir credenciales NAS al repo.
- Mantener compatibilidad con:
  - Hub Transfer v0.7.
  - NAS Clone clásico como fallback.
  - Remote VM Power Control v0.8 Fase 1.
- Mantener `app_tk.py` intacto.
- Mantener los tests existentes verdes.
- Si aparece un riesgo crítico, parar y reportar antes de seguir.

---

# 3. Instrucciones específicas para ejecución nocturna

Solo tendrás acceso real al portátil y al NAS. El PC de sobremesa puede no estar disponible para smoke real.

Puedes hacer:

- implementar código;
- ejecutar tests;
- ejecutar Qt/offscreen;
- probar Hub health;
- probar endpoints no destructivos;
- probar CLI dry-run;
- probar app real local en portátil si hay display;
- reiniciar Hub Docker del NAS si cambias código del Hub;
- reiniciar Agent del portátil si cambias código del Agent.

No puedes hacer:

- release;
- merge a main;
- tag;
- GitHub Release;
- cleanup real sobre paquetes reales;
- borrar VMs;
- borrar datos NAS;
- migraciones reales sin permiso;
- operaciones destructivas sobre VMs reales sin permiso.

Mañana el usuario hará el smoke manual real PC ↔ portátil.

---

# 4. Acceso NAS para mantenimiento del Hub Docker

Puedes usar SSH al NAS solo para mantenimiento del Hub Docker.

NAS:

- Host: `192.168.1.150`
- User: `Gery`
- Hub URL: `http://192.168.1.150:8765`

Usar clave SSH existente si está disponible, por ejemplo:

```bash
ssh -i ~/.ssh/hypergery_smoke Gery@192.168.1.150
```

No guardar passwords.  
No meter credenciales en docs.  
No imprimir secretos.  
No tocar datos NAS fuera de las rutas indicadas.

## Rutas NAS conocidas

Proyecto en NAS:

```text
/share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox
```

Staging/Hub data:

```text
/share/CACHEDEV2_DATA/Gerard/hypergery
```

Hub helper folder si existe:

```text
/share/CACHEDEV2_DATA/Gerard/hypergery/hub
```

Container Station Docker path en QNAP:

```text
/share/CACHEDEV2_DATA/.qpkg/container-station/bin/docker
```

Container Station Compose:

```text
/share/CACHEDEV2_DATA/.qpkg/container-station/bin/docker compose
```

---

# 5. Si cambias código del Hub/Registry/API

Si modificas:

- `hypergery_ubuntu/registry/server.py`
- `hypergery_ubuntu/registry/store.py`
- `hypergery_ubuntu/registry/client.py`
- `hypergery_ubuntu/hub/*`
- `Dockerfile`
- `docker-compose.yml`
- endpoints del Hub
- package/staging cleanup
- commands API

entonces debes actualizar el Hub Docker del NAS.

## Flujo recomendado desde el portátil

### 1. En el repo local del portátil

```bash
git switch develop
git pull origin develop

cd docker
docker compose build
cd ..
```

### 2. Exportar imagen al NAS mount

```bash
mkdir -p /mnt/hypergery-nas/hypergery/hub
docker save docker-hypergery-hub:latest | gzip > /mnt/hypergery-nas/hypergery/hub/hub-image.tar.gz
ls -lh /mnt/hypergery-nas/hypergery/hub/hub-image.tar.gz
```

### 3. Cargar/recrear Hub en el NAS por SSH

```bash
ssh -i ~/.ssh/hypergery_smoke Gery@192.168.1.150 '
set -e
CS=/share/CACHEDEV2_DATA/.qpkg/container-station/bin
HUB=/share/CACHEDEV2_DATA/Gerard/hypergery/hub

cd "$HUB"
gzip -dc hub-image.tar.gz | "$CS/docker" load
"$CS/docker" compose up -d --force-recreate
"$CS/docker" ps | grep hypergery-hub || true
'
```

### 4. Verificar

```bash
curl http://192.168.1.150:8765/health
```

Debe responder algo equivalente a:

```json
{"ok": true}
```

### 5. Probar endpoints nuevos de forma no destructiva

Puedes probar:

- `/health`
- `/hosts`
- `/migrations`
- `/commands`
- `/packages`
- cleanup dry-run.

No ejecutar cleanup real salvo sobre paquete falso/orphan creado explícitamente para test.  
No borrar paquetes reales sin confirmación del usuario.

---

# 6. Si cambias Agent

Si modificas:

- `hypergery_ubuntu/agent.py`
- comandos remotos
- inventario remoto
- lab actions remotas

reinicia el Agent del portátil para que coja el código nuevo:

```bash
systemctl --user restart hypergery-agent || true
systemctl --user status hypergery-agent --no-pager || true
```

Si no está instalado como servicio:

```bash
pkill -f "[c]li agent run" || true
setsid nohup ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli agent run \
  >/tmp/hypergery-agent.log 2>&1 < /dev/null &
sleep 2
pgrep -af "[c]li agent run"
```

No intentes reiniciar el Agent del PC de sobremesa si no está disponible.

---

# 7. Quality Gate obligatorio — no entregar si no está sólido

Antes de dar cualquier fase por completada, hacer una ronda explícita de verificación de calidad.

Objetivo:
No basta con que compile o pasen tests básicos. Cada fase debe quedar coherente, segura, usable y sin bugs obvios.

## 7.1 Auditoría de implementación

Revisar todos los archivos modificados y confirmar:

- no hay código muerto;
- no hay funciones duplicadas innecesarias;
- no hay nombres ambiguos;
- no hay prints/debug temporales;
- no hay mocks accidentales escribiendo en la raíz del repo;
- no hay paths personales hardcodeados salvo docs de validación histórica aceptable;
- no se han mezclado features de otra fase sin motivo;
- no se ha tocado main/tag/release;
- no se ha roto compatibilidad con v0.7.

## 7.2 Auditoría funcional

Probar mentalmente y con tests:

- happy path;
- estados vacíos;
- Hub offline;
- Agent offline;
- errores de red;
- permisos insuficientes;
- VM inexistente;
- VM en estado incompatible;
- comandos repetidos;
- cierre de diálogos mientras hay jobs/polling;
- UI sin congelarse;
- datos antiguos/stale;
- Hub viejo frente a app nueva;
- Agent viejo frente a Hub nuevo;
- errores JSON/API inesperados.

## 7.3 Auditoría de seguridad

Confirmar:

- ningún comando remoto arbitrario;
- ningún delete remoto;
- ningún shell remoto;
- ninguna escritura fuera de staging/config prevista;
- ningún path traversal;
- ninguna credencial guardada;
- ningún password en docs/tests/logs;
- acciones peligrosas con confirmación;
- Force Off siempre marcado como peligroso;
- cleanup solo borra staging temporal, nunca VMs ni discos reales;
- endpoint nuevo con validación de parámetros;
- allowlist doble si afecta al Hub/Agent;
- errores no filtran secretos.

## 7.4 Auditoría de UX

Confirmar:

- todo botón hace algo o está deshabilitado con explicación;
- todo error se muestra claro;
- no hay textos antiguos contradiciendo la feature nueva;
- no hay placeholders que prometen v0.8 si ya se implementó;
- empty states útiles;
- estados OK/WARN/FAIL visibles;
- no hay tablas sin scroll si pueden crecer;
- no hay UI que enseñe VMs locales al pedir VMs remotas;
- acciones destructivas se ven como danger;
- confirmaciones son claras;
- no se ocultan errores importantes en status bar temporal solamente.

## 7.5 Auditoría de tests

Añadir tests de:

- éxito;
- error;
- permisos/estado inválido si aplica;
- Hub offline;
- Agent offline;
- datos vacíos;
- Qt offscreen para UI nueva;
- seguridad si hay allowlist, cleanup o comandos remotos;
- regresión para cualquier bug encontrado.

No aceptar “lo probé manualmente” como sustituto de test si el caso puede automatizarse.

## 7.6 Validación completa

Ejecutar la suite completa indicada en este documento.

Si falla cualquier paso:

1. parar;
2. arreglar;
3. repetir validación;
4. documentar causa y fix.

## 7.7 Revisión de diff

Antes de commitear:

```bash
git diff --stat
git diff --check
git status --short --branch
```

Revisar cada archivo modificado y confirmar:

- commits pequeños y temáticos;
- no se mezclan features no relacionadas;
- no hay secretos;
- no hay ficheros basura;
- no se ha tocado main/tag/release.

## 7.8 Informe obligatorio por fase

Al terminar cada fase, responder:

A) Qué se implementó.  
B) Qué bugs se encontraron y arreglaron.  
C) Qué riesgos quedan.  
D) Qué tests se añadieron.  
E) Qué validación exacta se ejecutó.  
F) Qué se probó manualmente, si aplica.  
G) Qué NO se implementó por seguridad.  
H) Si la fase queda lista para pasar a la siguiente.  
I) Commits creados.  

## 7.9 Criterio de aceptación

Una fase no está terminada si:

- hay tests fallando;
- hay botón roto;
- hay error silencioso;
- hay comportamiento destructivo sin confirmación;
- hay docs contradiciendo el código;
- hay código sin test razonable;
- hay rutas/secretos accidentales;
- hay tareas “planned for v0.8” que ya deberían estar resueltas;
- hay deuda crítica sin documentar.

Si algo no puede quedar sólido en la fase actual, no improvisar: documentarlo como riesgo y pedir decisión antes de continuar.

No priorizar velocidad sobre estabilidad. Si hay que elegir entre hacer más features o dejar lo actual robusto, elegir robustez.

---

# 8. Validación obligatoria tras cada fase

Ejecutar:

```bash
cd hypergery-ubuntu

QT_QPA_PLATFORM=offscreen ~/.venvs/hypergery/bin/python -m unittest discover -s tests \
  || QT_QPA_PLATFORM=offscreen /home/gery/.venvs/hypergery/bin/python -m unittest discover -s tests \
  || QT_QPA_PLATFORM=offscreen /home/gerard/.venvs/hypergery/bin/python -m unittest discover -s tests

python3 -m unittest discover -s tests

cd ..

python3 -m compileall hypergery-ubuntu

bash -n \
  scripts/dev-run.sh \
  scripts/bootstrap-ubuntu.sh \
  scripts/preflight.sh \
  scripts/acceptance-ubuntu.sh \
  scripts/acceptance-real-host.sh \
  scripts/install-ubuntu-deps.sh \
  scripts/install-desktop-launcher.sh \
  scripts/start-second-host.sh \
  scripts/install-agent-user-service.sh

cd docker
docker compose config
cd ..
```

Si alguna validación falla:

- no seguir a la siguiente fase;
- arreglar el fallo;
- repetir validación;
- documentar causa y fix.

---

# 9. Fase 2 — Hub staging cleanup / maintenance

## 9.1 Objetivo

Añadir mantenimiento seguro del staging temporal del Hub.

Contexto:

- v0.7 añadió Hub Transfer.
- Los paquetes se suben al Hub y se borran tras import.
- Si una migración falla, se interrumpe o el target está apagado, pueden quedar paquetes huérfanos en staging.
- Hay que poder verlos y limpiarlos de forma segura.

## 9.2 Alcance funcional

Implementar:

1. Listado de staging del Hub.
2. Detección de paquetes huérfanos.
3. Dry-run cleanup.
4. Cleanup real solo de staging temporal.
5. UI o sección en Hub Admin / Migrations para visualizarlo.
6. CLI de mantenimiento.

## 9.3 Backend / Hub

Añadir endpoints o helpers seguros, preferiblemente bajo el Hub existente.

### `GET /packages`

Debe devolver packages staged:

- migration_id;
- path relativo seguro;
- size_bytes;
- file_count;
- created/modified time;
- age;
- linked migration status si existe;
- orphan yes/no;
- reason si es cleanup candidate.

### `POST /packages/cleanup`

Parámetros:

- `older_than_hours`;
- `dry_run`, default true;
- `include_failed`, opcional;
- `include_orphans`, opcional.

Debe devolver:

- candidates;
- total_size_bytes;
- deleted_count si no es dry-run;
- deleted_size_bytes;
- skipped;
- errors.

Mantener endpoints existentes si ya existen:

- `GET /packages/<migration_id>`;
- `PUT /packages/<migration_id>/<file>`;
- `DELETE /packages/<migration_id>`.

## 9.4 Reglas de seguridad

- Jamás borrar VMs.
- Jamás borrar discos importados.
- Jamás borrar fuera de `HYPERGERY_HUB_STAGING`.
- Protección contra path traversal.
- Dry-run debe ser el comportamiento por defecto en CLI.
- Cleanup real debe requerir flag explícito.
- No borrar paquetes recientes.
- No borrar paquetes de migraciones activas.
- No seguir symlinks peligrosos.
- No aceptar rutas absolutas del cliente.
- Toda eliminación debe quedar registrada en logs/resultados.

## 9.5 CLI

Añadir comandos:

```bash
python -m hypergery_ubuntu.cli hub packages
python -m hypergery_ubuntu.cli hub cleanup-staging --older-than-hours 24 --dry-run
python -m hypergery_ubuntu.cli hub cleanup-staging --older-than-hours 24 --confirm
```

Reglas:

- Sin `--confirm`, no borrar nada.
- Mostrar tabla/resumen.
- Mostrar tamaño total.
- Mostrar candidates.
- Mostrar skipped.
- Mostrar errores.
- Exit code distinto de cero si cleanup real falla.

## 9.6 UI

Añadir en Migrations o nueva sección Hub Admin/Maintenance.

Cards:

- Hub staging path.
- Packages staged.
- Total staging size.
- Orphan packages.
- Oldest package.
- Cleanup candidates.

Botones:

- Refresh.
- Dry Run Cleanup.
- Cleanup Confirmed.

UX:

- Cleanup real debe pedir confirmación.
- Mensaje claro:
  “Only temporary Hub staging packages are deleted. VMs and imported disks are never touched.”
- Errores del Hub inline, sin crash.
- Empty state útil:
  “No staged packages found.”
- Si Hub offline:
  “Hub not reachable. Check the NAS Hub and HYPERGERY_HUB_URL.”

## 9.7 Tests

Añadir tests.

Hub/server:

- lista paquetes;
- calcula tamaños;
- detecta orphan;
- cleanup dry-run no borra;
- cleanup confirm borra solo staging;
- path traversal bloqueado;
- paquete reciente no se borra si no supera threshold;
- paquete de migración activa no se borra.

Client/CLI:

- `hub packages`;
- `hub cleanup-staging --dry-run`;
- `hub cleanup-staging --confirm`;
- CLI sin confirm no borra.

Qt:

- UI muestra staging stats;
- dry-run renderiza candidates;
- cleanup pide confirmación;
- error del Hub no crashea;
- empty state.

## 9.8 Commits esperados

```text
hub: add staging package cleanup
ui: add Hub staging maintenance
docs: document Hub staging cleanup
```

---

# 10. Fase 3 — Remote VM Details + Remote Command Queue UI

## 10.1 Objetivo

Hacer que el inventario remoto deje de ser una tabla simple y se convierta en una vista útil de gestión remota, además de añadir observabilidad de comandos.

## 10.2 Parte A — Remote VM Details

En `Remote Hosts → View VMs`:

Al seleccionar una VM remota, mostrar panel de detalle:

- VM name;
- Host ID;
- Host name;
- State;
- Lab;
- RAM;
- vCPUs;
- Disk paths;
- ISO paths;
- Display type;
- MACs si están disponibles;
- Networks si están disponibles;
- Last inventory update;
- source de inventario;
- warning si los datos están stale.

Acciones remotas:

- Start;
- ACPI Shutdown;
- Force Off;
- Refresh.

Acciones NO disponibles:

- Console remote: disabled, “arrives later”.
- Delete remote: “intentionally not supported”.
- Reboot: only if backend safe method exists.

## 10.3 Inventario reportado por Agent

Mejorar si hace falta:

- disk_paths;
- iso_paths;
- display;
- networks;
- MAC addresses;
- snapshots count si existe barato;
- config path si no expone información sensible.

No tocar acciones destructivas.

## 10.4 Parte B — Command Queue UI

Crear página o panel:

`Commands` o sección dentro de Diagnostics/Hub Admin.

Debe mostrar:

- command_id;
- target_host_id;
- command_type;
- status:
  - pending;
  - running;
  - done;
  - failed;
- created_at;
- updated_at;
- age;
- payload resumen;
- result resumen;
- error si existe.

Acciones:

- Refresh.
- Copy command ID.
- Copy result.
- Filter:
  - all;
  - pending;
  - running;
  - done;
  - failed;
  - power commands;
  - migration commands.

Reglas:

- Solo lectura.
- No requeue todavía.
- No delete commands.
- No ejecutar comandos desde esta página salvo los ya existentes en Remote VM UI.
- No mostrar payloads con secretos si en el futuro los hubiera.

## 10.5 Hub/Client

Si no existe endpoint de listar commands, añadir:

### `GET /commands`

Filtros opcionales:

- target_host_id;
- status;
- command_type;
- limit.

No romper endpoint existente.

## 10.6 UI

Puede ubicarse como:

- nueva página sidebar `Commands`, si no rompe navegación; o
- sección dentro de Diagnostics; o
- panel dentro de Remote Hosts.

Preferencia:

- nueva página o subpanel claro, porque será muy útil para depurar.

## 10.7 Tests

Agent/Hub:

- list commands endpoint;
- filtros;
- resultados estructurados;
- limit funciona;
- payload/result se serializa bien.

Qt:

- Remote VM details panel muestra campos;
- botones power siguen funcionando;
- command queue muestra pending/done/failed;
- filtros funcionan;
- errores Hub no crashean;
- copy command ID/result no crashea;
- no hay acciones destructivas desde command queue.

## 10.8 Commits esperados

```text
hub: add command queue listing
ui: add remote VM details panel
ui: add command queue view
docs: document remote command observability
```

---

# 11. Fase 4 — Labs Workspace real

## 11.1 Objetivo

Convertir Labs en una vista real, no un banner.

Actualmente Labs está separado visualmente pero no funcionalmente. v0.8 debe hacer que Labs sirva para trabajar con grupos de VMs.

## 11.2 Funcionalidad mínima

Página Labs:

- Lista de labs.
- Lab seleccionado.
- VMs por lab.
- Estado global del lab:
  - total VMs;
  - running;
  - shut off;
  - paused;
  - unknown.
- Host distribution:
  - qué VMs están en qué host.
- Quick actions:
  - Open VM;
  - View Remote VM;
  - Migrate VM;
  - Start Lab;
  - Shutdown Lab;
  - Snapshot Lab si existe soporte real y seguro; si no, planned.

## 11.3 Lab Detail

Para cada lab:

- Nombre.
- Descripción.
- VMs.
- Rol opcional por VM:
  - router;
  - server;
  - client;
  - db;
  - web;
  - dns;
  - ad;
  - firewall.
- Estado.
- Host actual.
- RAM/vCPU.
- IP si existe forma real de obtenerla; si no, no inventar.
- Actions.

## 11.4 Data model

Revisar si existe LabStore o equivalente.

No hacer migraciones de schema peligrosas si no hace falta.

Si se añaden campos:

- hacerlo con migración segura;
- tests de compatibilidad;
- defaults razonables.

## 11.5 UI

Diseño:

- cards por lab;
- panel detalle;
- chips de estado;
- agrupación por host;
- empty state:
  “No labs yet. Create VMs in default-lab or create a new lab.”

No implementar topology visual avanzada todavía, salvo mini-layout simple si es barato.

## 11.6 Actions

### Start Lab

- Enviar start a cada VM del lab.
- Local VMs: backend local.
- Remote VMs: Hub → Agent.
- Confirmación:
  “This will start N VMs across M hosts.”

### Shutdown Lab

- ACPI shutdown a cada VM running.
- Confirmación:
  “This will request ACPI shutdown for N running VMs.”

### Force Off Lab

No implementarlo por defecto.

Si se añade:

- hidden/danger;
- confirmación fuerte;
- no incluir en toolbar principal.

Preferencia:

- dejar fuera de v0.8 Fase 4.

## 11.7 Tests

- Labs page no es banner.
- Lista labs.
- Muestra VMs por lab.
- Estado global correcto.
- Host distribution correcta.
- Start Lab encola comandos remotos y llama backend local según corresponda.
- Shutdown Lab idem.
- No Force Off Lab sin confirmación.
- Empty state.
- Hub offline no crashea.
- Agent offline produce errores claros.

## 11.8 Commits esperados

```text
ui: add Labs workspace
agent: support lab-aware remote actions if needed
docs: document Labs workspace
```

---

# 12. Fase 5 — Lab Power Actions + Polish

## 12.1 Objetivo

Cerrar la experiencia de Labs y Remote Control con acciones útiles, feedback y polish.

## 12.2 Lab Power Actions

Implementar de forma segura:

- Start Lab.
- Shutdown Lab.
- Refresh Lab.
- Migrate selected VM from Lab.
- View VM details.

Opcional si es seguro:

- Start order.
- Shutdown order.

Start order sugerido:

1. routers/firewalls;
2. infrastructure servers: DNS/AD;
3. app/db servers;
4. clients.

Shutdown order sugerido:

1. clients;
2. app/db servers;
3. infrastructure;
4. routers.

Si no hay roles:

- arrancar por orden alfabético o por orden actual;
- apagar por orden inverso o por running-first.

No implementar:

- Force Off whole Lab como acción normal.
- Delete Lab con VMs.
- Delete VMs.
- Destructive cleanup.

## 12.3 Activity Center / Notifications ligeras

Añadir un panel simple o mejorar activity log:

- Remote command queued.
- Remote command done.
- Remote command failed.
- Migration done.
- Hub staging cleanup done.
- Lab action started.
- Lab action done.
- Lab action partially failed.

No hace falta notificaciones del sistema operativo.

## 12.4 UI polish general

Revisar:

- Dashboard.
- Remote Hosts.
- Migrations.
- Commands.
- Labs.
- Settings.
- Diagnostics.
- VM inventory remote.
- Console local.

Buscar:

- textos cortados;
- botones ambiguos;
- estados que no se refrescan;
- errores silenciosos;
- botones que no hacen nada;
- tablas sin empty state;
- acciones que siguen habilitadas cuando no deben;
- tooltips faltantes;
- warnings demasiado temporales.

## 12.5 Tests

- Lab action feedback.
- Activity entries.
- No crashes con Hub offline.
- No crashes con Agent offline.
- Botones disabled correctamente.
- No acciones destructivas accidentales.
- Partial failure visible.
- Activity log conserva mensajes relevantes.

## 12.6 Commits esperados

```text
ui: add Lab power actions
ui: improve activity feedback
ui: polish v0.8 remote control workflows
```

---

# 13. Fase 6 — Stabilization, docs, smoke final y release prep

## 13.1 Objetivo

Dejar v0.8 lista para RC o release final.

## 13.2 Auditoría final

Revisar:

- Bugs reales.
- Seguridad.
- Docs.
- Tests.
- Rutas hardcodeadas.
- Secrets.
- Placeholders.
- Promesas no cumplidas.
- Cosas que deberían moverse a v0.9.

Buscar:

```bash
grep -RniE "password|passwd|token|secret|BEGIN .*PRIVATE KEY|638678107Mary|Y:|C:\\\\|\\\\\\\\|TODO|FIXME|planned for v0.8|arrives in v0.8" . \
  --exclude-dir=.git \
  --exclude-dir=__pycache__ \
  --exclude-dir=.pytest_cache \
  --exclude-dir=node_modules
```

Clasificar hallazgos:

- bloqueante;
- no bloqueante;
- mover a v0.9.

## 13.3 Docs

Actualizar:

- README.md.
- CHANGELOG.md.
- docs/VALIDATION.md.
- docs/HYPERGERY_HUB.md.
- docs/NAS_LIVE_MIGRATION.md.
- docs/TROUBLESHOOTING.md.
- docs/ARCHITECTURE.md.
- docs/QUICK_START_V08.md.
- RELEASE_NOTES_v0.8.0.md si toca preparar release.

Documentar:

- Remote VM Power Control.
- Hub staging cleanup.
- Remote VM Details.
- Command Queue UI.
- Labs Workspace.
- Lab Power Actions.
- Limitaciones:
  - no remote delete;
  - no remote console integrada todavía;
  - no true live RAM;
  - Hub auth pendiente si sigue pendiente.

## 13.4 Smoke manual recomendado

No ejecutar automáticamente salvo confirmación del usuario.

Checklist:

- PC y Lenovo online.
- Hub NAS online.
- Agents actualizados.
- Remote VM inventory.
- Start remoto.
- Shutdown remoto.
- Force Off remoto con confirmación.
- Command Queue muestra comandos.
- Migrations history carga.
- Hub staging cleanup dry-run.
- Hub staging cleanup confirm sobre paquete falso/orphan.
- Labs workspace muestra VMs.
- Start Lab.
- Shutdown Lab.
- Diagnostics.
- Settings.
- Console local VNC.
- Console local SPICE fallback.

## 13.5 Tests finales

Ejecutar validación completa obligatoria.

## 13.6 Release prep

No hacer release sin confirmación.

Cuando el usuario diga “smoke OK”:

- cambiar versión a `0.8.0`;
- actualizar CHANGELOG de Unreleased a final;
- crear release notes;
- commit release docs/version;
- dejar listo para merge/tag.

No tocar main/tag/release salvo permiso explícito.

## 13.7 Commits esperados

```text
docs: document v0.8 remote cluster workflows
release: prepare HyperGery v0.8.0
```

---

# 14. Entrega final esperada tras completar todas las fases

Responder con:

A) Estado inicial.  
B) Fases implementadas.  
C) Commits creados.  
D) Tests ejecutados exactos.  
E) Funciones nuevas.  
F) Seguridad:
   - qué comandos se permiten;
   - qué comandos se prohíben;
   - confirmación de que no hay delete remoto.  
G) Si se actualizó Hub Docker del NAS.  
H) Estado del Hub:
   - health;
   - endpoints nuevos probados.  
I) Estado del Agent del portátil.  
J) Qué se probó en real.  
K) Qué queda para smoke manual mañana.  
L) Qué se mueve a v0.9.  
M) Si v0.8 queda RC-candidate o todavía falta trabajo.  

---

# 15. Criterio final de éxito de v0.8

HyperGery v0.8 se considera listo cuando:

- Desde un host puedes ver VMs remotas.
- Puedes arrancar/apagar/forzar apagado de VMs remotas.
- Puedes ver detalles remotos útiles.
- Puedes ver la cola de comandos.
- Puedes mantener staging del Hub.
- Puedes gestionar labs reales.
- Puedes ejecutar acciones de lab.
- No existe delete remoto.
- No existe shell remoto.
- No existe consola remota insegura.
- Hub Transfer sigue funcionando.
- Migrations history sigue funcionando.
- Tests completos verdes.
- Smoke manual PC ↔ Lenovo pasado.

---

# 16. Nota final para ejecución nocturna

Puedes trabajar durante la noche, pero no ejecutes operaciones destructivas, no hagas cleanup real sobre datos reales, no borres VMs, no hagas release, y si falla una fase o los tests no pasan, para y deja informe.

Si tienes que elegir entre hacer más features o dejar lo actual robusto, elige robustez.
