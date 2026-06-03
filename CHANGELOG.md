# Changelog

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
