# Changelog

## v0.2.0 - En desarrollo

- Inicio de la rama `develop` para la siguiente iteracion sin modificar `main` ni la release `v0.1.0`.
- UI principal revisada para parecer mas una herramienta de gestion de VMs real: cabecera de producto, acciones principales separadas, estados de VM mas legibles y resumen de seleccion.
- Lista de VMs ampliada con estado, lab, CPU y RAM visibles.
- Panel de labs visible con lab id, numero de VMs y red asociada.
- Preflight visual mejorado con resumen de errores/avisos y tabla mas clara.
- Paneles de detalle reorganizados para General, System, Display, Storage, Network, Snapshots y Logs.
- Logs visibles con refresco manual y desplazamiento automatico al final.
- Wizard de creacion de VM dividido en Identity, Resources, Storage & Network y Review, con validacion temprana y confirmacion final.
- Confirmaciones mas explicitas para force off, delete, clone, settings y operaciones destructivas de snapshots.

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
