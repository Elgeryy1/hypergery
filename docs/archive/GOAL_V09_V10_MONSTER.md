# GOAL_V09_V10_MONSTER.md

# HYPERGERY V0.9 → V1.0 MONSTER GOAL
## Misión autónoma de implementación completa para Claude Code

Este documento sustituye al goal anterior para una sesión larga de desarrollo.

La V0.8 ya está cerrada en `develop`, con tests pasando, commits realizados, Hub NAS validado, agent del portátil reiniciado y documentación alineada. A partir de esa base estable, la misión es avanzar hacia una V0.9 avanzada y una V1.0 funcional bruta de HyperGery.

La V1.0 no tiene que ser perfecta. La V1.1 será para arreglar bugs. La V1.2 será para hardening de seguridad. Esta misión prioriza construir, integrar, probar y dejar el proyecto funcionando.

---

# 0. PRINCIPIO GENERAL

No quiero solo documentación.

No quiero solo arquitectura.

No quiero stubs vacíos.

No quiero pantallas falsas.

No quiero clases sin conectar.

Quiero que implementes la mayor cantidad posible de HyperGery como producto funcional real, usando el portátil como máquina de desarrollo y validación.

Si una función avanzada no puede implementarse completamente esta noche, implementa la versión funcional más cercana, con una arquitectura preparada para evolucionar. Pero esa versión mínima debe estar conectada a UI, backend, logs, configuración, tests y documentación.

Ejemplos:

- Si no puedes hacer live RAM migration real, implementa primero migración funcional por suspend/export/copy/import/start.
- Si no puedes detectar dirty pages reales del hipervisor, implementa un MemDiff experimental sobre archivos/estados serializados con pruebas.
- Si no puedes controlar VMs remotas reales porque falta un host, implementa el agente/API/protocolo y prueba localmente con modo loopback o mock realista.
- Si no puedes crear app Android completa, implementa la API backend preparada para Android Hub.
- Si no puedes probar con PC de casa porque está offline, deja smoke manual exacto y valida todo lo que sí se pueda en local.

---

# 1. OBJETIVO FINAL

Evolucionar HyperGery desde V0.8 hasta:

## V0.9
Una versión avanzada, sólida y usable con:

- mejor gestión de hosts;
- mejor gestión de laboratorios;
- telemetría real;
- integración NAS más completa;
- logs robustos;
- comandos de operación;
- validaciones;
- health checks;
- UI más completa;
- documentación actualizada;
- tests pasando.

## V1.0
Una versión funcional bruta de la visión completa:

- orquestador inteligente;
- battery manager;
- teleport engine;
- NAS commit;
- network manager por laboratorio;
- preparación MemDiff;
- invitados/roles básicos;
- API para Android Hub;
- Isard/external node connector básico;
- paneles UI para todo;
- documentación de bugs y limitaciones;
- smoke manual completo.

---

# 2. REGLAS ABSOLUTAS

## 2.1 No romper V0.8

Antes de tocar nada:

```bash
git status
git branch --show-current
git log --oneline -5
```

Debes estar en `develop`.

No tocar `main`.

No hacer release.

No taggear.

No borrar commits existentes.

No modificar secretos.

No hacer operaciones destructivas.

No borrar `app_tk.py` si se mantiene como referencia/legacy.

## 2.2 Rama de trabajo

Trabaja en `develop` salvo que detectes que existe una política distinta.

Si decides crear rama, usa:

```bash
git checkout -b feature/v09-v10-monster
```

Pero por defecto trabaja en `develop` si el proyecto ya venía así.

## 2.3 Compilabilidad permanente

Después de cada bloque grande:

```bash
python -m pytest
```

Si existe entorno virtual:

```bash
source .venv/bin/activate || true
python -m pytest
```

Si hay tests Qt/offscreen:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

No avances durante mucho tiempo con el proyecto roto.

## 2.4 Commits frecuentes

Haz commits temáticos.

Formato recomendado:

```bash
git add .
git commit -m "feat(v09): add host telemetry service"
```

Tipos:

- `feat(v09): ...`
- `feat(v1): ...`
- `fix: ...`
- `test: ...`
- `docs: ...`
- `refactor: ...`
- `chore: ...`

Máximo recomendado:

- 1 módulo grande por commit.
- 1 refactor claro por commit.
- 1 pack de docs por commit.

## 2.5 No mentir en informes

Si algo queda experimental, dilo.

Si algo no se pudo probar, dilo.

Si algo necesita PC de casa/NAS/credenciales, dilo.

Pero intenta dejar todo lo posible probado en local.

## 2.6 Prioridad de ejecución

Orden estricto:

1. Que compile.
2. Que arranque.
3. Que funcione.
4. Que esté testeado.
5. Que tenga UI.
6. Que tenga logs.
7. Que esté documentado.
8. Que sea bonito.

---

# 3. FASE 0 — AUDITORÍA INICIAL

Antes de implementar:

## 3.1 Revisar estado del repo

Ejecutar:

```bash
git status
git branch --show-current
git log --oneline -20
find . -maxdepth 3 -type f | sort | sed 's#^\./##' | head -300
```

## 3.2 Detectar stack real

Identificar:

- lenguaje principal;
- framework UI;
- estructura de src;
- estructura de tests;
- docs existentes;
- servicios existentes;
- endpoints existentes;
- configuración;
- agent;
- Hub;
- integración NAS;
- comandos;
- sistema de persistencia.

## 3.3 Leer docs clave

Leer como mínimo:

- README.md
- CHANGELOG.md
- ARCHITECTURE.md / docs/ARCHITECTURE.md
- HUB.md
- LABS.md
- VALIDATION.md
- TROUBLESHOOTING.md
- QUICK_START_V08.md
- SMOKE_V08_PENDING.md si existe
- goal.md anterior si existe

## 3.4 Ejecutar tests base

Antes de tocar:

```bash
python -m pytest
```

Si falla, documentar estado inicial y corregir solo si es trivial. Si la V0.8 venía passing, no debería fallar.

## 3.5 Crear informe inicial

Crear:

```text
V09_V10_START_STATE.md
```

Debe incluir:

- branch;
- últimos commits;
- tests iniciales;
- módulos detectados;
- riesgos;
- plan resumido de implementación.

Commit:

```bash
git add V09_V10_START_STATE.md
git commit -m "docs(v09): record v09 v10 start state"
```

---

# 4. FASE 1 — V0.9 CORE STABILIZATION

Objetivo: dejar la base más fuerte antes de meter V1.

## 4.1 Configuración global

Implementar o mejorar configuración central:

- rutas locales;
- ruta NAS;
- host local;
- hosts remotos;
- modo offline;
- modo dry-run;
- umbrales de batería;
- umbrales de RAM;
- endpoints agent;
- timeouts;
- nivel de logs;
- flags experimentales.

Crear o mejorar:

- `config.py`
- `settings_service.py`
- `settings.json`
- UI Settings.

Criterios de aceptación:

- configuración carga sin romper;
- valores por defecto seguros;
- errores de configuración se muestran claros;
- tests unitarios.

## 4.2 Logging robusto

Implementar logs estructurados si aún no existen:

Campos recomendados:

- timestamp;
- level;
- module;
- host;
- lab_id;
- vm_id;
- operation_id;
- message;
- details.

Crear categorías:

- app;
- agent;
- hub;
- nas;
- teleport;
- battery;
- orchestrator;
- network;
- guest;
- api;
- tests.

Criterios:

- UI puede mostrar logs;
- se pueden filtrar;
- se pueden exportar;
- se escriben a archivo;
- tests.

## 4.3 Operation IDs

Toda operación larga debe tener `operation_id`:

- NAS commit;
- teleport;
- snapshot;
- restore;
- sync;
- host health;
- lab start;
- lab stop.

Criterios:

- logs agrupables;
- progreso trazable;
- errores claros.

## 4.4 Error handling

Crear errores propios:

- `HyperGeryError`
- `HostOfflineError`
- `NasUnavailableError`
- `TeleportError`
- `BatteryUnavailableError`
- `LabValidationError`
- `NetworkConflictError`
- `PermissionDeniedError`

Criterios:

- no stacktraces feos en UI;
- logs con detalle técnico;
- mensajes humanos para usuario.

---

# 5. FASE 2 — V0.9 HOSTS & AGENTS

Objetivo: sistema de hosts serio.

## 5.1 Modelo Host

Crear o mejorar modelo:

```text
Host
- id
- name
- role
- address
- agent_url
- status
- last_seen
- cpu
- ram_total
- ram_free
- disk_total
- disk_free
- battery_percent
- battery_status
- network_interfaces
- capabilities
- tags
```

Roles:

- laptop
- home_pc
- nas
- isard
- guest
- unknown

Capacidades:

- can_run_vms
- can_store_labs
- can_receive_teleport
- can_send_teleport
- can_report_battery
- can_report_network
- can_act_as_hub
- experimental

## 5.2 Host discovery

Implementar:

- carga desde config;
- detección local;
- health check;
- ping HTTP si hay agent;
- modo offline claro;
- modo loopback para pruebas.

## 5.3 Host health check

Endpoint/servicio:

```text
GET /health
GET /inventory
GET /telemetry
GET /commands
```

Si ya existen, ampliarlos.

## 5.4 UI Hosts

Pantalla Hosts:

- lista de hosts;
- estado online/offline;
- latencia;
- RAM;
- CPU;
- batería;
- capacidades;
- botón refresh;
- botón health;
- botón logs.

## 5.5 Tests

Crear tests:

- host model;
- host registry;
- health parser;
- offline handling;
- loopback host.

Commit:

```bash
git add .
git commit -m "feat(v09): add advanced host registry and health checks"
```

---

# 6. FASE 3 — V0.9 TELEMETRY

Objetivo: telemetría real y visible.

## 6.1 Telemetría local

Implementar usando librerías disponibles o métodos del sistema:

- CPU percent;
- RAM total/free/used;
- disk total/free/used;
- network interfaces;
- battery percent si disponible;
- uptime;
- process info si viable.

Si `psutil` está disponible, usarlo. Si no, implementar fallback.

## 6.2 Telemetría remota

Si hay agent:

- consumir `/telemetry`;
- cachear último estado;
- mostrar stale si no actualiza.

## 6.3 Historial básico

Guardar últimas N muestras por host.

No hace falta base de datos compleja.

Puede ser JSON local.

## 6.4 Alertas

Alertas mínimas:

- RAM baja;
- batería baja;
- host offline;
- NAS offline;
- disco bajo;
- agent sin responder.

## 6.5 UI Telemetry

Pantalla o panel:

- tarjetas por host;
- CPU/RAM/disco/batería;
- estado de red;
- timestamp;
- alertas.

## 6.6 Tests

- parse telemetry;
- fallback;
- stale status;
- alert thresholds.

Commit:

```bash
git add .
git commit -m "feat(v09): implement unified telemetry and alerts"
```

---

# 7. FASE 4 — V0.9 LABS WORKSPACE

Objetivo: laboratorios más potentes.

## 7.1 Modelo Lab

Debe soportar:

```text
Lab
- id
- name
- subject
- description
- vms
- networks
- storage_profile
- execution_profile
- owner
- guests
- created_at
- updated_at
- last_started_at
- status
- tags
```

Subjects recomendados:

- ASR
- PAR
- ISO
- SAD
- DB
- WEB
- CUSTOM

## 7.2 Operaciones Lab

Implementar:

- create;
- edit;
- clone;
- delete seguro;
- export;
- import;
- validate;
- archive;
- favorite.

## 7.3 Validación Lab

Comprobar:

- nombres únicos;
- VM ids válidos;
- redes sin conflicto;
- storage disponible;
- perfil de ejecución válido;
- permisos.

## 7.4 UI Labs

Pantalla Labs:

- grid/list;
- filtros por asignatura;
- estado;
- acciones rápidas;
- botón start;
- botón stop;
- botón commit NAS;
- botón teleport si aplica;
- botón clone.

## 7.5 Tests

- create lab;
- clone lab;
- validate lab;
- invalid network;
- export/import.

Commit:

```bash
git add .
git commit -m "feat(v09): expand labs workspace operations"
```

---

# 8. FASE 5 — V0.9 VM CONTROL

Objetivo: control de VMs más completo.

## 8.1 Modelo VM

```text
VM
- id
- name
- os_type
- cpu
- ram_mb
- disk_path
- status
- host_id
- lab_id
- network_ids
- snapshots
- last_seen
- boot_order
- notes
```

## 8.2 Operaciones VM

Implementar o mejorar:

- start;
- stop;
- restart;
- pause;
- resume;
- status;
- details;
- snapshot;
- restore;
- delete snapshot;
- open console si existe.

Si no hay backend real para alguna operación, usar modo adapter con:

- real provider si existe;
- simulated provider para tests;
- clear logs.

## 8.3 Provider abstraction

Crear interfaz:

```text
VMProvider
- list_vms()
- get_vm(id)
- start_vm(id)
- stop_vm(id)
- pause_vm(id)
- resume_vm(id)
- snapshot_vm(id, name)
- restore_snapshot(id, snapshot_id)
```

Providers:

- LocalProvider
- AgentProvider
- SimulatedProvider

## 8.4 UI VMs

- lista;
- estado;
- host;
- lab;
- recursos;
- acciones;
- logs.

## 8.5 Tests

- provider simulation;
- invalid transition;
- snapshot metadata;
- UI model if applicable.

Commit:

```bash
git add .
git commit -m "feat(v09): add vm provider abstraction and controls"
```

---

# 9. FASE 6 — V0.9 NAS SYSTEM

Objetivo: NAS como almacenamiento serio de HyperGery.

## 9.1 NAS config

Soportar:

- host;
- user;
- path;
- ssh mode;
- local mounted path;
- timeout;
- dry-run;
- compression.

No hardcodear secretos.

## 9.2 NAS health

Implementar:

- comprobar ruta;
- comprobar espacio;
- comprobar escritura dry-run;
- comprobar lectura;
- comprobar último commit.

## 9.3 Lab package format

Definir paquete:

```text
lab_id/
  manifest.json
  vms/
  disks/
  snapshots/
  logs/
  checksums.sha256
```

## 9.4 NAS Commit

Implementar:

1. validar lab;
2. freeze/snapshot si aplica;
3. empaquetar manifest;
4. calcular hashes;
5. copiar a destino NAS;
6. verificar hashes;
7. registrar commit;
8. mostrar resultado.

Debe tener dry-run.

## 9.5 Restore básico

Implementar:

- listar commits;
- seleccionar commit;
- validar hashes;
- restaurar manifest y ficheros;
- registrar operación.

## 9.6 UI NAS

Pantalla NAS:

- estado;
- ruta;
- espacio;
- último commit;
- historial;
- commit selected lab;
- restore;
- dry-run.

## 9.7 Tests

- package manifest;
- checksum;
- dry-run;
- restore validation;
- failure handling.

Commit:

```bash
git add .
git commit -m "feat(v09): implement nas commit and restore workflow"
```

---

# 10. FASE 7 — V1 ORCHESTRATOR / AUTO-BOOST

Objetivo: cerebro de HyperGery.

## 10.1 Motor de decisión

Crear servicio:

```text
OrchestratorService
```

Inputs:

- hosts;
- labs;
- vms;
- telemetry;
- battery;
- network;
- preferences;
- constraints.

Output:

```text
PlacementPlan
- lab_id
- vm_id
- current_host
- target_host
- reason
- confidence
- actions
- warnings
```

## 10.2 Reglas mínimas

Reglas:

- si host offline, no usar;
- si RAM libre insuficiente, evitar;
- si batería baja, preferir remoto;
- si VM ligera, preferir local;
- si VM pesada, preferir home_pc si disponible;
- si NAS operación, verificar NAS;
- si invitado, no permitir offload a recursos del admin;
- si modo offline, todo local o simulado.

## 10.3 Pesos de VM

Clasificar:

- ligera: <= 2GB RAM;
- media: <= 4GB RAM;
- pesada: > 4GB RAM;
- crítica: tag critical.

## 10.4 Explicabilidad

Cada decisión debe explicar:

- por qué;
- qué datos usó;
- qué riesgos hay;
- qué haría si falla.

Ejemplo:

```text
VM WinServer movida a home_pc porque portátil está al 28% de batería y solo tiene 3.2GB RAM libre. home_pc tiene 21GB libres y latencia aceptable.
```

## 10.5 UI Orchestrator

Panel:

- plan actual;
- recomendaciones;
- botón apply;
- botón dry-run;
- detalles de razonamiento;
- warnings.

## 10.6 Tests

- batería baja;
- RAM baja;
- host offline;
- guest restrictions;
- local-only mode.

Commit:

```bash
git add .
git commit -m "feat(v1): add auto-boost orchestrator decision engine"
```

---

# 11. FASE 8 — V1 BATTERY MANAGER

Objetivo: HyperGery reacciona a batería real.

## 11.1 Battery service

Crear:

```text
BatteryService
```

Funciones:

- get battery percent;
- get charging status;
- estimate mode;
- expose thresholds;
- generate events.

Umbrales:

- 50%: eco recommended;
- 30%: offload recommended;
- 20%: emergency;
- 10%: critical.

Configurable.

## 11.2 Acciones automáticas

Modos:

- disabled;
- recommend_only;
- auto_prepare;
- auto_execute_safe.

Acciones:

- reducir refresh;
- recomendar stop de VMs pesadas;
- preparar teleport;
- ejecutar teleport funcional si está permitido;
- commit NAS si está permitido.

## 11.3 UI Battery

Mostrar:

- porcentaje;
- estado;
- modo;
- umbrales;
- acciones pendientes;
- logs.

## 11.4 Tests

- no battery available;
- thresholds;
- event generation;
- recommend mode;
- emergency mode.

Commit:

```bash
git add .
git commit -m "feat(v1): implement battery manager and offload recommendations"
```

---

# 12. FASE 9 — V1 TELEPORT ENGINE

Objetivo: mover cargas entre hosts de forma funcional.

## 12.1 Teleport modes

Implementar modos:

```text
dry_run
local_loopback
suspend_copy_start
experimental_memdiff
```

Por defecto:

- `dry_run` para pruebas sin riesgo.
- `local_loopback` para validación sin PC remoto.
- `suspend_copy_start` para funcional real cuando haya host destino.

## 12.2 Teleport package

Formato:

```text
teleport_package/
  teleport_manifest.json
  lab_manifest.json
  vm_manifest.json
  disk_delta_or_reference
  state/
  checksums.sha256
  logs/
```

## 12.3 Flujo funcional

1. validar origen;
2. validar destino;
3. comprobar espacio;
4. comprobar VM status;
5. suspender/parar si hace falta;
6. exportar manifest;
7. copiar paquete;
8. verificar hash;
9. importar destino;
10. arrancar si procede;
11. actualizar inventario;
12. escribir logs.

## 12.4 Rollback

Si falla:

- dejar origen en estado seguro;
- no borrar datos;
- marcar destino como failed;
- escribir recovery instructions.

## 12.5 UI Teleport

Pantalla o panel:

- VM/Lab origen;
- host destino;
- modo;
- dry-run;
- ejecutar;
- progreso;
- logs;
- resultado.

## 12.6 Tests

- dry-run;
- local loopback;
- package manifest;
- checksum mismatch;
- host offline;
- rollback.

Commit:

```bash
git add .
git commit -m "feat(v1): implement teleport engine with safe transfer workflow"
```

---

# 13. FASE 10 — V1 MEMDIFF EXPERIMENTAL

Objetivo: preparar migración diferencial.

No es obligatorio lograr live migration real de RAM. Sí es obligatorio construir un módulo experimental real y testeable.

## 13.1 MemDiff service

Crear:

```text
MemDiffService
```

Funciones:

- snapshot_state(source);
- split_blocks(file/state);
- hash_blocks(blocks);
- compare_snapshots(a, b);
- produce_delta(a, b);
- apply_delta(base, delta);
- verify_result.

## 13.2 Formato Delta

```text
memdiff_delta/
  base_id
  target_id
  block_size
  changed_blocks
  hashes
  created_at
```

## 13.3 Pruebas con archivos

Usar archivos binarios simulados para validar:

- snapshot A;
- snapshot B;
- delta;
- apply delta;
- resultado == B.

## 13.4 Integración con Teleport

Teleport puede usar MemDiff si está activado:

- calcular delta;
- mostrar ahorro estimado;
- registrar experimental.

## 13.5 UI MemDiff

Mostrar:

- estado experimental;
- último delta;
- bloques modificados;
- ahorro;
- verificación.

## 13.6 Tests

- block split;
- delta detect;
- apply;
- verify;
- corrupt delta fail.

Commit:

```bash
git add .
git commit -m "feat(v1): add experimental memdiff delta engine"
```

---

# 14. FASE 11 — V1 NETWORK MANAGER

Objetivo: redes por laboratorio, aislamiento lógico y detección de conflictos.

## 14.1 Modelo Network

```text
Network
- id
- lab_id
- name
- cidr
- mode
- gateway
- dhcp_enabled
- isolated
- allowed_hosts
- notes
```

Modos:

- host_only;
- nat;
- internal;
- bridged;
- simulated.

## 14.2 Switch lógico por laboratorio

Cada lab debe tener redes propias.

No mezclar redes de labs salvo que se configure explícitamente.

## 14.3 Conflictos

Detectar:

- CIDR duplicado;
- gateway duplicado;
- DHCP conflictivo;
- VM conectada a red inexistente;
- cruce no autorizado.

## 14.4 UI Network

Mostrar:

- redes por lab;
- CIDR;
- modo;
- VMs conectadas;
- warnings;
- topología simple.

## 14.5 Packet logs básicos

Sin hacer captura intrusiva.

Solo registrar eventos propios:

- VM connected;
- network created;
- conflict detected;
- blocked cross-link;
- DHCP warning.

## 14.6 Tests

- CIDR conflict;
- isolated network;
- vm attach;
- invalid gateway;
- cross lab validation.

Commit:

```bash
git add .
git commit -m "feat(v1): add lab network isolation manager"
```

---

# 15. FASE 12 — V1 GUESTS / RBAC BÁSICO

Objetivo: colaboración controlada.

## 15.1 Roles

Implementar:

- SuperAdmin
- Admin
- Operator
- Guest

Permisos:

```text
can_view_labs
can_start_vm
can_stop_vm
can_commit_nas
can_teleport
can_use_remote_compute
can_manage_guests
can_change_settings
```

## 15.2 Reglas

Guest:

- solo labs asignados;
- no puede usar PC de casa del admin;
- no puede cambiar NAS;
- no puede ejecutar teleport remoto;
- puede ejecutar local si se permite;
- puede enviar commit si se permite.

## 15.3 Modelo User

```text
User
- id
- name
- role
- assigned_labs
- permissions
- created_at
```

## 15.4 UI Guests

Pantalla:

- usuarios;
- rol;
- labs asignados;
- permisos;
- estado;
- acciones.

## 15.5 Audit log

Registrar:

- login simulado/local;
- acción;
- permiso permitido/denegado;
- lab afectado.

## 15.6 Tests

- permission allow;
- permission deny;
- guest cannot offload;
- guest assigned lab;
- audit log.

Commit:

```bash
git add .
git commit -m "feat(v1): implement basic rbac and guest controls"
```

---

# 16. FASE 13 — V1 ISARD / EXTERNAL NODE CONNECTOR

Objetivo: preparar nodos externos de cómputo.

## 16.1 External node model

```text
ExternalNode
- id
- name
- type
- address
- status
- capabilities
- cpu
- ram
- notes
```

Types:

- isard
- cloud
- remote_pc
- loopback
- unknown

## 16.2 Registro manual

Implementar al menos:

- añadir nodo externo manualmente;
- health check;
- marcar capacidades;
- integrarlo en orquestador.

## 16.3 Detección heurística local

Si es viable:

- detectar virtualización;
- detectar entorno Linux/KVM;
- detectar hostname/tags;
- reportar como external.

No hacer nada invasivo.

## 16.4 UI External Nodes

- lista;
- estado;
- capacidades;
- botón health;
- botón add/remove;
- botón use in dry-run plan.

## 16.5 Tests

- add node;
- offline node;
- orchestrator includes external;
- invalid node.

Commit:

```bash
git add .
git commit -m "feat(v1): add external node connector for isard style boosters"
```

---

# 17. FASE 14 — V1 ANDROID HUB API / MOBILE READY BACKEND

Objetivo: dejar backend listo para app móvil.

## 17.1 API endpoints

Implementar o ampliar API:

```text
GET /health
GET /hosts
GET /hosts/{id}
GET /telemetry
GET /labs
GET /labs/{id}
GET /vms
GET /vms/{id}
GET /nas/status
GET /battery
GET /orchestrator/plan
POST /orchestrator/dry-run
POST /teleport/dry-run
POST /teleport/start
GET /logs
GET /network
GET /guests
```

Si el stack no tiene servidor HTTP, crear API service interno y dejar CLI/mock.

## 17.2 API responses

JSON claro:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "timestamp": "..."
}
```

Errores:

```json
{
  "ok": false,
  "error": {
    "code": "HOST_OFFLINE",
    "message": "Host is offline"
  }
}
```

## 17.3 OpenAPI

Si es viable, generar:

```text
docs/API_V1_OPENAPI.yaml
```

O al menos:

```text
docs/API_V1.md
```

## 17.4 Mobile mock panel

Si es rápido, crear panel web/simple:

- estado global;
- hosts;
- batería;
- labs;
- botones dry-run.

## 17.5 Tests

- health;
- hosts;
- telemetry;
- labs;
- error format;
- teleport dry-run.

Commit:

```bash
git add .
git commit -m "feat(v1): expose android hub ready api layer"
```

---

# 18. FASE 15 — V1 UI GLOBAL

Objetivo: que todo se pueda usar desde UI.

## 18.1 Navegación mínima

Pantallas o secciones:

- Dashboard
- Hosts
- Telemetry
- Labs
- VMs
- NAS
- Teleport
- Orchestrator
- Battery
- Network
- Guests
- External Nodes
- Logs
- Settings

## 18.2 Dashboard

Debe mostrar:

- estado global;
- hosts online/offline;
- labs activos;
- VMs activas;
- batería;
- NAS;
- alertas;
- próxima acción recomendada;
- últimos logs.

## 18.3 Acciones globales

- refresh;
- run health checks;
- dry-run orchestrator;
- open logs;
- export report.

## 18.4 No pantallas muertas

Cada pantalla debe:

- leer datos reales del servicio;
- mostrar empty state si no hay datos;
- mostrar errores;
- registrar acciones.

## 18.5 Tests

Si hay tests UI:

- crear pantalla;
- cargar modelo;
- acciones básicas.

Commit:

```bash
git add .
git commit -m "feat(v1): build integrated v1 ui navigation"
```

---

# 19. FASE 16 — CLI / COMMANDS

Objetivo: poder probar sin depender de UI.

Implementar comandos si la arquitectura lo permite:

```bash
hypergery health
hypergery hosts
hypergery telemetry
hypergery labs
hypergery labs validate
hypergery nas status
hypergery nas commit --lab LAB --dry-run
hypergery orchestrator plan --lab LAB
hypergery teleport dry-run --vm VM --target HOST
hypergery battery
hypergery network validate
hypergery guests list
```

Si no hay CLI binaria, crear scripts internos o comandos Python.

Criterios:

- comandos dev friendly;
- usados en smoke;
- documentados.

Commit:

```bash
git add .
git commit -m "feat(v1): add developer commands for v1 workflows"
```

---

# 20. FASE 17 — TESTING MASIVO

Objetivo: dejar el proyecto lo más validado posible.

## 20.1 Unit tests

Cubrir:

- config;
- host registry;
- telemetry;
- labs;
- VMs;
- NAS package;
- orchestrator;
- battery;
- teleport;
- memdiff;
- network;
- RBAC;
- API.

## 20.2 Integration tests

Crear tests de flujo:

### Flujo 1
Crear lab → validar → plan orchestrator → dry-run teleport.

### Flujo 2
Batería baja simulada → recomendación offload → plan generado.

### Flujo 3
NAS commit dry-run → paquete → checksum.

### Flujo 4
MemDiff A/B → delta → apply → verify.

### Flujo 5
Guest intenta offload → denegado → audit log.

## 20.3 Smoke local

Crear:

```text
V1_LOCAL_SMOKE.md
```

Con comandos exactos.

## 20.4 Ejecutar tests

Ejecutar:

```bash
python -m pytest
```

Y si aplica:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

Guardar salida en:

```text
TEST_RESULTS_V1.md
```

Commit:

```bash
git add .
git commit -m "test(v1): add integration coverage for v1 workflows"
```

---

# 21. FASE 18 — DOCUMENTACIÓN FINAL

Crear/actualizar:

## 21.1 V09_REPORT.md

Debe incluir:

- qué cambió en V0.9;
- commits principales;
- tests;
- cómo usar;
- limitaciones.

## 21.2 V10_REPORT.md

Debe incluir:

- módulos V1 implementados;
- estado de cada módulo:
  - functional;
  - experimental;
  - partial;
  - blocked.
- pruebas realizadas;
- próximos pasos.

## 21.3 ARCHITECTURE_V1.md

Incluir:

- diagrama textual;
- servicios;
- modelos;
- flujos;
- decisiones;
- límites.

## 21.4 V1_KNOWN_BUGS.md

Incluir:

- bug;
- severidad;
- reproducción;
- workaround;
- objetivo V1.1.

## 21.5 NEXT_STEPS_V11.md

Plan de bugfix:

- crashes;
- UX;
- rendimiento;
- tests faltantes;
- refactors.

## 21.6 NEXT_STEPS_V12_SECURITY.md

Plan de seguridad:

- token storage;
- RBAC hardening;
- audit logs;
- secret scanning;
- TLS;
- permisos;
- least privilege;
- NAS credentials;
- GitHub auth cleanup.

## 21.7 V1_MANUAL_SMOKE.md

Checklist para Gerard:

- encender PC casa;
- reiniciar agent;
- verificar laptop agent;
- verificar NAS;
- probar host health;
- probar telemetry;
- probar lab;
- probar NAS commit dry-run;
- probar teleport dry-run;
- probar orchestrator;
- probar UI;
- anotar bugs.

Commit:

```bash
git add .
git commit -m "docs(v1): add v1 reports smoke and next steps"
```

---

# 22. FASE 19 — FINAL VALIDATION

Antes de terminar, ejecutar:

```bash
git status
python -m pytest
```

Si hay venv:

```bash
source .venv/bin/activate || true
python -m pytest
```

Si hay UI Qt:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

Verificar que app arranca si hay comando documentado.

Verificar que no hay secretos:

```bash
git diff --cached
git status
```

Buscar posibles secretos:

```bash
grep -R "ghp_" -n . || true
grep -R "github_pat_" -n . || true
grep -R "password" -n . | head -50 || true
grep -R "token" -n . | head -50 || true
```

No commitear credenciales.

---

# 23. FASE 20 — INFORME FINAL DE CLAUDE

Crear:

```text
FINAL_V09_V10_HANDOVER.md
```

Debe contener:

## Resumen ejecutivo

- estado final;
- rama;
- commits;
- tests;
- módulos completos;
- módulos experimentales;
- bloqueos.

## Tabla de módulos

Columnas:

- módulo;
- estado;
- archivos principales;
- pruebas;
- notas.

Módulos:

- Hosts
- Telemetry
- Labs
- VMs
- NAS
- Orchestrator
- Battery
- Teleport
- MemDiff
- Network
- Guests/RBAC
- External Nodes/Isard
- Android API
- UI
- CLI/Commands
- Docs

## Comandos para mañana

Incluir copy-paste:

```bash
git status
python -m pytest
```

Y comandos concretos del proyecto para:

- app;
- agent;
- hub;
- smoke.

## Riesgos

- qué puede fallar;
- qué no se pudo probar;
- qué necesita PC casa;
- qué necesita NAS;
- qué necesita credenciales.

## Próximo mensaje recomendado

Preparar una frase para Gerard:

```text
V1 implementada en develop. Smoke manual pendiente. Revisa FINAL_V09_V10_HANDOVER.md y ejecuta V1_MANUAL_SMOKE.md. Después hacemos V1.1 bugfix.
```

Commit:

```bash
git add .
git commit -m "docs(v1): add final v09 v10 handover"
```

---

# 24. CRITERIOS DE ÉXITO

La misión se considera completada si:

- el repo está limpio o con cambios claramente documentados;
- hay commits temáticos;
- tests pasan o fallos están explicados;
- la app arranca o el motivo está documentado;
- V0.9 queda implementada;
- V1 queda montada funcionalmente;
- Teleport tiene versión funcional o dry-run/local-loopback;
- MemDiff tiene módulo experimental testeado;
- Orchestrator toma decisiones reales;
- Battery Manager funciona o tiene fallback;
- NAS Commit funciona o tiene dry-run + documentación;
- Network Manager valida redes;
- Guests/RBAC aplica permisos;
- API Android-ready existe o está documentada;
- UI muestra los módulos;
- docs finales existen.

---

# 25. QUÉ NO HACER

No hacer:

- release;
- tag;
- merge a main;
- borrar historial;
- meter secretos;
- depender de servicios externos sin fallback;
- dejar todo en mocks sin avisar;
- crear arquitectura gigante sin conectar;
- romper tests existentes;
- hacer operaciones destructivas en NAS;
- borrar datos locales;
- ejecutar acciones remotas reales sin confirmación si pueden destruir datos;
- prometer live migration perfecta si solo hay modo experimental.

---

# 26. ESTRATEGIA SI EL TIEMPO NO DA

Si no da tiempo a todo, priorizar así:

1. Orchestrator.
2. Battery Manager.
3. Teleport funcional/dry-run/local-loopback.
4. NAS Commit.
5. Network Manager.
6. UI integrada.
7. API Android.
8. MemDiff experimental.
9. Guests/RBAC.
10. External Nodes/Isard.
11. Docs finales.
12. Tests finales.

Pero no abandones módulos sin dejar al menos:

- modelo;
- servicio;
- UI mínima;
- tests básicos;
- documentación.

---

# 27. FRASE DE CIERRE PARA CLAUDE

Trabaja como si fueras el desarrollador principal de HyperGery durante toda la noche.

Implementa.

Ejecuta.

Prueba.

Corrige.

Commitea.

Documenta.

No pares en la primera versión que compile. Itera hasta dejar la V1 lo más funcional posible.

La V1.1 será para bugs.

La V1.2 será para seguridad.

Esta noche es para construir el monstruo.
