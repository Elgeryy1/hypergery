# Changelog

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
