# Changelog

## v0.7.0 - Unreleased (pre-release, pending final manual smoke)

Visual Refresh & UX Stabilization plus Hub Transfer migrations. Develop only;
not tagged or released until the final two-host manual smoke passes.

### UI — Visual Refresh (PySide6/QSS, design tokens)

- New app shell: sidebar navigation (Dashboard, Virtual Machines, Labs, Templates, Remote Hosts, Migrations, Diagnostics, Settings) and top bar with Hub/Host/NAS status chips.
- Dashboard with health cards (VMs, Hub, NAS, hosts), warnings, and last migration summary.
- Remote Hosts redesigned as a hub status card plus per-host cards with capability badges and per-host test action.
- Settings dialog redesigned with sectioned navigation and ENV/CONFIG/DEFAULT source chips per field.
- Diagnostics page running `doctor` checks in a background worker with grouped results and copyable report.
- NAS Clone Migration wizard rebuilt as a 6-step flow (Select VM, Target Host, Options, Preflight, Progress, Result) with progress states and auto-polling status.
- Virtual Machines view: page header with counters, 7-column table with state chips, modernized detail cards including Console status (Host Key: Right Ctrl).
- Console window polish: grouped toolbar, status bar with display type/resolution, explicit disconnected/powered-off/SPICE states. Closing the console never stops the VM.
- Migrations page with real read-only history from the Hub (`/migrations`): refresh on demand, status colors, copy ID/summary. Never deletes records or packages.

### Hub Transfer migrations (new in v0.7)

- Hub package staging endpoints: `PUT/GET/DELETE /packages/<migration_id>/...` with chunked streaming and path-traversal protection. Staging directory configurable via `HYPERGERY_HUB_STAGING`.
- New migration transfer mode `hub`: the source packages locally, uploads through the Hub, the target downloads, imports, and the Hub copy is deleted after a successful import. No shared NAS mount or identical paths required on hosts.
- `migrate remote --transfer hub|nas` CLI flag; the wizard defaults to Hub transfer and keeps shared-NAS mode as fallback.
- Source VM and source disks remain untouched in both transfer modes; target import still regenerates UUID and MAC and refuses existing target VM names.

### Infrastructure

- Default `hub_url` now points at the Hub running in Container Station on the NAS (`http://192.168.1.150:8765`); env and config overrides unchanged.
- `scripts/start-second-host.sh`: one-command launcher for a secondary host (agent + app against the NAS Hub).
- `scripts/install-agent-user-service.sh`: installs the agent as a systemd --user service (no sudo, no stored credentials; optional `loginctl enable-linger` for headless hosts).

### Deferred to v0.8

- Lab-specific visual workspace.
- Extra Settings sections (Host Agent options, Console preferences, Appearance accent/density).

## v0.6.0 - NAS Clone Migration

Release scope:

- NAS Control Plane.
- HyperGery Agent.
- Host Discovery.
- NAS Migration Staging.
- VM Package Export.
- VM Package Import.
- Live Migration UI action.
- Right-click VM context menu.
- Migration preflight.
- Migration progress/logs.
- CLI migration commands.

Release strategy: v0.6.0 presents the UI action as "Live Migration", but the shipped safe implementation is NAS Clone Migration. Source VMs, disks, and metadata remain untouched. Running VM migration is blocked unless a real safe libvirt/QEMU strategy is available.

Released in v0.6.0:

- HyperGery Hub Docker / NAS control plane with host registration, heartbeat/offline tracking, safe command queue, VM inventory, events, migration status records, Docker Compose setup, Docker healthcheck, and local Docker volume persistence for the SQLite DB.
- HyperGery Agent with config file support, capability heartbeat, safe command allowlist, migration command execution, and CLI `agent` commands.
- Remote Hosts support with CLI `host list`, `host show`, and `host test`.
- First-run Ubuntu bootstrap in `scripts/dev-run.sh` and `scripts/bootstrap-ubuntu.sh`.
- Migration package module with VM asset collection, offline preflight, package export, package validation, target identity regeneration, import rollback, and package listing.
- CLI `migrate preflight`, `migrate package`, `migrate validate-package`, `migrate import`, `migrate list`, and `migrate status`.
- NAS Clone Migration remote orchestration: source package creation in NAS staging, Hub `import_vm_package` command creation for the target host, target agent import, migration status polling helpers, and source VM preservation.
- Qt **Remote Hosts** panel with Hub host list, online/offline state, last seen, RAM/disk info, KVM/libvirt readiness, active VMs, Refresh, and Test command.
- Qt **Live Migration** VM action with real target host selection, target VM name, include ISO/snapshots, start-after-import, preflight output, and Start Migration gated by successful preflight.
- CLI `migrate remote` and `migrate status --migration-id` for registry-backed orchestration and polling.
- Separate HyperGery Console window for local VNC displays, with toolbar actions, explicit input capture/release, and Right Ctrl as Host Key.
- SPICE VMs now show a clear integrated-console fallback message and keep using the external viewer path.
- SPICE console UX now uses a clear VNC-required card, avoids input capture without an active VNC connection, and offers **Switch to VNC** while the VM is shut off.
- Switching a shut off VM from SPICE to VNC now removes SPICE-only audio/channel XML so libvirt can redefine the domain.
- HyperGery Console now auto-connects running VNC VMs and uses Scale to Fit rendering with a centered framebuffer and real-size scrollbars.
- Toolbar split between integrated **Console** and **External Console** so `virt-viewer` / `remote-viewer` remain available for SPICE and fallback.
- App-level settings for Hub URL, host identity, NAS staging path, default display, default ISO folder, and default VM storage path in `~/.config/hypergery/config.json`, with environment variables as overrides.
- CLI `doctor` command for non-destructive diagnostics of Python, KVM, libvirt, tools, Hub reachability, NAS staging, Docker Compose, and Hub VM inventory.
- Remote Hosts Hub status summary showing Hub URL, online/offline state, last check, online host count, VM record count, and NAS staging writability.
- v0.6 quick start guide at `docs/QUICK_START_V06.md`.

Validation status for final release:

- Automated tests pass: 214 tests OK in the Qt/offscreen venv and 214 tests OK with 15 skipped on system Python.
- Docker Hub smoke passed: `docker compose config`, `build`, `up`, `/health`, `/hosts`, and `/vms`.
- Hub/Agent smoke passed: agent registration, host list, VM inventory, and queued host test with `pong=true`.
- Local NAS Clone Migration E2E passed with two logical agents on one libvirt host: package created on NAS staging, source VM/disk preserved, target imported, UUID/MAC regenerated, target started, and target cleanup completed.
- Real two-physical-host NAS Clone Migration smoke passed with `hg-source` and `hg-target`: both hosts online with KVM/libvirt OK, NAS staging writable at `/mnt/hypergery-nas/hypergery`, command ping completed with `pong=true`, migration `hg-v06-2host-source-f67154f7803b` reached `done`, source VM/disk remained intact, target UUID/MAC were regenerated, target booted to `running`, target cleanup completed, and the NAS package was retained.

Not included in v0.6.0:

- True live RAM migration.
- HG-MEMDIFF or any custom dirty-page transfer protocol.
- AutoBoost.
- Android Hub.
- IsardVDI.
- SPICE integrated console.

Future topology polish:

- v0.7.0 or v0.6.x: export topology to PNG/SVG.
- v0.7.0 or v0.6.x: zoom and pan for large labs.
- v0.7.0 or v0.6.x: role badges in topology nodes.
- v0.7.0 or v0.6.x: progress per VM during lab instantiation.
- v0.7.0 or v0.6.x: improved cleanup actions.
- v0.7.0 or v0.6.x: optional removal of Tkinter legacy fallback.

## v0.5.0 - Lab Topology & UX

HyperGery v0.5.0 — topología visual de labs y mejoras de UX.

Cambios implementados en v0.5:

- `LabTopologyWidget` (topology.py): canvas QPainter con nodo de red a la izquierda y nodos de VM a la derecha; líneas bezier; color por estado (running=verde, shut off=gris, paused=ámbar, not created=pizarra); RAM/vCPUs badge; clic en nodo selecciona VM en la lista.
- `build_lab_topology()`: mezcla VMs live (libvirt) con VMs del manifiesto; marca VMs solo en manifiesto como "not created"; excluye VMs de otros labs.
- `topology_to_json()`: exporta topología como dict serializable.
- Panel de detalles del lab ahora tiene dos sub-tabs: "Details" (texto existente) y "Topology" (nuevo canvas).
- `PlannedVmDialog`: reemplaza `_AddPlannedVmDialog`; soporta tanto añadir como editar (pre-rellena campos); incluye `template_id` opcional, `notes`, validación de nombre en el dialog.
- `EditLabTemplateDialog` mejorado: usa `QTableWidget` con columnas Name/Role/OS/RAM/vCPUs/Disk/Display/ISO req.; doble-clic para editar VM; validación de duplicados al editar.
- `_IsoMappingPage` del wizard: botón "Apply same ISO to all VMs…" para reutilizar una ISO; status label indicando exactamente qué VMs faltan ISO.
- `CleanupPreviewDialog`: vista de lectura de todos los recursos HyperGery (VMs, labs, VM templates, lab templates); accessible desde botón "Resources…" en la barra de acciones.
- CLI `template update vm|lab <id> --set key=value`: actualiza campos de templates.
- CLI `lab-topology <lab_id>`: imprime topología como JSON.
- CLI `lab-instantiate <template_id> <lab_name> --iso vm=path [--dry-run]`: instancia un lab template desde CLI.
- Corrección final: `get_vm()` convierte memoria de libvirt (`KiB`, `MiB`, `GiB`, bytes) a MiB para que Topology/CLI no muestren RAM como `0` cuando `virsh dumpxml` normaliza `<memory>` a KiB.
- 10 nuevos tests: topología (vacía, con VMs, VMs de otros labs, not created, deduplicación, JSON), CLI update template, CLI lab-topology, CLI lab-instantiate dry-run, parseo de memoria KiB de libvirt.

Pendiente en v0.5 (roadmap):

- Role badges en nodos de topología.
- Export de topología como PNG/SVG.
- Zoom/pan para labs grandes.
- UI de progreso por VM durante instanciación.

## v0.4.0 - Lab Automation

HyperGery v0.4.0 — automatización de entornos de laboratorio.

Cambios implementados en v0.4:

- Modelo de Planned VMs ampliado: campos `iso_required` (por defecto `true`), `role`, `notes`; validación de nombres duplicados; validación de formato de nombre de VM.
- `TemplateStore.update_vm_template()` y `update_lab_template()`: edición in-place de plantillas sin borrar y recrear.
- `TemplateStore._resolve_planned_vm()`: resuelve defaults de VM Template referenciado y los combina con overrides de la planned VM.
- `TemplateStore.instantiate_lab_template()`: crea lab real y todas las VMs planificadas secuencialmente; `dry_run=True` valida sin crear nada; rollback transaccional si falla a mitad.
- UI Wizard `InstantiateLabTemplateWizard` (3 páginas): Lab Identity con preview, ISO Mapping con Browse por VM, Review completo.
- `create_lab_from_template()` usa el wizard y ejecuta `instantiate_lab_template()` en un worker en background; surfacea errores y warnings de rollback parcial.
- `EditVmTemplateDialog`: edición de todos los campos de VM Template excepto template_id y schema_version.
- `EditLabTemplateDialog`: edición de nombre, descripción, red y notas; gestión de planned VMs (add/remove via `_AddPlannedVmDialog`).
- `DuplicateLabDialog`: checkbox Clone VMs now enabled cuando el lab tiene VMs; `duplicate_lab()` pasa callbacks reales del backend cuando clone_vms=True, ejecutado en worker.
- 20 nuevos tests: dry_run, ISO faltante, rollback parcial, update, validación de planned VMs, resolución de defaults con y sin VM Template.
- Docs: `docs/TEMPLATES.md` reescrito completo; nuevo `docs/LAB_AUTOMATION.md` con explicación del flujo de instantiation, dry-run, rollback, edición y smoke test.

Pendiente en v0.4 (roadmap):

- CLI `template update` y `template instantiate`.
- Vista de topología de lab.
- Flujo mejorado template-to-ISO para reutilizar ISO en varias VMs.
- Edición inline de campos de planned VMs (actualmente: remove + re-add).

## v0.3.0 - Labs and Templates

HyperGery v0.3.0 — Lab Manager & Templates Manager.

Convierte HyperGery en un gestor de entornos de laboratorio reutilizables, manteniendo el backend real KVM/QEMU/libvirt de v0.1.0 y la UI PySide6/Qt de v0.2.0.

No implementado en v0.3 (dejado para v0.4):

- Auto-crear VMs desde lab template (requiere seleccion de ISO por cada VM planificada).
- Editar plantillas in-place (workaround: delete + recrear).
- Clonar discos de VMs durante `duplicate_lab` (disabled explicitamente en UI).
- Android Hub, NAS, IsardVDI, P2P, live migration, GPU shadowing.

Cambios implementados en v0.3:

- Nuevo modulo `hypergery_ubuntu.labs` con `LabStore`, migracion a `schema_version: 2`, export/import portable y duplicacion segura de labs.
- Nuevo modulo `hypergery_ubuntu.templates` con `TemplateStore`, plantillas de VM y plantillas de laboratorio.
- CLI minima para `lab list/create/show/rename/delete/export/import` y `template list/show/delete`.
- Tests unitarios de validacion de lab ids, migracion, subredes, bridges, export/import y plantillas.
- Primera UI Qt de Lab Manager conectada a `LabStore`: lista real de labs, detalles, seleccion activa y refresco manual.
- Acciones Qt para crear, renombrar nombre visible/descripcion, borrar, duplicar, exportar e importar labs con dialogos de validacion.
- Preview de nuevo lab y duplicado con `lab_id`, red libvirt, bridge y subred antes de crear.
- Filtro de lista de VMs entre `All VMs` y `Selected Lab`, con empty state `No VMs in this lab yet` y acceso a `New VM in Lab`.
- Clonado/borrado masivo de VMs desde dialogs de labs queda explicitamente deshabilitado hasta conectar el flujo real de discos.
- Templates Manager UI Qt conectado a `TemplateStore` real: tab `Templates` con sub-tabs `VM Templates` y `Lab Templates`.
- Lista real de VM Templates con columnas Name, ID, OS, RAM, vCPUs, Disk, Net, Display.
- Lista real de Lab Templates con columnas Name, ID, Net, VMs, Desc/Notes.
- Panel de detalles al seleccionar plantilla (nombre, id, recursos, red, notas).
- Dialogo `New VM Template` con Name, OS type, RAM, vCPUs, Disk, Network, Display, Notes y preview de template_id; Create desactivado si invalido.
- Dialogo `New Lab Template` con Name, Description, Network, Notes y preview de template_id; Create desactivado si invalido.
- Dialogo `Delete VM Template` con confirmacion escribiendo template_id.
- Dialogo `Delete Lab Template` con confirmacion escribiendo template_id.
- Export/Import de VM Templates y Lab Templates con `QFileDialog`, validacion JSON y manejo de colisiones.
- Activity log registra todas las operaciones de plantillas.
- `refresh_all` carga plantillas junto con VMs y labs en el arranque.
- Tests unitarios para validacion de template_id, conteo de VMs en lab template, validacion de campos, import invalido, delete inexistente y no sobreescritura en import.
- Tests Qt (`test_qt_ui`) se saltan limpiamente si PySide6 no esta disponible en el Python del sistema; se ejecutan dentro del venv con PySide6.
- Flujo `Create VM from Template`: abre wizard con valores prellenados (os_type, ram_mib, vcpus, disk_gb, network_mode, display); usuario elige nombre, ISO y lab; tras crear la VM se registra la plantilla en `templates_used` del manifiesto de lab.
- Flujo `Create Lab from Template`: dialogo con nombre, descripcion y modo de red prellenados desde la plantilla, preview de lab_id/network/bridge/subnet y lista de VMs planificadas; crea el lab real via `LabStore` y registra `templates_used`; las VMs planificadas no se crean automaticamente.
- Tests para mapeo template → defaults de wizard: presencia de campos, capitalizacion de os_type, tipos numericos, roundtrip de template real.

## v0.2.0 - Modern PySide6 UI

- Inicio de la rama `develop` para la siguiente iteracion sin modificar `main` ni la release `v0.1.0`.
- Migracion inicial de la UI principal a PySide6/Qt como interfaz por defecto.
- Capa Qt separada en `hypergery_ubuntu/ui_qt/`, reutilizando el backend real existente.
- UI Tkinter conservada temporalmente como `hypergery_ubuntu.app_tk` durante la migracion y mantenida una version mas como legacy fallback.
- Pulido visual del dashboard PySide6: preflight compacto, empty states, chips de estado, logs menos invasivos y cards de accion rapida.
- UI principal revisada para parecer mas una herramienta de gestion de VMs real: cabecera de producto, acciones principales separadas, estados de VM mas legibles y resumen de seleccion.
- Lista de VMs ampliada con estado, lab, CPU y RAM visibles.
- Panel de labs visible con lab id, numero de VMs y red asociada.
- Preflight visual mejorado con resumen de errores/avisos y tabla mas clara.
- Paneles de detalle reorganizados para General, System, Display, Storage, Network, Snapshots y Logs.
- Logs visibles con refresco manual y desplazamiento automatico al final.
- Wizard de creacion de VM dividido en Identity, Resources, Storage & Network y Review, con validacion temprana y confirmacion final.
- Confirmaciones mas explicitas para force off, delete, clone, settings y operaciones destructivas de snapshots.
- Documentadas instrucciones para crear el entorno virtual fuera del repositorio cuando este vive en un NAS o filesystem sin soporte fiable de symlinks.
- Prueba manual real de la UI PySide6 detecto un crash al intentar crear una VM en un entorno GNOME/Wayland con errores de portal DBus.
- Corregido el flujo de seleccion de ISO/directorio de la UI Qt para usar dialogos de fichero no nativos y evitar el crash del portal.
- Ajustada la inicializacion Qt para usar XCB por defecto en sesiones Wayland cuando `QT_QPA_PLATFORM` no esta definido, mitigando crashes de la pila Qt Wayland durante el flujo de creacion de VM.
- Fijado tema Qt generico `gtk3` y estilo `Fusion` por defecto para evitar el plugin de tema GNOME que seguia provocando segfaults al arrancar la UI.
- Evitado que la ventana principal ejecute `virsh list`/inventario de VMs de forma sincrona durante el constructor; la carga inicial y Refresh pasan a ejecutarse en background para no bloquear ni tumbar la UI.
- Corregido el crash al completar la creacion de VM desde Qt: los jobs de backend ya no pasan objetos Python por `Signal(object)`, sino que guardan el resultado en el worker y emiten senales sin payload.
- Retenidos temporalmente los `QThread` finalizados para evitar segfaults de Shiboken durante la destruccion del worker justo despues de crear una VM.
- Verificada creacion real desde la UI PySide6 con permisos `libvirt` efectivos mediante `sg libvirt`: wizard New VM, `qemu-img`, `virsh define`, VM en estado `shut off` y limpieza posterior.
- Corregida la carga de estados cuando `virsh domstate` devuelve texto localizado como `ejecutando`; los comandos externos se ejecutan con locale `C` y el backend normaliza estados conocidos.
- Documentacion y scripts preparados para cierre de v0.2.0: PySide6 como UI principal, Tkinter como legacy temporal, venv externo recomendado para NAS y checklist de validacion real UI Qt.
- Validacion manual final de UI Qt en `develop`: app arranca, preflight OK, creacion de `hg-v02-qt-test` desde ISO real, Start a running, Console con `virt-viewer`, apagado por ACPI o Force Off segun respuesta del guest, snapshots create/list/revert/delete, clone a `hg-v02-qt-clone`, delete seguro de test y clone, y sin VMs/discos de prueba restantes.

Limitaciones intencionales mantenidas en v0.2.0:

- Android Hub no incluido.
- NAS no incluido.
- IsardVDI no incluido.
- P2P no incluido.
- Migracion en caliente no incluida.
- GPU shadowing no incluido.

## v0.1.0 - Primera versión real de HyperGery Ubuntu/KVM

- Backend real con KVM/QEMU/libvirt mediante `virsh` y `qemu-img`.
- Creación de VM desde ISO local.
- Discos reales `qcow2`.
- Redes libvirt reales por laboratorio con bridges propios `hgbr*`.
- Consola real con `virt-viewer` o `remote-viewer`.
- Snapshots reales: crear, listar, revertir y borrar.
- Clone real de VMs apagadas con disco `qcow2` independiente.
- Delete seguro con confirmación y borrado limitado a discos gestionados por HyperGery.
- Preflight real de dependencias, permisos, KVM, libvirt y visor gráfico.
- Validación acceptance real en Ubuntu con VM `hg-acceptance-ubuntu-test`.

Limitaciones intencionales de v0.1.0:

- Android Hub no incluido.
- NAS no incluido.
- IsardVDI no incluido.
- P2P no incluido.
- Migración en caliente no incluida.
- GPU shadowing y RBAC no incluidos.
