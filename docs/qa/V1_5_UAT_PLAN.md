# Plan UAT v1.5 — live migration directa (U10–U12) · MODO AVANZADO

> **Replanteamiento 2026-06-10:** la live migration directa host-a-host es
> **modo avanzado/experimental**; el flujo oficial es la migración mediada por
> el Hub (`docs/qa/V1_5_HUB_MIGRATION_UAT_PLAN.md`, que es el gate de release).
> Estado: **U11 PASS · U12 PASS · U10 pendiente de NFS** (ya NO bloquea release).
- **Equipos:** PC (origen) y portátil (destino), ambos con la RC instalada o
  el venv actualizado, conectados por la LAN privada.
- **Regla de oro:** SOLO VMs `hgtest-*`. Jamás una VM real. Limpieza al acabar.

## Preparación (una vez)

```bash
# En ambos equipos: ssh sin contraseña entre ellos (qemu+ssh) y libvirt activo.
ssh gery@portatil true                          # debe entrar sin preguntar
virsh --connect qemu+ssh://gery@portatil/system version   # desde el PC

# VM de prueba desechable en el PC (pequeña: 1 GiB disco, 512 MiB RAM):
hypergery-cli create-vm --name hgtest-u10 --iso <iso-pequeña> --ram-mib 512 --disk-gb 1
hypergery-cli start hgtest-u10
```

## U10 — shared storage (disco visible en ambos hosts)

> **Requisitos de storage (aprendidos en el UAT del 2026-06-10):**
> - El disco debe estar en **NFS (recomendado nfs4)** o un FS compartido con
>   locks fiables para QEMU/libvirt. **CIFS/SMB (smb2/smb3/fuse.smb) NO está
>   soportado**: el handoff del write-lock de imágenes falla (durable handles)
>   y el preflight del producto lo **rechaza** con error humano. Block
>   migration (U11) sí funciona sobre cualquier FS local.
> - **Preflight manual**: `stat -f -c %T <ruta-del-disco>` en el origen debe
>   devolver `nfs`/`nfs4` (si devuelve `smb2`/`cifs`, U10 shared no procede).
> - **Misma ruta absoluta en ambos hosts** (p. ej. `/mnt/hypergery-nas`).
> - qemu (usuario `libvirt-qemu`) debe poder **leer y escribir** el disco en
>   ambos hosts.
> - Disco con `cache='none'` y, si libvirt no autodetecta el FS como
>   compartido, `shared_filesystems = [ "/mnt/hypergery-nas" ]` en
>   `/etc/libvirt/qemu.conf` + reinicio de libvirtd (verificar MainPID nuevo).
> - Hosts cross-vendor (AMD↔Intel): CPU de la VM con modelo común
>   (p. ej. `qemu64` + `<feature policy='disable' name='svm'/>`), nunca
>   host-passthrough.
> - El origen debe resolver el hostname del destino (entrada en `/etc/hosts`).
>
> Guía completa de montaje: `docs/setup/NFS_SHARED_STORAGE_FOR_LIVE_MIGRATION.md`.

```bash
hypergery-cli v1 migrate-live --vm hgtest-u10 \
  --target qemu+ssh://gery@portatil/system --shared-storage --confirm
```

**Preflight esperado:** pasa (VM running, destino alcanzable, RAM suficiente,
sin `<hostdev>`); estrategia shared.
**PASS si:** la VM nunca se apaga; `downtime_ms` en el resultado/progreso es
< 1000; el destino queda `running`; el origen queda undefined tras confirmar;
`virsh list` en ambos hosts lo confirma (**nunca activa en los dos**).

## U11 — block migration (sin storage compartido)

```bash
hypergery-cli v1 migrate-live --vm hgtest-u11 \
  --target qemu+ssh://gery@portatil/system --block-migration --confirm
```

**PASS si:** los discos viajan por el canal de migración (sin NAS), y el resto
igual que U10 (downtime medido, origen limpio, destino running, no double-active).

## U12 — cancelación a mitad

```bash
# Lanza U10 o U11 y, durante el pre-copy (mira /progress o la salida):
virsh domjobabort hgtest-u12          # o Ctrl-C en la CLI
```

**PASS si:** el origen sigue `running` e intacto; el destino queda limpio (sin
VM definida); el estado en `/progress` es `cancelled`; el journal de migración
no deja la VM bloqueada (`hypergery-cli v1 migrate-journal list` vacío o
liberado tras el rollback).

## Comprobaciones transversales (en los tres)

- **Rollback**: ante cualquier fallo, el origen debe quedar como estaba
  (running) y el destino sin restos.
- **No double-active**: en ningún instante `virsh list` muestra la VM running
  en ambos hosts. Tras un switchover confirmado, `backend.start_vm` del origen
  debe negarse si el journal retiene la entrada.
- **downtime_ms**: anotar el valor real de cada migración en el resultado.
- **qemu+tcp**: probar que `--target qemu+tcp://...` se RECHAZA con error
  humano (control negativo, no necesita red).

## Limpieza

```bash
hypergery-cli delete-vm hgtest-u10 --delete-disks    # en el host donde quedara
hypergery-cli delete-vm hgtest-u11 --delete-disks
hypergery-cli v1 migrate-journal list                 # debe quedar vacío
```

## Registro

Anotar resultados (PASS/FAIL + downtime_ms + incidencias) en
`docs/qa/V1_5_UAT_RESULT.md` al ejecutarlos.
